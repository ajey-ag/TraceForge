import json
import time
from uuid import uuid5

from sqlalchemy import func, select

from packages.core.config import Settings
from packages.core.contracts import Stage, Status
from packages.models.providers import (
    PROMPT_VERSION,
    SYSTEM,
    FakeProvider,
    OpenAIProvider,
    ProviderError,
    prompt,
)
from packages.persistence.lifecycle import transition
from packages.persistence.models import Investigation, Operation
from packages.persistence.queue import owned_job

# USD per million tokens, versioned estimates rather than provider billing observations.
PRICING = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00)}
PRICING_VERSION = "openai-reference-2025-04"


class BudgetExceeded(Exception):
    pass


class Runtime:
    def __init__(self, sessions, store, claim, settings: Settings, policy: dict):
        self.sessions, self.store, self.claim = sessions, store, claim
        self.settings, self.policy = settings, policy

    def check(self):
        with self.sessions.begin() as session:
            owned_job(session, self.claim)

    def stage(self, stage: Stage, reason: str):
        with self.sessions.begin() as session:
            owned_job(session, self.claim)
            row = session.get(Investigation, self.claim.investigation_id)
            transition(session, row, Status.RUNNING, stage, reason)

    def operation(self, key: str, kind: str, request: dict, execute, reconcilable=False) -> dict:
        identity = uuid5(self.claim.investigation_id, key)
        with self.sessions.begin() as session:
            owned_job(session, self.claim)
            previous = session.get(Operation, identity)
            if previous:
                if previous.request != request:
                    raise ValueError("Persisted operation inputs changed; refusing replay")
                if previous.result is not None:
                    return previous.result
                if not reconcilable:
                    raise ProviderError(
                        "Interrupted model call has unknown result; not charged twice"
                    )
            else:
                if kind == "MODEL":
                    calls = session.scalars(
                        select(Operation).where(
                            Operation.investigation_id == self.claim.investigation_id,
                            Operation.kind == "MODEL",
                        )
                    ).all()
                    reserved = sum(call.request.get("reserved_usd", 0) for call in calls)
                    if len(calls) >= self.policy["max_model_calls"]:
                        raise BudgetExceeded("Model-call budget exhausted")
                    if reserved + request["reserved_usd"] > self.policy["max_spend_usd"]:
                        raise BudgetExceeded("Conservative model spend reservation exceeds budget")
                session.add(
                    Operation(
                        id=identity,
                        investigation_id=self.claim.investigation_id,
                        key=key,
                        kind=kind,
                        status="RUNNING",
                        request=request,
                    )
                )
        started = time.monotonic()
        result = execute(identity)
        result["duration_seconds"] = time.monotonic() - started
        artifact = self.store.put(json.dumps(result, sort_keys=True).encode())
        with self.sessions.begin() as session:
            owned_job(session, self.claim)
            row = session.get(Operation, identity)
            row.result = result
            row.artifact = artifact
            row.status = "FAILED" if result.get("error") else "COMPLETED"
            row.ended_at = func.now()
        return result

    def model(self, task: str, context: dict, attempt=0, feedback: dict | None = None) -> dict:
        strategy = self.policy["strategy"]
        signals = {
            "failure_category": context["parsed"]["failure_category"],
            "context_bytes": len(json.dumps(context).encode()),
            "previous_verification_failed": bool(feedback),
            "attempts_consumed": attempt,
            "max_model_calls": self.policy["max_model_calls"],
        }
        strong = strategy == "strong" or (
            strategy == "rule_based"
            and (
                bool(feedback)
                or signals["context_bytes"] > 16000
                or signals["failure_category"] == "UNKNOWN_OR_UNSUPPORTED"
            )
        )
        model = self.settings.strong_model if strong else self.settings.cheap_model
        provider = self.policy["provider"]
        payload = context | {"execution_feedback": feedback}
        if provider == "fake":
            model = "fake-strong-v1" if strong else "fake-cheap-v1"
            reserve = 0.0
        else:
            if model not in PRICING:
                raise ProviderError(
                    "Model has no configured price estimate; refusing unbudgeted call"
                )
            rates = PRICING[model]
            # UTF-8 bytes upper bound tokens conservatively; include schema/system overhead.
            input_bound = len((SYSTEM + prompt(task, payload)).encode()) + 1024
            reserve = (input_bound * rates[0] + 2000 * rates[1]) / 1_000_000
        request = {
            "provider": provider,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "context_sha256": self.store.put(json.dumps(payload, sort_keys=True).encode()),
            "strategy": strategy,
            "routing_inputs": signals,
            "routing_reason": "feedback/complexity escalation" if strong else "lower-cost baseline",
            "reserved_usd": reserve,
            "pricing_version": PRICING_VERSION,
        }

        def execute(identity):
            implementation = FakeProvider() if provider == "fake" else OpenAIProvider(self.settings)
            try:
                generated = implementation.generate(task, payload, model)
                cost = 0.0
                if provider != "fake":
                    cost = reserve
                    if generated.input_tokens is not None and generated.output_tokens is not None:
                        cost = (
                            generated.input_tokens * rates[0] + generated.output_tokens * rates[1]
                        ) / 1_000_000
                return {
                    "payload": generated.payload,
                    "provider": provider,
                    "model": model,
                    "input_tokens": generated.input_tokens,
                    "output_tokens": generated.output_tokens,
                    "estimated_cost_usd": cost,
                    "cost_kind": "zero_fake" if provider == "fake" else "estimated",
                }
            except ProviderError as exc:
                return {
                    "error": str(exc),
                    "estimated_cost_usd": reserve,
                    "cost_kind": "reserved_unknown",
                }

        return self.operation(f"model:{task}:{attempt}", "MODEL", request, execute)

    def usage(self, report):
        with self.sessions() as session:
            calls = session.scalars(
                select(Operation)
                .where(
                    Operation.investigation_id == self.claim.investigation_id,
                    Operation.kind == "MODEL",
                )
                .order_by(Operation.started_at)
            ).all()
            report.model_calls = len(calls)
            report.provider = self.policy["provider"]
            report.observed_model_cost_usd = 0 if report.provider == "fake" else None
            report.estimated_model_cost_usd = sum(
                (call.result or {}).get("estimated_cost_usd", call.request["reserved_usd"])
                for call in calls
            )
            report.routing = [call.request | {"status": call.status} for call in calls]

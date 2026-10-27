import hashlib
import hmac
import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from packages.core.contracts import Submission
from packages.integrations.github import GitHubError, GitHubRun, allowed_repository
from packages.persistence.models import Delivery, Investigation, Job, Transition


def router(settings, sessions):
    routes = APIRouter(prefix="/integrations/github", tags=["GitHub"])

    def enqueue(body: GitHubRun, delivery_id=None):
        try:
            allowed_repository(settings, body.repository)
        except GitHubError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not settings.github_token or not settings.github_token.get_secret_value():
            raise HTTPException(503, "TRACEFORGE_GITHUB_TOKEN is not configured")
        # Same workflow attempt deduplicates manual requests and webhook deliveries.
        key = f"run:{body.repository.lower()}:{body.run_id}:{body.attempt}"
        try:
            with sessions.begin() as session:
                if existing := session.get(Delivery, key):
                    return {"id": existing.investigation_id, "duplicate": True}
                if delivery_id and (existing := session.get(Delivery, delivery_id)):
                    return {"id": existing.investigation_id, "duplicate": True}
                identity = uuid4()
                policy = Submission(fixture_id="calculator-add").model_dump(
                    exclude={"fixture_id", "source"}
                )
                policy["github"] = body.model_dump()
                session.add(
                    Investigation(
                        id=identity,
                        source="github",
                        fixture_id="github-run",
                        repository=body.repository,
                        commit_sha="PENDING_INGESTION",
                        policy=policy,
                    )
                )
                session.flush()
                session.add(Job(investigation_id=identity, max_attempts=settings.max_attempts))
                session.add(
                    Transition(
                        investigation_id=identity,
                        from_status=None,
                        to_status="QUEUED",
                        stage="INGEST",
                        reason="GitHub workflow attempt accepted; metadata will be collected by worker",
                    )
                )
                session.add(Delivery(key=key, investigation_id=identity))
                if delivery_id:
                    session.add(Delivery(key=delivery_id, investigation_id=identity))
            return {"id": identity, "duplicate": False}
        except IntegrityError:
            with sessions() as session:
                existing = session.get(Delivery, key) or session.get(Delivery, delivery_id)
                if existing:
                    return {"id": existing.investigation_id, "duplicate": True}
            raise

    @routes.post("/runs", status_code=202)
    def import_run(body: GitHubRun):
        return enqueue(body)

    @routes.post("/webhook", status_code=202)
    async def webhook(request: Request):
        secret = settings.github_webhook_secret
        if not secret or not secret.get_secret_value():
            raise HTTPException(503, "Webhook secret is not configured")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1_000_000:
                raise HTTPException(413, "Webhook body too large")
        expected = (
            "sha256="
            + hmac.new(secret.get_secret_value().encode(), raw, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(expected, request.headers.get("x-hub-signature-256", "")):
            raise HTTPException(401, "Invalid webhook signature")
        delivery = request.headers.get("x-github-delivery", "")
        if not delivery or len(delivery) > 100:
            raise HTTPException(422, "Valid delivery identifier required")
        try:
            body = json.loads(raw)
            if (
                request.headers.get("x-github-event") != "workflow_run"
                or body.get("action") != "completed"
            ):
                return {"ignored": True}
            run = body["workflow_run"]
            if run.get("conclusion") not in {"failure", "timed_out"}:
                return {"ignored": True}
            command = GitHubRun(
                repository=body["repository"]["full_name"],
                run_id=run["id"],
                attempt=run.get("run_attempt", 1),
            )
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise HTTPException(422, "Malformed workflow webhook") from exc
        return enqueue(command, f"delivery:{delivery}")

    return routes

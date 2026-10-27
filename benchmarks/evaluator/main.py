"""Manually initiated comparable strategy runs; fake results are smoke checks, not research."""
import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import httpx

from benchmarks.evaluator.metrics import summarize
from packages.core.config import Settings
from packages.persistence.database import make_engine, session_factory
from packages.persistence.models import Experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--provider", choices=["fake", "openai"], default="fake")
    parser.add_argument("--strategies", nargs="+", choices=["cheap", "strong", "rule_based"], default=["cheap", "strong", "rule_based"])
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--max-spend-usd", type=float, default=0)
    parser.add_argument("--max-model-calls", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.provider == "openai" and not 0 < args.max_spend_usd <= 10:
        parser.error("Real runs require explicit --max-spend-usd in (0,10] per investigation")
    tasks_path = Path(__file__).parents[1] / "tasks" / "v1.json"
    benchmark = json.loads(tasks_path.read_text())
    payload = {
        "benchmark": benchmark["version"], "benchmark_sha256": hashlib.sha256(tasks_path.read_bytes()).hexdigest(),
        "provider": args.provider, "started_at": datetime.now(UTC).isoformat(),
        "budget_per_investigation": {"max_calls": args.max_model_calls, "max_spend_usd": args.max_spend_usd},
        "dependencies": {name: version(name) for name in ("traceforge", "langgraph", "pydantic")},
        "cache_policy": "Immutable fixture evidence content-addressed; every investigation makes its own model calls",
        "limitations": benchmark["limitations"], "runs": [],
    }
    with httpx.Client(base_url=args.url, timeout=15) as client:
        for strategy in args.strategies:
            for repeat in range(args.repeats):
                for task in benchmark["tasks"]:
                    started = time.monotonic()
                    response = client.post("/investigations", json={
                        "fixture_id": task["fixture_id"], "execution_policy": "repair",
                        "provider": args.provider, "strategy": strategy,
                        "max_model_calls": args.max_model_calls, "max_spend_usd": args.max_spend_usd,
                    })
                    response.raise_for_status()
                    identity = response.json()["id"]
                    deadline = time.monotonic() + 300
                    result = None
                    while time.monotonic() < deadline:
                        response = client.get(f"/investigations/{identity}")
                        response.raise_for_status()
                        detail = response.json()
                        if detail["status"] == "COMPLETED":
                            response = client.get(f"/investigations/{identity}/report")
                            response.raise_for_status()
                            result = response.json()
                            break
                        if detail["status"] in {"FAILED", "CANCELLED"}:
                            result = {"outcome": detail["outcome"], "error": detail["explanation"]}
                            operations = client.get(f"/investigations/{identity}/operations").json()
                            calls = [op for op in operations if op["kind"] == "MODEL"]
                            result["model_calls"] = len(calls)
                            result["estimated_model_cost_usd"] = sum(
                                (op["result"] or {}).get("estimated_cost_usd", op["request"]["reserved_usd"])
                                for op in calls
                            )
                            break
                        time.sleep(.5)
                    if result is None:
                        # Do not silently exclude pending/failed work from an experiment.
                        client.post(f"/investigations/{identity}/cancel")
                        raise RuntimeError(f"Experiment timed out; cancelled {identity}. Run not summarized.")
                    payload["runs"].append(result | {
                        "strategy": strategy, "repeat": repeat, "task": task["id"],
                        "split": task["split"], "wall_seconds": time.monotonic() - started,
                    })
                    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    payload["metrics"] = {
        strategy: summarize([row for row in payload["runs"] if row["strategy"] == strategy])
        for strategy in args.strategies
    }
    payload["finished_at"] = datetime.now(UTC).isoformat()
    engine = make_engine(Settings())
    try:
        with session_factory(engine).begin() as session:
            session.add(Experiment(payload=payload))
    finally:
        engine.dispose()
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["metrics"], indent=2))


if __name__ == "__main__":
    main()

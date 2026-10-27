import time

import httpx

from packages.persistence.queue import LeaseLost
from packages.runner.contracts import ExecutionRequest, ExecutionResult


def run_execution(runtime, mode: str, changes: dict | None = None, attempt=0) -> dict:
    def execute(identity):
        request = ExecutionRequest(
            id=identity, fixture_id="calculator-add", mode=mode, changes=changes or {}
        )
        with httpx.Client(
            base_url=runtime.settings.runner_url,
            timeout=10,
            trust_env=False,
            headers={"Authorization": f"Bearer {runtime.settings.runner_token.get_secret_value()}"},
        ) as client:
            try:
                response = client.post("/executions", json=request.model_dump(mode="json"))
                response.raise_for_status()
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    runtime.check()
                    response = client.get(f"/executions/{identity}")
                    response.raise_for_status()
                    result = ExecutionResult.model_validate(response.json())
                    if result.status != "RUNNING":
                        return result.model_dump()
                    time.sleep(0.25)
                client.delete(f"/executions/{identity}")
                return {"status": "TIMED_OUT", "error": "Controller polling deadline exceeded"}
            except LeaseLost:
                try:
                    client.delete(f"/executions/{identity}")
                except httpx.HTTPError:
                    pass
                raise
            except httpx.HTTPError as exc:
                return {
                    "status": "SETUP_FAILED",
                    "error": f"Runner unavailable: {type(exc).__name__}",
                }

    return runtime.operation(
        f"runner:{mode}:{attempt}",
        "TOOL",
        {"mode": mode, "changes": changes or {}},
        execute,
        reconcilable=True,
    )

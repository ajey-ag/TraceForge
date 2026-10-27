"""Trusted controller. Only this service has Docker access; job containers never do."""

import hashlib
import json
import os
import secrets
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException

from packages.core.config import Settings
from packages.diagnosis.contracts import FileChange, PatchProposal
from packages.diagnosis.retrieval import fixture_source
from packages.ingestion.fixtures import load_fixture
from packages.runner.contracts import ExecutionRequest, ExecutionResult
from packages.verification.patches import validate_patch

settings = Settings()
lock = threading.Lock()
active: dict[str, threading.Event] = {}


def write_result(identity: str, payload: dict):
    root = settings.runner_state
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{identity}.json"
    temporary = root / f"{identity}.tmp"
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, target)


def read_result(identity: str):
    path = settings.runner_state / f"{identity}.json"
    return json.loads(path.read_text()) if path.exists() else None


def remove_container(name):
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)


def execute(request: ExecutionRequest, cancelled: threading.Event, request_hash: str):
    identity = str(request.id)
    name = f"traceforge-job-{identity}"
    result = {"status": "SETUP_FAILED", "error": "Execution did not start"}
    process = None
    try:
        fixture = load_fixture(request.fixture_id)
        source = fixture_source(request.fixture_id)
        image = subprocess.run(
            ["docker", "image", "inspect", settings.runner_image, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if image.returncode:
            raise RuntimeError("Execution image missing; run docker compose build execution-image")
        command = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--label",
            "traceforge.execution=true",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--cpus",
            "1",
            "--pids-limit",
            "64",
            "--tmpfs",
            "/workspace:rw,noexec,nosuid,size=64m,uid=10001,gid=10001",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m,uid=10001,gid=10001",
            "--user",
            "10001:10001",
            image.stdout.strip(),
        ]
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        output = bytearray()
        exceeded = threading.Event()

        def consume():
            while chunk := process.stdout.read(4096):
                if len(output) + len(chunk) > 256000:
                    exceeded.set()
                elif not exceeded.is_set():
                    output.extend(chunk)

        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        process.stdin.write(
            json.dumps(
                {
                    "source": source,
                    "changes": request.changes,
                    "commit_sha": fixture.manifest.commit_sha,
                    "mode": request.mode,
                }
            ).encode()
        )
        process.stdin.close()
        deadline = time.monotonic() + request.timeout_seconds
        while process.poll() is None:
            status = None
            if cancelled.is_set():
                status = "CANCELLED"
            elif exceeded.is_set():
                status = "OUTPUT_LIMIT"
            elif time.monotonic() > deadline:
                status = "TIMED_OUT"
            if status:
                remove_container(name)
                process.kill()
                result = {"status": status, "error": f"Execution stopped: {status}"}
                break
            time.sleep(0.1)
        process.wait(timeout=10)
        reader.join(timeout=5)
        if result["status"] == "SETUP_FAILED":
            try:
                result = ExecutionResult.model_validate_json(output).model_dump()
            except ValueError:
                result = {
                    "status": "SETUP_FAILED",
                    "error": "Executor failed to return a valid report",
                }
        result.setdefault("environment", {}).update(
            {
                "image": settings.runner_image,
                "image_id": image.stdout.strip(),
                "network": "none",
                "memory_bytes": 268435456,
                "cpus": 1,
                "timeout_seconds": request.timeout_seconds,
                "output_limit_bytes": 256000,
                "docker_command": command,
                "container_exit_code": process.returncode,
            }
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {"status": "SETUP_FAILED", "error": str(exc)[:500]}
    finally:
        try:
            remove_container(name)
        except (OSError, subprocess.SubprocessError):
            result.setdefault("limitations", []).append(
                "Container cleanup failed; inspect controller logs"
            )
        with lock:
            write_result(identity, {"request_hash": request_hash, "result": result})
            active.pop(identity, None)


@asynccontextmanager
async def lifespan(app):
    settings.runner_state.mkdir(parents=True, exist_ok=True)
    # Reconcile controller interruption without blindly re-executing repository code.
    for path in settings.runner_state.glob("*.json"):
        record = json.loads(path.read_text())
        if record["result"]["status"] == "RUNNING":
            identity = str(UUID(path.stem))
            remove_container(f"traceforge-job-{identity}")
            record["result"] = {
                "status": "INTERRUPTED",
                "error": "Controller restarted during execution",
            }
            write_result(identity, record)
    yield
    for event in list(active.values()):
        event.set()


def authorize(authorization: str = Header(default="")):
    expected = f"Bearer {settings.runner_token.get_secret_value()}"
    if not secrets.compare_digest(authorization, expected):
        raise HTTPException(401, "Runner authorization required")


app = FastAPI(
    title="TraceForge execution controller", lifespan=lifespan, dependencies=[Depends(authorize)]
)


@app.post("/executions", status_code=202)
def submit(request: ExecutionRequest):
    if request.mode == "reproduce" and request.changes:
        raise HTTPException(422, "Reproduction cannot include a patch")
    if request.mode == "verify":
        try:
            validate_patch(
                PatchProposal(
                    explanation="runner validation",
                    files=[
                        FileChange(path=path, content=content)
                        for path, content in request.changes.items()
                    ],
                ),
                fixture_source(request.fixture_id),
            )
        except (ValueError, SyntaxError) as exc:
            raise HTTPException(422, str(exc)) from exc
    identity = str(request.id)
    request_hash = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
    with lock:
        previous = read_result(identity)
        if previous:
            if previous["request_hash"] != request_hash:
                raise HTTPException(409, "Execution ID already used for different inputs")
            return previous["result"]
        if len(active) >= 2:
            raise HTTPException(429, "Runner concurrency limit reached")
        write_result(identity, {"request_hash": request_hash, "result": {"status": "RUNNING"}})
        event = threading.Event()
        active[identity] = event
        threading.Thread(target=execute, args=(request, event, request_hash), daemon=True).start()
    return {"status": "RUNNING"}


@app.get("/executions/{identity}")
def status(identity: UUID):
    with lock:
        result = read_result(str(identity))
    if result is None:
        raise HTTPException(404, "Execution not found")
    return result["result"]


@app.delete("/executions/{identity}")
def cancel(identity: UUID):
    with lock:
        if event := active.get(str(identity)):
            event.set()
    return {"cancellation_requested": True}

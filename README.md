# TraceForge

**An Adaptive AI Engineer for CI Failure Diagnosis and Verified Repair** — developed
incrementally. The working **Phase 0–1** release ingests a saved Python/pytest failure,
processes it in a separate worker, and returns a persisted, evidence-backed structured
failure report. No model credentials or paid services are required.

```text
POST fixture → PostgreSQL investigation + job → worker parses saved pytest log
             → content-addressed evidence + persisted report → GET report
```

Current support is the controlled `calculator-add` fixture. `DIAGNOSED` means a
deterministic failure summary with a heuristic category; it does not establish a
root cause or imply a repair. The report explicitly says reproduction and verification
were not run. AI diagnosis, isolated execution, patching, GitHub import, and the
Next.js dashboard are later milestones.

## Quick start: Docker Compose

Prerequisites: Git and Docker with the **Linux engine running**, plus Docker Compose.
Run all commands from the TraceForge directory containing `compose.yaml`.

```sh
docker compose up --build -d
docker compose ps
```

Compose starts PostgreSQL, runs `alembic upgrade head`, then starts the API and worker.
First startup downloads images and dependencies. Open:

- API documentation: **http://127.0.0.1:8000/docs**
- Liveness: http://127.0.0.1:8000/health
- Readiness: http://127.0.0.1:8000/ready

The API and database bind to loopback only. Database credentials in Compose are local
demo credentials. Reports and evidence survive service restarts in named volumes.

### Submit the sample (PowerShell)

```powershell
$base = 'http://127.0.0.1:8000'
$job = Invoke-RestMethod -Method Post -Uri "$base/investigations" `
  -ContentType 'application/json' -Body '{"fixture_id":"calculator-add"}'
$job.id
Start-Sleep -Seconds 2
Invoke-RestMethod "$base/investigations/$($job.id)"
Invoke-RestMethod "$base/investigations/$($job.id)/report" | ConvertTo-Json -Depth 12
```

### Submit the sample (Bash)

```sh
curl -sS -X POST http://127.0.0.1:8000/investigations \
  -H 'Content-Type: application/json' -d '{"fixture_id":"calculator-add"}'
# Use the returned id; poll detail until status is COMPLETED.
curl -sS http://127.0.0.1:8000/investigations/RETURNED_ID/report
```

Submission returns **202**. A report request returns **409** until a report exists.
An unknown fixture returns **404** with the available identifiers; malformed identifiers
and unsupported request fields return **422**.

Expected report excerpt:

```json
{
  "fixture_id": "calculator-add",
  "outcome": "DIAGNOSED",
  "parsed": {
    "failure_category": "APPLICATION_CODE_REGRESSION",
    "failed_test_identifiers": ["test_calculator.py::test_add_positive_numbers"],
    "failures": [{
      "test_id": "test_calculator.py::test_add_positive_numbers",
      "exception_type": "AssertionError",
      "message": "assert -1 == 5",
      "traceback": [{"path": "test_calculator.py", "line": 5, "context": "in test_add_positive_numbers"}]
    }]
  },
  "reproduction_status": "NOT_RUN_SAVED_LOG_ONLY",
  "patch_status": "NOT_PROPOSED",
  "verification_status": "NOT_RUN",
  "model_calls": 0,
  "observed_model_cost_usd": 0
}
```

The full report also includes parsing limitations, the exact fixture commit, and
SHA-256 evidence references. [An actual retrieved report](docs/example-report.json)
is included; its investigation/evidence IDs are specific to the recorded demo database.

## Python development setup

Selected runtime: **Python 3.12.10**; supported Python range: 3.12.x. Dependencies
are fully locked in `uv.lock` for Windows and Linux. Use **uv 0.13.5**:

```sh
python -m pip install --user uv==0.13.5
python -m uv sync --frozen --extra dev
docker compose up -d db
python -m uv run --frozen --extra dev alembic upgrade head
```

Stop Compose API/worker first if switching from the full-container setup:
`docker compose stop api worker`. In two separate terminals:

```sh
# Terminal 1
python -m uv run --frozen --extra dev uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
# Terminal 2
python -m uv run --frozen --extra dev traceforge-worker
```

The defaults connect to PostgreSQL at `127.0.0.1:54329` and store local artifacts
under `.artifacts/`. Optional overrides are listed in `.env.example`; create `.env`
only if needed. Local processes must share the same database and artifact root.
Compose deliberately uses its own service URL and shared artifact volume instead.

### Checks

```sh
python -m uv run --frozen --extra dev ruff check .
python -m uv run --frozen --extra dev ruff format --check .
python -m uv run --frozen --extra dev pytest -q
```

Without a test database URL, PostgreSQL integration tests explicitly skip. To run
the complete suite against real PostgreSQL:

```powershell
$env:TRACEFORGE_TEST_DATABASE_URL = 'postgresql+psycopg://traceforge:traceforge@127.0.0.1:54329/traceforge'
python -m uv run --frozen --extra dev pytest -q
```

On Bash, use `export TRACEFORGE_TEST_DATABASE_URL=postgresql+psycopg://traceforge:traceforge@127.0.0.1:54329/traceforge`.
Tests create and drop a uniquely named disposable database; the supplied database is
not truncated. The configured test user therefore needs `CREATEDB` privileges.

For Linux checks entirely inside Docker:

```sh
docker compose run --rm --no-deps \
  -e TRACEFORGE_TEST_DATABASE_URL=postgresql+psycopg://traceforge:traceforge@db:5432/traceforge \
  worker python -m pytest -q -p no:cacheprovider
```

### Explicitly reproduce the intentionally broken sample

```sh
python -m uv run --frozen --extra dev python -m benchmarks.reproduce
```

This reconstructs the fixture's exact Git commit in a temporary directory and runs
the manifest test command. **Expected exit code: 1**, with one failed test and
`assert -1 == 5`. The helper is an owned-fixture developer utility, not the future
isolated runner. The saved log records the original Windows capture environment;
the same sample can be checked explicitly in Linux:

```sh
docker compose run --rm --no-deps \
  --workdir /app/benchmarks/fixtures/calculator-add/source worker \
  python -m pytest -q --tb=short --color=no -p no:cacheprovider test_calculator.py
```

`pytest` defaults to `tests/`, so the intentionally broken sample is excluded from
TraceForge's own suite. To deliberately regenerate the saved capture and manifest,
use `python -m benchmarks.reproduce --record` in the installed environment; it also
returns 1 because the sample fails. Review regenerated evidence before using it.

## API surface

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Process liveness, independent of PostgreSQL |
| `GET /ready` | Checks database schema revision and writable artifact storage |
| `GET /fixtures` | Supported fixture identifiers |
| `POST /investigations` | Atomically persists an investigation and queued job |
| `GET /investigations` | History; `status`, `limit` (1–100), and `offset` filters |
| `GET /investigations/{id}` | Status, stage, timeline, job, and attempt history |
| `GET /investigations/{id}/report` | Persisted validated report |
| `GET /investigations/{id}/evidence/{evidence_id}` | Hash-checked original evidence |
| `POST /investigations/{id}/cancel` | Cancels queued/running work and fences publication |

Submission accepts `source: "fixture"`, `fixture_id`,
`execution_policy: "saved_evidence_only"`, `max_attempts` (1–10, capped by server
configuration), and zero-valued `max_model_calls`/`max_spend_usd`. The latter are
deliberately fixed to zero until model orchestration exists. Repeated explicit
submissions create separate investigations; artifacts are deduplicated by hash.

## Operations and troubleshooting

- `docker compose logs api worker migrate` shows service and structured application logs.
- `docker compose restart api worker` preserves investigations and artifacts.
- `docker compose down` stops services while preserving volumes. Adding `-v` **deletes data**.
- Readiness 503: check PostgreSQL availability, run migrations, and check artifact permissions.
- A queued investigation needs a running worker. Poll `/investigations/{id}` for attempts/errors.
- A terminated worker's job becomes claimable after its lease expires (default 30 seconds).
  Exhausted attempts become a visible `FAILED` investigation rather than disappearing.
- A missing/corrupt evidence blob returns 503; the report itself remains in PostgreSQL.
- On Windows, start Docker Desktop's Linux engine and use `127.0.0.1`, rather than
  `localhost`, for the host database URL; IPv6 resolution caused connection stalls here.
- If port 8000 or 54329 is occupied, adjust the Compose binding and corresponding client URL.
- The pinned Starlette test client emits an `httpx` deprecation warning; it does not
  prevent the current tests passing. Update the test transport with future dependency upgrades.
- Local-only application: authentication is planned before any remote exposure.

## Project documentation

- [Architecture and package conventions](docs/architecture.md)
- [Implementation plan](docs/implementation-plan.md)
- [Verified progress and next milestone](docs/progress.md)
- [Decisions](docs/decisions.md)
- [Evaluation boundaries](docs/evaluation.md)
- [Reproducible demo](docs/demo.md)

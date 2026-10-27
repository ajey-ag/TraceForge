# Architecture

## Implemented Phase 0–1 flow

1. FastAPI validates a fixture submission against an explicit identifier registry.
2. One transaction stores the investigation, execution policy, initial lifecycle
   event, and job. The HTTP request does not parse logs or execute investigations.
3. A separate worker claims eligible jobs using `SELECT ... FOR UPDATE SKIP LOCKED`.
4. It verifies fixture identity/log hash, parses pytest text deterministically, and
   stores immutable log/manifest/report artifacts through the artifact-store interface.
5. A fenced transaction publishes evidence metadata, the JSON report, the terminal
   lifecycle event, and the completed job/attempt together.
6. API report/detail/evidence routes read persisted state, including after restarts.

## Modules and installation

One installable distribution, `traceforge`, is defined by `pyproject.toml`. Regular
Python packages map directly to the requested repository layout:

- `apps.api`: HTTP boundary and application factory.
- `apps.worker`: CLI process, queue polling, heartbeat, shutdown handling.
- `packages.core`: settings, JSON logging, Pydantic contracts, lifecycle/stage enums.
- `packages.persistence`: SQLAlchemy models, database health, lifecycle transitions, queue.
- `packages.ingestion`: fixture registry/manifest validation, pytest parser, report pipeline.
- `packages.artifacts`: storage protocol and local content-addressed implementation.
- `benchmarks`: packaged fixture assets and explicit source-reconstruction utility.
- `infra/migrations`: immutable Alembic revisions, operated from the source checkout/image.
- `scripts/demo.py`: repository-local HTTP/restart smoke check.

Install with `uv sync --frozen --extra dev`. Imports use full names such as
`packages.persistence.queue` and `apps.api.main`; no `sys.path` or `PYTHONPATH` changes.
Fixture assets are included in wheels and accessed using `importlib.resources`.
The generic top-level `apps`/`packages` names are an intentional monorepo convention;
this is one application distribution, not independently published component libraries.

## Durable queue semantics

- Job claim and attempt creation commit atomically; competing workers skip locked rows.
- Leases use PostgreSQL time. Default duration is 30 seconds, heartbeat every 10 seconds.
- Every claim gets a new random ownership token; expired workers cannot renew or publish.
- Lease recovery marks the abandoned attempt and creates the next attempt, bounded
  by the investigation's effective attempt limit.
- Retryable storage/database failures use persisted exponential backoff (2, 4, …,
  capped at 60 seconds). Invalid fixture data and unexpected programming errors fail
  without automatic retries. Errors expose classifications rather than connection secrets.
- If recording an error fails during a database outage, lease recovery remains the fallback.
- Graceful shutdown finishes the current small ingestion before stopping. Abrupt termination
  leaves a lease that another worker can reclaim; no in-memory-only queue exists.
- Cancellation takes the job lock before changing state. An active parser may finish local
  computation, but its ownership check prevents publishing after cancellation.

This provides at-least-once computation and fenced publication, not exactly-once external
side effects. Evidence IDs are deterministic per investigation/type; artifact keys are
content hashes. A crash before the final DB commit may leave unreferenced immutable blobs.
They are safe to reuse; garbage collection is deferred. No tool/model external calls exist yet.

## Data and lifecycle

Tables: investigations, jobs, job_attempts, transitions, evidence, reports. Every accepted
investigation has one job; evidence type is unique per investigation; there is one final
report. JSONB stores validated report snapshots and execution policies.

Lifecycle is separate from execution stage. The successful implemented path is
`QUEUED/INGEST → RUNNING/INGEST → COMPLETED/REPORT`. Retry/recovery/cancellation events
also carry reasons. `DIAGNOSED` is a deterministic summary outcome; `UNSUPPORTED` is
used when the parser cannot classify the evidence. Operational failure ends in `FAILED`
with `NO_VERIFIED_REPAIR` and an explanation, without fabricating a report.

## Local deployment

Compose runs PostgreSQL 17.7, a one-shot migration service, API, and worker. API/worker
share an artifact volume; PostgreSQL has its own data volume. Application containers run
as non-root. Only loopback ports are published. `/health` is liveness; `/ready` requires
the expected migration revision and accessible writable storage. Readiness does not
claim that a worker is alive; queued job age/attempts are observable through detail routes.

## Later boundaries

The future runner will be a separate restricted execution environment, not code inside
API requests or the current worker container. LangGraph/provider abstractions arrive
with model-driven diagnosis. Next.js/TypeScript UI and GitHub ingestion arrive in Phase 5.
No arbitrary repository code, user-supplied command, network retrieval, or model call is
accepted by this release.

# Decisions

## 001 — One distribution with explicit module boundaries

Use the requested `apps/` and `packages/` layout as regular Python packages installed
by setuptools. Avoid a multi-project build system for a solo developer. Fixture data
ships in the wheel. Add modules only when their milestone needs them.

## 002 — Real PostgreSQL for queue verification

Use SQLAlchemy synchronous sessions, Alembic, PostgreSQL 17.7, and psycopg 3. SQLite
cannot establish the required locking behavior. Tests create disposable PostgreSQL
databases when explicitly configured; otherwise those tests visibly skip.

## 003 — Leases, tokens, and atomic publication

Use `SKIP LOCKED` for claiming, per-claim tokens for fencing, heartbeat renewal, persisted
attempt history, and bounded retries. Final job status and report metadata commit in
the same transaction. Content-addressed blobs are written first and may be orphaned by
a crash, but a stale worker cannot publish a second report.

## 004 — Deterministic saved-evidence report first

Phase 1 intentionally has no LLM dependency or graph. Assertion failures receive a
heuristic application-regression category; import and selected configuration errors
have separate categories. Unknown evidence remains unknown. Multiple failures keep
separate exceptions; ambiguous section matching is explicitly noted instead of inventing
tracebacks. Root-cause reasoning and evidence-citation validation belong to Phase 2.

## 005 — Reconstructible owned fixture rather than nested Git metadata

Store the two source files, actual pytest capture, and manifest. A developer helper
reconstructs the exact Git commit with canonical LF source bytes and fixed author/date,
verifies the SHA, and runs the command in a temporary directory. This avoids committing
a nested `.git` directory or confusing the fixture with the application's parent repo.
The failing sample stays outside default discovery. Saved log bytes use canonical LF,
enforced by `.gitattributes`, so Git newline conversion cannot invalidate the manifest hash.

## 006 — Local content-addressed storage

The storage protocol exposes put/read/probe. Local implementation validates digest keys,
confines paths, uses temporary writes plus atomic replacement, and checks hashes on reads.
Identical ingestion content is reused. Object storage and garbage collection are deferred.

## 007 — Runtime/dependency reproducibility

- Python selected: 3.12.10; application supports 3.12.x.
- Dependency resolver/build tooling: uv 0.13.5; full resolution in `uv.lock`.
- PostgreSQL selected: 17.7 (`postgres:17.7-bookworm`).
- FastAPI 0.162.0, Pydantic 2.14.1, SQLAlchemy 2.0.55, Alembic 1.20.1,
  psycopg 3.3.6, pytest 8.4.2, Ruff 0.17.2 at initial resolution.
- Container runtime: `python:3.12.10-slim`; tags pin releases, not immutable image digests.
  A future benchmark release should additionally pin image digests.

Observed host prerequisites: Python 3.12.10, Docker 29.6.2, Compose 5.3.1, Git 2.54.0.
Host database URLs use `127.0.0.1` after `localhost` connection stalls on this Windows
environment. PostgreSQL remains Linux-hosted under Docker.

## 008 — Test/developer tools in initial local image

The Compose image includes the locked development extra so reproducible checks can run
on Linux without a second Dockerfile. Production optimization is deferred until there
is a remote-deployment milestone. Authentication must precede that milestone.

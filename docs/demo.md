# Reproducible demonstration

1. From the project root, run `docker compose up --build -d`.
2. Open `http://127.0.0.1:8000/docs`. Show `/health`, `/ready`, and `/fixtures`.
3. Submit `{"fixture_id":"calculator-add"}` to `POST /investigations`.
4. Poll `GET /investigations/{id}`. Show `QUEUED → RUNNING → COMPLETED`,
   the separate `INGEST/REPORT` stages, and persisted attempt history.
5. Retrieve `/investigations/{id}/report`. Explain `assert -1 == 5`, traceback line 5,
   heuristic classification, evidence hashes, and parsing limitations.
6. Retrieve `/investigations/{id}/evidence/{evidence_id}` using an ID from the report.
7. Restart with `docker compose restart api worker`; retrieve the same report again.
8. Show the explicit sample reproduction command in README. It fails intentionally
   with exit 1. The investigation itself only ingests saved evidence.

## Automated live smoke check

After Python development setup and Compose startup:

```sh
python -m uv run --frozen --extra dev python -m scripts.demo --restart-services
```

The script makes actual HTTP requests, verifies the report/evidence, restarts the API
and worker, and checks report equality. It exits nonzero on failure. Optionally save
the retrieved report using `--save-report docs/example-report.json`. The existing
example was captured from a successful real API/worker run; UUIDs change on new submissions.

## Queue demonstration

Stop the worker (`docker compose stop worker`), submit the sample, and show `QUEUED`.
Start it (`docker compose start worker`) and show the persisted result. Multiple workers
can be started with `docker compose up -d --scale worker=2`; return to one with
`docker compose up -d --scale worker=1`.

For reproducible interruption/retry behavior, run the PostgreSQL integration suite.
It includes concurrent claims, expired-lease recovery, a deliberately crashed claim
process followed by a fresh worker process, and cancellation that blocks stale publication.

## Presentation boundaries

This is a functioning deterministic ingestion demo with zero model calls. The completed
investigation is not a verified repair. AI hypotheses, a secure runner, patches, GitHub
integration, and a dashboard are upcoming milestones; no simulated UI or invented model
results are presented.

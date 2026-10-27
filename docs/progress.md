# Progress

## Remaining milestones: implementation in progress

- Phase 2 implementation added: provider boundary, deterministic fake provider, OpenAI
  HTTP adapter, LangGraph workflow, AST source inspection, versioned prompts, citation
  validation, persisted model-call identities, conservative budgets, and routing records.
- Check after diagnosis integration: **33 tests passed** using real PostgreSQL, including
  malformed model output, invalid citations, missing credentials, and recoverable timeout behavior.
- No paid provider request has been made. The real adapter still requires a credentialed smoke test.
- Controlled runner and repair verification are being implemented next; their acceptance
  is not yet claimed. The phase table below records the previously completed baseline.

## Phase 0–1: completed

The first usable vertical slice is implemented and verified:

**Submit saved fixture → persist investigation/job → dedicated worker parses evidence
→ persist structured report → retrieve through API.**

### Delivered

- Installable Python 3.12 project, cross-platform `uv.lock`, validated configuration,
  structured logging, FastAPI application, PostgreSQL migrations, and local Compose services.
- Liveness/readiness endpoints, fixture discovery, submission/history/detail/report/evidence
  routes, status filtering, attempt timelines, and cancellation.
- PostgreSQL atomic claiming, ownership-token fencing, leases/heartbeats, retry backoff,
  bounded attempts, and expired-lease recovery with abandoned-attempt records.
- Deterministic pytest parser and explicit unknown/unsupported/ambiguous parsing limitations.
- Hash-validated fixture log and manifest, content-addressed local artifacts, persisted reports.
- Owned intentionally broken sample with reconstructible Git SHA
  `f827c3ab8f6c29e42ffb26daa79e529e7becd6c3` and explicit reproduction command.
- Canonical LF captures and `.gitattributes` prevent fresh-checkout newline/hash drift.
- Setup, architecture, decisions, evaluation boundaries, demo instructions, and actual
  retrieved example report in `docs/example-report.json`.

### Observed verification

| Check | Result |
| --- | --- |
| Windows Python suite with real PostgreSQL | 26 passed |
| Linux container suite with real PostgreSQL, including final LF-capture fix | 26 passed |
| Ruff lint | Passed |
| Ruff format check | Passed (38 Python files checked) |
| Alembic schema/model comparison | No new upgrade operations detected |
| Migration downgrade → upgrade roundtrip in disposable DB | Passed |
| Eight concurrent worker claims | Eight unique claims; no duplicate ownership |
| Crash after persisted claim, then fresh worker process | Recovered; abandoned and completed attempts persisted |
| Expired leases, heartbeat, stale publication, backoff, attempt exhaustion | Passed |
| Queued/running cancellation | Passed; stale publication rejected |
| Live Compose HTTP → worker → report | Passed |
| API + worker restart, same report retrieved | Passed, exact JSON equality |
| Wheel-installed package/fixture loaded outside source directory | Passed from `/tmp` in container |
| Owned sample on Windows and Linux | Expected one failure, `assert -1 == 5`, exit 1 |
| Fixture files canonical LF | Confirmed with Git line-ending inspection |

No required Phase 0–1 checks remain blocked. One upstream Starlette/httpx test-client
deprecation warning remains; tests pass. Docker was initially stopped and was started.
Host `localhost` PostgreSQL connections stalled; `127.0.0.1` resolved this and is now
the documented default. No paid model calls, external repository integrations, or
verified repairs were performed.

Latest recorded live demonstration: investigation
`f33956e5-39b0-4464-ba3b-c47449a679d1`, outcome `DIAGNOSED`, saved assertion evidence,
`NOT_RUN_SAVED_LOG_ONLY` reproduction, `NOT_PROPOSED` patch, `NOT_RUN` verification.
IDs are local demonstration records, not globally available examples.

## Remaining roadmap

| Phase | Status | Main deliverable |
| --- | --- | --- |
| 0 Foundation | Complete | Reproducible application/database/fixture setup |
| 1 Ingestion | Complete | Durable fixture-to-report workflow |
| 2 AI diagnosis | Not started | Provider interface, fake/real providers, grounded structured hypotheses |
| 3 Reproduction | Not started | Isolated Linux runner and reproducible environment manifests |
| 4 Repair | Not started | Candidate patches and independent protected-check verification |
| 5 Product integration | Not started | Next.js dashboard and GitHub Actions ingestion |
| 6 Adaptation/MCP | Not started | Comparable routing baselines, later learned routing and tool adapter |
| 7 Research | Not started | Versioned benchmark, experiments, analysis, and paper |

Two of eight phases are complete; phase count is not an effort estimate. Most work
remains in controlled execution, trustworthy verification, integration, and evaluation.

## Next actionable milestone: Phase 2

Introduce the internal model-provider interface and deterministic fake provider first,
then structured diagnosis contracts, relevant-code retrieval, versioned prompts, and
evidence-reference validation. Add one real provider behind environment credentials,
with timeout/malformed-output handling and explicit fake-versus-real run metadata.
Acceptance is grounded diagnosis, not patching. Keep default automated tests offline.

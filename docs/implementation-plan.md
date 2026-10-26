# Implementation plan

## Current increment: Phase 0 + Phase 1

1. Establish Python 3.12 packaging, locked dependencies, configuration, JSON logging,
   PostgreSQL migrations, local Compose services, and health/readiness checks.
2. Create one deterministic, intentionally broken source snapshot with a reproducible
   Git commit, actual saved pytest output, and a validated manifest.
3. Add transactional investigation submission, history/detail/report endpoints,
   content-addressed evidence, and a separately runnable worker.
4. Use PostgreSQL row locks, leases, heartbeat, fencing tokens, bounded retries,
   attempt history, and expired-lease recovery. Parse saved logs without AI calls.
5. Verify behavior with unit tests, real PostgreSQL integration tests, and a live
   Compose API → worker → report demo, including service restart persistence.
6. Record exact setup/demo commands and observed verification outcomes.

## Later milestones (not implemented in this increment)

- Phase 2: evidence-backed diagnosis, fake provider, one real provider, citation validation.
- Phase 3: isolated Linux runner, exact checkout, reproduction and environment manifests.
- Phase 4: patch candidates, protected paths, independent verification, bounded attempts.
- Phase 5: Next.js dashboard and incremental GitHub integration.
- Phase 6: baseline routing strategies, measured escalation, later learned router and MCP.
- Phase 7: versioned benchmark, held-out evaluation, cost/success analysis and paper.

Each milestone must include a usable increment, relevant checks, documentation,
and an explicit distinction between implemented, observed, and planned behavior.

# Evaluation

## Current evidence

This release validates an ingestion system, not AI diagnosis quality or repair success.
One original synthetic fixture (`calculator-add`, CC0-1.0) has a reconstructible exact
commit, explicit pytest command, expected assertion failure, captured log hash, and
capture runtime/platform metadata. Additional parser tests use small synthetic log
strings covering import errors, configuration problems, ambiguity, and truncated logs.

The fixture is development/demo data. It is not a held-out benchmark and does not
establish generalization to arbitrary Python repositories or pytest plugins. Category
labels are heuristics and are reported as such.

## What can be measured now

- Submission/report persistence and evidence integrity.
- Queue claim uniqueness, heartbeat behavior, bounded retry, and crash recovery.
- Extraction of test identifiers, exceptions, messages, and traceback entries.
- Explicit unsupported/unknown handling and limitations.

No model runs occurred: observed model-call count and cost are zero. There were no
repair attempts and no verified repairs. Cost per verified repair is **undefined**,
not zero. Total infrastructure cost, token usage, latency distributions, and comparative
strategy effectiveness have not been measured.

## Future research protocol

Before strategy experiments, version task provenance/licensing, repository/commit,
environment, budgets, hidden checks, and development/validation/held-out split. Split
by repository or bug family when possible. Keep hidden checks outside agent-accessible
workspaces. Record prompt/model identifiers, experiment dates, real versus fake provider
usage, dependency/image versions, all failed attempts, and immutable-artifact cache hits.

Compare cheaper-only, stronger-only, rule-based, and eventually learned escalation with
equal tools/task inputs and documented budgets. Measure verified repair/reproduction/
regression rates, unsupported/unresolved rates, total cost, cost per verified repair,
model usage, median/tail latency, and repeated-run variation. Do not claim novelty or
significance before related-work review and analysis. See implementation-plan.md for
the milestone order.

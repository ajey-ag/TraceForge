from uuid import uuid5

from packages.artifacts.local import ArtifactStore
from packages.core.config import Settings
from packages.core.contracts import EvidenceRef, Report, Stage, Status
from packages.diagnosis.retrieval import fixture_source, inspect_source
from packages.ingestion.fixtures import load_fixture
from packages.ingestion.pytest_parser import PARSER_VERSION, parse_pytest_log
from packages.integrations.github import GitHubError, GitHubRun, download_run, encoded_metadata
from packages.persistence.lifecycle import transition
from packages.persistence.models import Evidence, Investigation, StoredReport
from packages.persistence.queue import Claim, clear_lease, finish_attempt, owned_job


def process_claim(
    sessions, store: ArtifactStore, claim: Claim, settings: Settings | None = None
) -> Report:
    with sessions() as session:
        investigation = session.get(Investigation, claim.investigation_id)
        fixture_id, commit_sha = investigation.fixture_id, investigation.commit_sha
        policy = investigation.policy
        input_source = investigation.source
    if input_source == "github":
        from packages.orchestration.runtime import Runtime

        runtime = Runtime(sessions, store, claim, settings or Settings(), policy)

        def collect(identity):
            try:
                return download_run(runtime.settings, GitHubRun.model_validate(policy["github"]))
            except GitHubError as exc:
                return {"error": str(exc)}

        collected = runtime.operation(
            "github:ingest", "TOOL", policy["github"], collect, reconcilable=True
        )
        if collected.get("error"):
            log = collected["error"].encode()
            manifest_bytes = b"{}"
        else:
            log = collected["log"].encode()
            manifest_bytes = encoded_metadata(collected)
            commit_sha = collected["metadata"]["commit_sha"]
            with sessions.begin() as session:
                owned_job(session, claim)
                row = session.get(Investigation, claim.investigation_id)
                row.commit_sha = commit_sha
                row.repository = collected["metadata"]["repository"]
    else:
        fixture = load_fixture(fixture_id)
        if fixture.manifest.commit_sha != commit_sha:
            raise ValueError("Fixture commit changed since submission")
        log, manifest_bytes = fixture.log, fixture.manifest_bytes
    parsed = parse_pytest_log(log.decode("utf-8", errors="replace"))
    evidence = []
    rows = []
    inputs = [
        ("PYTEST_LOG", log, "pytest.txt"),
        (
            "FIXTURE_MANIFEST" if input_source == "fixture" else "GITHUB_METADATA",
            manifest_bytes,
            "manifest.json",
        ),
    ]
    source_files = {}
    if policy["execution_policy"] != "saved_evidence_only":
        source_files = fixture_source(fixture_id)
        inputs.extend(
            (f"SOURCE:{path}", content.encode(), path) for path, content in source_files.items()
        )
    for kind, content, source in inputs:
        key = store.put(content)
        identity = uuid5(claim.investigation_id, kind)
        evidence.append(EvidenceRef(id=identity, type=kind, sha256=key, artifact=key))
        rows.append(
            Evidence(
                id=identity,
                investigation_id=claim.investigation_id,
                type=kind,
                artifact=key,
                content_hash=key,
                source_path=f"{fixture_id}/{source}",
                line_start=1,
                line_end=len(content.splitlines()),
                commit_sha=commit_sha,
                method=PARSER_VERSION if kind == "PYTEST_LOG" else "fixture-manifest-v1",
            )
        )
    supported = parsed.failure_category != "UNKNOWN_OR_UNSUPPORTED"
    report = Report(
        investigation_id=claim.investigation_id,
        source=input_source,
        fixture_id=fixture_id,
        commit_sha=commit_sha,
        outcome="DIAGNOSED" if supported else "UNSUPPORTED",
        summary=(
            f"Parsed {len(parsed.failures)} saved pytest failure(s); "
            f"heuristic category: {parsed.failure_category}. No repair was attempted."
        ),
        parsed=parsed,
        evidence=evidence,
    )
    if input_source == "github":
        report.limitations.append(
            "GitHub logs are ingested only; external repository execution is not enabled."
        )
        if collected.get("error"):
            report.limitations.append(collected["error"])
    if policy["execution_policy"] != "saved_evidence_only":
        from packages.orchestration.runtime import Runtime
        from packages.orchestration.workflow import run_workflow

        context = {
            "parsed": parsed.model_dump(),
            "source": inspect_source(source_files),
            "evidence": [entry.model_dump(mode="json") for entry in evidence],
        }
        report = run_workflow(
            Runtime(sessions, store, claim, settings or Settings(), policy), report, context
        )
    report_key = store.put(report.model_dump_json(indent=2).encode())
    with sessions.begin() as session:
        job = owned_job(session, claim)  # Fence stale workers before publishing any DB results.
        investigation = session.get(Investigation, claim.investigation_id)
        session.add_all(rows)
        session.add(
            StoredReport(
                investigation_id=claim.investigation_id,
                payload=report.model_dump(mode="json"),
                artifact=report_key,
            )
        )
        transition(session, investigation, Status.COMPLETED, Stage.REPORT, report.summary)
        investigation.outcome = report.outcome
        investigation.explanation = report.summary
        job.status = "COMPLETED"
        job.error = None
        clear_lease(job)
        finish_attempt(session, claim.token, "COMPLETED")
    return report

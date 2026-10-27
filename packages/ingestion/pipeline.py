from uuid import uuid5

from packages.artifacts.local import ArtifactStore
from packages.core.config import Settings
from packages.core.contracts import EvidenceRef, Report, Stage, Status
from packages.diagnosis.retrieval import fixture_source, inspect_source
from packages.ingestion.fixtures import load_fixture
from packages.ingestion.pytest_parser import PARSER_VERSION, parse_pytest_log
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
    fixture = load_fixture(fixture_id)
    if fixture.manifest.commit_sha != commit_sha:
        raise ValueError("Fixture commit changed since submission")
    parsed = parse_pytest_log(fixture.log.decode("utf-8", errors="replace"))
    evidence = []
    rows = []
    inputs = [
        ("PYTEST_LOG", fixture.log, "pytest.txt"),
        ("FIXTURE_MANIFEST", fixture.manifest_bytes, "manifest.json"),
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

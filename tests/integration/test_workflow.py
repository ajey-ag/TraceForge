import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.main import create_app
from apps.worker.main import run_once
from packages.artifacts.local import LocalArtifacts
from packages.ingestion.pipeline import process_claim
from packages.persistence.models import Evidence, Investigation, Job, JobAttempt, StoredReport
from packages.persistence.queue import LeaseLost, claim_job, fail_job, heartbeat

pytestmark = pytest.mark.integration


def submit(settings, attempts=3):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/investigations",
            json={
                "fixture_id": "calculator-add",
                "max_attempts": attempts,
            },
        )
        assert response.status_code == 202
        return UUID(response.json()["id"])


def expire(db, claim):
    with db.begin() as session:
        session.get(Job, claim.job_id).lease_expires_at = func.now() - timedelta(seconds=1)


def test_submission_worker_persistence_and_evidence(db, postgres_settings):
    identity = submit(postgres_settings)
    with TestClient(create_app(postgres_settings)) as client:
        assert client.get("/ready").status_code == 200
        assert client.get(f"/investigations/{identity}/report").status_code == 409
    assert run_once(
        db, LocalArtifacts(postgres_settings.artifact_root), postgres_settings, "worker-1"
    )
    # A new application/engine sees persisted state, rather than process memory.
    with TestClient(create_app(postgres_settings)) as client:
        report = client.get(f"/investigations/{identity}/report").json()
        assert report["outcome"] == "DIAGNOSED"
        assert report["verification_status"] == "NOT_RUN"
        assert report["reproduction_status"] == "NOT_RUN_SAVED_LOG_ONLY"
        assert len(report["evidence"]) == 2
        evidence_id = report["evidence"][0]["id"]
        evidence = client.get(f"/investigations/{identity}/evidence/{evidence_id}")
        assert evidence.status_code == 200
        assert "assert -1 == 5" in evidence.text
        detail = client.get(f"/investigations/{identity}").json()
        assert [t["to_status"] for t in detail["timeline"]] == ["QUEUED", "RUNNING", "COMPLETED"]
        assert detail["attempts"][0]["status"] == "COMPLETED"
        assert len(client.get("/investigations?status=COMPLETED").json()["items"]) == 1
    assert not run_once(
        db, LocalArtifacts(postgres_settings.artifact_root), postgres_settings, "worker-2"
    )


def test_concurrent_claims_are_unique(db, postgres_settings):
    for _ in range(8):
        submit(postgres_settings)
    barrier = threading.Barrier(8)

    def claim(index):
        barrier.wait(timeout=10)
        return claim_job(db, f"worker-{index}", 30)

    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(claim, range(8)))
    assert all(claims)
    assert len({claim.job_id for claim in claims}) == 8
    assert claim_job(db, "ninth-worker", 30) is None


def test_interruption_recovers_and_fences_old_worker(db, postgres_settings):
    identity = submit(postgres_settings)
    original = claim_job(db, "interrupted", 30)
    expire(db, original)
    replacement = claim_job(db, "replacement", 30)
    assert replacement.job_id == original.job_id
    assert replacement.attempt == 2
    assert not heartbeat(db, original, 30)
    store = LocalArtifacts(postgres_settings.artifact_root)
    with pytest.raises(LeaseLost):
        process_claim(db, store, original)
    process_claim(db, store, replacement)
    with db() as session:
        assert session.get(StoredReport, identity) is not None
        attempts = session.scalars(select(JobAttempt).order_by(JobAttempt.number)).all()
        assert [a.status for a in attempts] == ["ABANDONED", "COMPLETED"]
        assert len(session.scalars(select(Evidence)).all()) == 2


def test_heartbeat_extends_lease(db, postgres_settings):
    submit(postgres_settings)
    claim = claim_job(db, "alive", 30)
    with db.begin() as session:
        job = session.get(Job, claim.job_id)
        job.lease_expires_at = func.now() + timedelta(seconds=1)
    assert heartbeat(db, claim, 30)
    assert claim_job(db, "competitor", 30) is None
    with db() as session:
        job = session.get(Job, claim.job_id)
        assert job.lease_expires_at > session.scalar(select(func.now())) + timedelta(seconds=20)


def test_expired_last_attempt_becomes_visible_failure(db, postgres_settings):
    identity = submit(postgres_settings, attempts=1)
    claim = claim_job(db, "interrupted", 30)
    expire(db, claim)
    assert claim_job(db, "recovery", 30) is None
    with db() as session:
        row = session.get(Investigation, identity)
        assert row.status == "FAILED"
        assert "Attempt limit" in row.explanation


def test_retry_backoff_and_attempt_limit(db, postgres_settings):
    identity = submit(postgres_settings, attempts=2)
    first = claim_job(db, "first", 30)
    fail_job(db, first, "OSError: temporary storage failure", retryable=True)
    assert claim_job(db, "too-soon", 30) is None
    with db.begin() as session:
        session.get(Job, first.job_id).available_at = func.now() - timedelta(seconds=1)
    second = claim_job(db, "second", 30)
    fail_job(db, second, "OSError: storage still unavailable", retryable=True)
    with db() as session:
        assert session.get(Investigation, identity).status == "FAILED"
    assert claim_job(db, "third", 30) is None


@pytest.mark.parametrize("running", [False, True])
def test_cancel_prevents_publication(db, postgres_settings, running):
    identity = submit(postgres_settings)
    claim = claim_job(db, "worker", 30) if running else None
    with TestClient(create_app(postgres_settings)) as client:
        assert client.post(f"/investigations/{identity}/cancel").json()["status"] == "CANCELLED"
        assert client.post(f"/investigations/{identity}/cancel").status_code == 200
    if claim:
        with pytest.raises(LeaseLost):
            process_claim(db, LocalArtifacts(postgres_settings.artifact_root), claim)
    assert claim_job(db, "next", 30) is None
    with db() as session:
        assert session.get(StoredReport, identity) is None


def test_process_crash_is_recovered_by_fresh_worker_process(db, postgres_settings):
    identity = submit(postgres_settings)
    env = os.environ | {
        "TRACEFORGE_DATABASE_URL": postgres_settings.database_url,
        "TRACEFORGE_ARTIFACT_ROOT": str(postgres_settings.artifact_root),
    }
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; from packages.core.config import Settings; "
                "from packages.persistence.database import make_engine, session_factory; "
                "from packages.persistence.queue import claim_job; "
                "sessions = session_factory(make_engine(Settings())); "
                "claim = claim_job(sessions, 'crashed-process', 30); "
                "assert claim is not None; os._exit(17)"
            ),
        ],
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert crashed.returncode == 17, crashed.stderr.decode()
    with db.begin() as session:
        job = session.scalar(select(Job).where(Job.investigation_id == identity))
        assert job.status == "RUNNING"
        # Advance the lease expiry rather than sleeping for 30 seconds.
        job.lease_expires_at = func.now() - timedelta(seconds=1)
    worker = subprocess.run(
        [sys.executable, "-m", "apps.worker.main", "--once"],
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert worker.returncode == 0, worker.stderr.decode()
    with db() as session:
        assert session.get(StoredReport, identity).payload["outcome"] == "DIAGNOSED"
        attempts = session.scalars(select(JobAttempt).order_by(JobAttempt.number)).all()
        assert [attempt.status for attempt in attempts] == ["ABANDONED", "COMPLETED"]


def test_migration_matches_models_and_roundtrips(db, postgres_settings):
    # The session fixture directs Alembic to this disposable database only.
    config = Config("alembic.ini")
    command.check(config)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)

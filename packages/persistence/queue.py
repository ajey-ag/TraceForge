from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update

from packages.core.contracts import Stage, Status
from packages.persistence.lifecycle import transition
from packages.persistence.models import Investigation, Job, JobAttempt


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    investigation_id: UUID
    token: UUID
    attempt: int


class LeaseLost(Exception):
    pass


def finish_attempt(session, token: UUID, status: str, error: str | None = None):
    session.execute(
        update(JobAttempt)
        .where(JobAttempt.lease_token == token)
        .values(
            status=status,
            ended_at=func.now(),
            error=error,
        )
    )


def clear_lease(job: Job):
    job.lease_owner = job.lease_token = job.lease_expires_at = None


def claim_job(sessions, owner: str, lease_seconds: int) -> Claim | None:
    # All claim decisions and associated state changes are in one PostgreSQL transaction.
    with sessions.begin() as session:
        while True:
            job = session.scalar(
                select(Job)
                .where(
                    or_(
                        and_(Job.status == "QUEUED", Job.available_at <= func.now()),
                        and_(Job.status == "RUNNING", Job.lease_expires_at <= func.now()),
                    )
                )
                .order_by(Job.available_at, Job.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            investigation = session.get(Investigation, job.investigation_id)
            recovered = job.status == "RUNNING"
            if recovered:
                finish_attempt(session, job.lease_token, "ABANDONED", "Lease expired")
            if job.attempt_count >= job.max_attempts:
                job.status = "FAILED"
                job.error = "Attempt limit exhausted after worker lease expired"
                clear_lease(job)
                transition(session, investigation, Status.FAILED, Stage.INGEST, job.error)
                investigation.outcome = "NO_VERIFIED_REPAIR"
                investigation.explanation = job.error
                session.flush()
                continue
            token = uuid4()
            now = session.scalar(select(func.now()))
            job.status = "RUNNING"
            job.lease_owner = owner
            job.lease_token = token
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.attempt_count += 1
            session.add(
                JobAttempt(
                    job_id=job.id,
                    number=job.attempt_count,
                    lease_token=token,
                    worker=owner,
                    status="RUNNING",
                )
            )
            transition(
                session,
                investigation,
                Status.RUNNING,
                Stage.INGEST,
                "Recovered expired lease" if recovered else "Worker claimed persisted job",
            )
            return Claim(job.id, job.investigation_id, token, job.attempt_count)


def owned_job(session, claim: Claim) -> Job:
    job = session.scalar(
        select(Job)
        .where(
            Job.id == claim.job_id,
            Job.status == "RUNNING",
            Job.lease_token == claim.token,
            Job.lease_expires_at > func.now(),
        )
        .with_for_update()
    )
    if job is None:
        raise LeaseLost("Lease expired, was reassigned, or job was cancelled")
    return job


def heartbeat(sessions, claim: Claim, lease_seconds: int) -> bool:
    with sessions.begin() as session:
        result = session.execute(
            update(Job)
            .where(
                Job.id == claim.job_id,
                Job.status == "RUNNING",
                Job.lease_token == claim.token,
                Job.lease_expires_at > func.now(),
            )
            .values(
                heartbeat_at=func.now(),
                lease_expires_at=func.now() + timedelta(seconds=lease_seconds),
            )
        )
        return result.rowcount == 1


def fail_job(sessions, claim: Claim, error: str, retryable: bool) -> None:
    with sessions.begin() as session:
        job = owned_job(session, claim)
        investigation = session.get(Investigation, claim.investigation_id)
        retry = retryable and job.attempt_count < job.max_attempts
        job.error = error
        job.status = "QUEUED" if retry else "FAILED"
        job.available_at = func.now() + timedelta(seconds=min(2**job.attempt_count, 60))
        clear_lease(job)
        finish_attempt(session, claim.token, "FAILED", error)
        transition(session, investigation, Status(job.status), Stage.INGEST, error)
        if not retry:
            investigation.outcome = "NO_VERIFIED_REPAIR"
            investigation.explanation = error

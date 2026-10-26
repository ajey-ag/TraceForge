from sqlalchemy import func
from sqlalchemy.orm import Session

from packages.core.contracts import Stage, Status
from packages.persistence.models import Investigation, Transition

ALLOWED = {
    Status.QUEUED: {Status.RUNNING, Status.CANCELLED, Status.FAILED},
    Status.RUNNING: {
        Status.RUNNING,
        Status.QUEUED,
        Status.COMPLETED,
        Status.FAILED,
        Status.CANCELLED,
        Status.NEEDS_INPUT,
    },
    Status.NEEDS_INPUT: {Status.QUEUED, Status.CANCELLED},
    Status.COMPLETED: set(),
    Status.FAILED: set(),
    Status.CANCELLED: set(),
}


def transition(
    session: Session,
    investigation: Investigation,
    status: Status,
    stage: Stage,
    reason: str,
) -> None:
    if status not in ALLOWED[Status(investigation.status)]:
        raise ValueError(f"Invalid transition {investigation.status} -> {status}")
    session.add(
        Transition(
            investigation_id=investigation.id,
            from_status=investigation.status,
            to_status=status,
            stage=stage,
            reason=reason,
        )
    )
    investigation.status = status
    investigation.stage = stage
    investigation.updated_at = func.now()

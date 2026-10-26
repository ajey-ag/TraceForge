import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from packages.artifacts.local import LocalArtifacts
from packages.core.config import Settings
from packages.core.contracts import Report, Stage, Status, Submission
from packages.core.logging import configure_logging
from packages.ingestion.fixtures import FIXTURE_IDS, load_fixture
from packages.persistence.database import check_database, make_engine, session_factory
from packages.persistence.lifecycle import transition
from packages.persistence.models import (
    Evidence,
    Investigation,
    Job,
    JobAttempt,
    StoredReport,
    Transition,
)
from packages.persistence.queue import clear_lease, finish_attempt

logger = logging.getLogger(__name__)


def investigation_view(row: Investigation) -> dict:
    return {
        name: getattr(row, name)
        for name in (
            "id",
            "source",
            "fixture_id",
            "repository",
            "commit_sha",
            "status",
            "stage",
            "policy",
            "outcome",
            "explanation",
            "created_at",
            "updated_at",
        )
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings)
    sessions = session_factory(engine)
    store = LocalArtifacts(settings.artifact_root)

    @asynccontextmanager
    async def lifespan(app):
        configure_logging(settings.log_level)
        yield
        engine.dispose()

    app = FastAPI(title="TraceForge", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessions = sessions

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logger.error("Database request failed", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=503, content={"detail": "Database unavailable; check /ready"}
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            check_database(engine)
            store.probe()
        except (SQLAlchemyError, RuntimeError, OSError):
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "detail": "Check database, migrations, and artifact storage",
                },
            )
        return {"status": "ready"}

    @app.get("/fixtures")
    def fixtures():
        return {"fixtures": list(FIXTURE_IDS)}

    @app.post("/investigations", status_code=202)
    def submit(body: Submission):
        try:
            fixture = load_fixture(body.fixture_id)
        except KeyError as exc:
            raise HTTPException(404, detail=exc.args[0]) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(503, detail="Packaged fixture is unavailable or invalid") from exc
        policy = body.model_dump(exclude={"fixture_id", "source"})
        policy["max_attempts"] = min(body.max_attempts, settings.max_attempts)
        with sessions.begin() as session:
            investigation = Investigation(
                fixture_id=body.fixture_id,
                repository=fixture.manifest.repository,
                commit_sha=fixture.manifest.commit_sha,
                policy=policy,
            )
            session.add(investigation)
            session.flush()
            session.add(Job(investigation_id=investigation.id, max_attempts=policy["max_attempts"]))
            session.add(
                Transition(
                    investigation_id=investigation.id,
                    from_status=None,
                    to_status="QUEUED",
                    stage="INGEST",
                    reason="Fixture submission accepted",
                )
            )
        return investigation_view(investigation)

    @app.get("/investigations")
    def history(
        status: Status | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        query = select(Investigation).order_by(Investigation.created_at.desc(), Investigation.id)
        if status:
            query = query.where(Investigation.status == status)
        with sessions() as session:
            rows = session.scalars(query.limit(limit).offset(offset)).all()
            return {
                "items": [investigation_view(row) for row in rows],
                "limit": limit,
                "offset": offset,
            }

    def require_investigation(session, identity):
        row = session.get(Investigation, identity)
        if row is None:
            raise HTTPException(404, detail="Investigation not found")
        return row

    @app.get("/investigations/{identity}")
    def detail(identity: UUID):
        with sessions() as session:
            row = require_investigation(session, identity)
            result = investigation_view(row)
            result["timeline"] = [
                {
                    "from_status": event.from_status,
                    "to_status": event.to_status,
                    "stage": event.stage,
                    "reason": event.reason,
                    "at": event.created_at,
                }
                for event in session.scalars(
                    select(Transition)
                    .where(
                        Transition.investigation_id == identity,
                    )
                    .order_by(Transition.id)
                )
            ]
            job = session.scalar(select(Job).where(Job.investigation_id == identity))
            result["job"] = {
                "id": job.id,
                "status": job.status,
                "attempt_count": job.attempt_count,
                "max_attempts": job.max_attempts,
                "error": job.error,
            }
            result["attempts"] = [
                {
                    "number": attempt.number,
                    "worker": attempt.worker,
                    "status": attempt.status,
                    "started_at": attempt.started_at,
                    "ended_at": attempt.ended_at,
                    "error": attempt.error,
                }
                for attempt in session.scalars(
                    select(JobAttempt)
                    .where(
                        JobAttempt.job_id == job.id,
                    )
                    .order_by(JobAttempt.number)
                )
            ]
            return result

    @app.get("/investigations/{identity}/report", response_model=Report)
    def report(identity: UUID):
        with sessions() as session:
            row = require_investigation(session, identity)
            saved = session.get(StoredReport, identity)
            if saved is None:
                raise HTTPException(
                    409, detail=f"Report unavailable; investigation is {row.status}"
                )
            return saved.payload

    @app.get("/investigations/{identity}/evidence/{evidence_id}")
    def evidence(identity: UUID, evidence_id: UUID):
        with sessions() as session:
            row = session.scalar(
                select(Evidence).where(
                    Evidence.id == evidence_id,
                    Evidence.investigation_id == identity,
                )
            )
            if row is None:
                raise HTTPException(404, detail="Evidence not found in this investigation")
            try:
                content = store.read(row.artifact)
            except (OSError, ValueError) as exc:
                raise HTTPException(503, detail="Evidence artifact missing or corrupt") from exc
            return Response(
                content,
                media_type="text/plain",
                headers={
                    "ETag": f'"{row.content_hash}"',
                    "X-Content-Type-Options": "nosniff",
                },
            )

    @app.post("/investigations/{identity}/cancel")
    def cancel(identity: UUID):
        with sessions.begin() as session:
            # Consistent job-before-investigation lock order with worker publication.
            job = session.scalar(
                select(Job).where(Job.investigation_id == identity).with_for_update()
            )
            row = require_investigation(session, identity)
            if row.status == "CANCELLED":
                return investigation_view(row)
            if row.status not in {"QUEUED", "RUNNING", "NEEDS_INPUT"}:
                raise HTTPException(409, detail="Investigation is already terminal")
            if job.lease_token:
                finish_attempt(session, job.lease_token, "CANCELLED", "Cancelled by user")
            job.status = "CANCELLED"
            clear_lease(job)
            transition(session, row, Status.CANCELLED, Stage(row.stage), "Cancelled by user")
            row.explanation = "Cancelled by user; no further results will be published"
        return investigation_view(row)

    return app


app = create_app()

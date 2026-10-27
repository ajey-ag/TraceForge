import argparse
import logging
import signal
import socket
import threading
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from packages.artifacts.local import LocalArtifacts
from packages.core.config import Settings
from packages.core.logging import configure_logging
from packages.ingestion.pipeline import process_claim
from packages.persistence.database import check_database, make_engine, session_factory
from packages.persistence.queue import LeaseLost, claim_job, fail_job, heartbeat

logger = logging.getLogger(__name__)


def run_once(sessions, store, settings: Settings, owner: str) -> bool:
    claim = claim_job(sessions, owner, settings.lease_seconds)
    if claim is None:
        return False
    context = {
        "job_id": str(claim.job_id),
        "investigation_id": str(claim.investigation_id),
        "attempt": claim.attempt,
    }
    logger.info("Job claimed", extra=context)
    stop = threading.Event()

    def renew():
        while not stop.wait(settings.lease_seconds / 3):
            try:
                if not heartbeat(sessions, claim, settings.lease_seconds):
                    return
            except SQLAlchemyError:
                logger.warning(
                    "Heartbeat failed; final publication still requires lease", extra=context
                )

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        process_claim(sessions, store, claim, settings)
        logger.info("Report persisted", extra=context)
    except LeaseLost:
        logger.info("Stopped stale or cancelled job", extra=context)
    except Exception as exc:
        # Keep connection details/secrets out of persisted error messages and logs.
        error = f"{type(exc).__name__}: ingestion failed"
        logger.error(error, extra=context)
        try:
            fail_job(sessions, claim, error, retryable=isinstance(exc, (OSError, SQLAlchemyError)))
        except (LeaseLost, SQLAlchemyError):
            logger.warning("Unable to record failure; lease recovery will reconcile", extra=context)
    finally:
        stop.set()
        thread.join(timeout=5)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process persisted TraceForge fixture jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one job, then exit")
    args = parser.parse_args()
    settings = Settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings)
    sessions = session_factory(engine)
    store = LocalArtifacts(settings.artifact_root)
    stop = threading.Event()
    owner = f"{socket.gethostname()[:50]}-{uuid4()}"
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        check_database(engine)
        store.probe()
        logger.info("Worker ready")
        while not stop.is_set():
            try:
                worked = run_once(sessions, store, settings, owner)
            except SQLAlchemyError:
                logger.warning("Database unavailable; retrying queue poll")
                worked = False
            if args.once:
                break
            if not worked:
                stop.wait(settings.poll_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

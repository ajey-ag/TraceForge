from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(20), default="fixture")
    fixture_id: Mapped[str] = mapped_column(String(80))
    repository: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    stage: Mapped[str] = mapped_column(String(30), default="INGEST")
    policy: Mapped[dict] = mapped_column(JSONB)
    outcome: Mapped[str | None] = mapped_column(String(40))
    explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_investigations_created_at", "created_at"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    investigation_id: Mapped[UUID] = mapped_column(ForeignKey("investigations.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_jobs_claim", "status", "available_at", "lease_expires_at"),)


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    number: Mapped[int] = mapped_column(Integer)
    lease_token: Mapped[UUID] = mapped_column(unique=True)
    worker: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("job_id", "number"),)


class Transition(Base):
    __tablename__ = "transitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    investigation_id: Mapped[UUID] = mapped_column(ForeignKey("investigations.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    investigation_id: Mapped[UUID] = mapped_column(ForeignKey("investigations.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    artifact: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_path: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    commit_sha: Mapped[str] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(String(80))
    __table_args__ = (UniqueConstraint("investigation_id", "type"),)


class StoredReport(Base):
    __tablename__ = "reports"
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id"), primary_key=True
    )
    payload: Mapped[dict] = mapped_column(JSONB)
    artifact: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

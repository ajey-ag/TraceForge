"""Durable investigations, jobs, attempts, transitions, evidence, and reports."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "investigations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("fixture_id", sa.String(80), nullable=False),
        sa.Column("repository", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("policy", pg.JSONB(), nullable=False),
        sa.Column("outcome", sa.String(40)),
        sa.Column("explanation", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_investigations_created_at", "investigations", ["created_at"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Uuid(),
            sa.ForeignKey("investigations.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("lease_owner", sa.String(100)),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "available_at", "lease_expires_at"])
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), unique=True, nullable=False),
        sa.Column("worker", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("job_id", "number"),
    )
    op.create_table(
        "transitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "investigation_id", sa.Uuid(), sa.ForeignKey("investigations.id"), nullable=False
        ),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_transitions_investigation_id", "transitions", ["investigation_id"])
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id", sa.Uuid(), sa.ForeignKey("investigations.id"), nullable=False
        ),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("artifact", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("line_start", sa.Integer()),
        sa.Column("line_end", sa.Integer()),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("method", sa.String(80), nullable=False),
        sa.UniqueConstraint("investigation_id", "type"),
    )
    op.create_index("ix_evidence_investigation_id", "evidence", ["investigation_id"])
    op.create_table(
        "reports",
        sa.Column(
            "investigation_id", sa.Uuid(), sa.ForeignKey("investigations.id"), primary_key=True
        ),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("artifact", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    for name in ("reports", "evidence", "transitions", "job_attempts", "jobs", "investigations"):
        op.drop_table(name)

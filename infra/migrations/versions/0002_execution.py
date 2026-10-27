"""Execution identities, patch verification, integration deduplication and experiments."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_execution"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id", sa.Uuid(), sa.ForeignKey("investigations.id"), nullable=False
        ),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("result", JSONB()),
        sa.Column("artifact", sa.Text()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("investigation_id", "key"),
    )
    op.create_index("ix_operations_investigation_id", "operations", ["investigation_id"])
    op.create_table(
        "patch_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "investigation_id", sa.Uuid(), sa.ForeignKey("investigations.id"), nullable=False
        ),
        sa.Column("parent_commit", sa.String(40), nullable=False),
        sa.Column("artifact", sa.Text(), nullable=False),
        sa.Column("changed_files", JSONB(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
    )
    op.create_index(
        "ix_patch_candidates_investigation_id", "patch_candidates", ["investigation_id"]
    )
    op.create_table(
        "verification_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patch_id", sa.Uuid(), sa.ForeignKey("patch_candidates.id"), nullable=False),
        sa.Column(
            "investigation_id", sa.Uuid(), sa.ForeignKey("investigations.id"), nullable=False
        ),
        sa.Column("payload", JSONB(), nullable=False),
    )
    op.create_index(
        "ix_verification_runs_investigation_id", "verification_runs", ["investigation_id"]
    )
    op.create_table(
        "deliveries",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column(
            "investigation_id", sa.Uuid(), sa.ForeignKey("investigations.id"), nullable=False
        ),
    )
    op.create_table(
        "experiments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    for name in (
        "experiments",
        "deliveries",
        "verification_runs",
        "patch_candidates",
        "operations",
    ):
        op.drop_table(name)

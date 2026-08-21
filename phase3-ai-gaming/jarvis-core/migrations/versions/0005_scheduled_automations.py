"""scheduled automations

Revision ID: 0005_scheduled_automations
Revises: 0004_orchestration_runs_workers
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_scheduled_automations"
down_revision = "0004_orchestration_runs_workers"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "personal_ops_scheduled_automations",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("automation_key", sa.String(length=120), nullable=False, unique=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="paused"),
        sa.Column("schedule_kind", sa.String(length=40), nullable=False, server_default="daily"),
        sa.Column("schedule", json_type(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False, server_default="America/New_York"),
        sa.Column("parameters", json_type(), nullable=False),
        sa.Column("channels", json_type(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("approval_id", sa.String(length=40), nullable=True),
        sa.Column("created_by", sa.String(length=80), nullable=False, server_default="jarvis-core"),
        sa.Column("updated_by", sa.String(length=80), nullable=False, server_default="jarvis-core"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_personal_ops_scheduled_automations_status_next", "personal_ops_scheduled_automations", ["status", "next_run_at"])
    op.create_index("ix_personal_ops_scheduled_automations_job_type", "personal_ops_scheduled_automations", ["job_type"])


def downgrade():
    op.drop_index("ix_personal_ops_scheduled_automations_job_type", table_name="personal_ops_scheduled_automations")
    op.drop_index("ix_personal_ops_scheduled_automations_status_next", table_name="personal_ops_scheduled_automations")
    op.drop_table("personal_ops_scheduled_automations")

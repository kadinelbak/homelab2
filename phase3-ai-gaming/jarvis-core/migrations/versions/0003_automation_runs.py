"""automation run history

Revision ID: 0003_automation_runs
Revises: 0002_personal_ops_phase4
Create Date: 2026-08-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_automation_runs"
down_revision = "0002_personal_ops_phase4"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "personal_ops_automation_runs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("automation_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output", json_type(), nullable=False),
        sa.Column("safe_summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_personal_ops_automation_runs_key_started", "personal_ops_automation_runs", ["automation_key", "started_at"])


def downgrade():
    op.drop_index("ix_personal_ops_automation_runs_key_started", table_name="personal_ops_automation_runs")
    op.drop_table("personal_ops_automation_runs")

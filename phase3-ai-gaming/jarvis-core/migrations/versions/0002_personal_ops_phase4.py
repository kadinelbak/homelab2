"""personal ops phase 4

Revision ID: 0002_personal_ops_phase4
Revises: 0001_initial_jarvis_core
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_personal_ops_phase4"
down_revision = "0001_initial_jarvis_core"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "personal_ops_evidence",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), sa.ForeignKey("personal_ops_projects.id"), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("evidence_type", sa.String(length=80), nullable=False),
        sa.Column("uri", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("tags", json_type(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "personal_ops_maintenance_records",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("service_name", sa.String(length=120), nullable=False),
        sa.Column("record_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", json_type(), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "personal_ops_daily_briefs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("brief_date", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("generated_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("personal_ops_daily_briefs")
    op.drop_table("personal_ops_maintenance_records")
    op.drop_table("personal_ops_evidence")

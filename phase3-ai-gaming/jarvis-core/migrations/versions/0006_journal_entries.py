"""journal entries

Revision ID: 0006_journal_entries
Revises: 0005_scheduled_automations
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_journal_entries"
down_revision = "0005_scheduled_automations"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "personal_ops_journal_entries",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("entry_date", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("structured", json_type(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_personal_ops_journal_entries_entry_date", "personal_ops_journal_entries", ["entry_date"])


def downgrade():
    op.drop_index("ix_personal_ops_journal_entries_entry_date", table_name="personal_ops_journal_entries")
    op.drop_table("personal_ops_journal_entries")

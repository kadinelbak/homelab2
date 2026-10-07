"""people notes

Revision ID: 0006_people_notes
Revises: 0005_scheduled_automations
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_people_notes"
down_revision = "0005_scheduled_automations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "people_notes",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("person", sa.String(length=120), nullable=False),
        sa.Column("person_key", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("noted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_people_notes_person_key", "people_notes", ["person_key"])


def downgrade():
    op.drop_index("ix_people_notes_person_key", table_name="people_notes")
    op.drop_table("people_notes")

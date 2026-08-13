"""initial jarvis core schema

Revision ID: 0001_initial_jarvis_core
Revises:
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_jarvis_core"
down_revision = None
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "jarvis_requests",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("user_id", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True, unique=True),
        sa.Column("correlation_id", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_structured_intents",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("request_id", sa.String(length=40), sa.ForeignKey("jarvis_requests.id"), nullable=False),
        sa.Column("intent_type", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("requires_clarification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("clarification_question", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_tool_definitions",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("required_permissions", json_type(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_proposed_actions",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("request_id", sa.String(length=40), sa.ForeignKey("jarvis_requests.id"), nullable=False),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("tool_version", sa.String(length=40), nullable=False),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("arguments", json_type(), nullable=False),
        sa.Column("preview", json_type(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_approval_requests",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("proposed_action_id", sa.String(length=40), sa.ForeignKey("jarvis_proposed_actions.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(length=80), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_execution_attempts",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("proposed_action_id", sa.String(length=40), sa.ForeignKey("jarvis_proposed_actions.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column("safe_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "jarvis_execution_results",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("execution_attempt_id", sa.String(length=40), sa.ForeignKey("jarvis_execution_attempts.id"), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_verification_results",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("execution_result_id", sa.String(length=40), sa.ForeignKey("jarvis_execution_results.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_audit_events",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("correlation_id", sa.String(length=80), nullable=False),
        sa.Column("causation_id", sa.String(length=80), nullable=True),
        sa.Column("sensitivity", sa.String(length=40), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_outbox_events",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_model_invocations",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("request_id", sa.String(length=40), sa.ForeignKey("jarvis_requests.id"), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("purpose", sa.String(length=80), nullable=False),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_notifications",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("user_id", sa.String(length=80), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jarvis_calendar_events",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("calendar_target", sa.String(length=120), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_action_id", sa.String(length=40), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "personal_ops_projects",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("area", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "personal_ops_tasks",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("project_id", sa.String(length=40), sa.ForeignKey("personal_ops_projects.id"), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("effort_level", sa.String(length=40), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("tags", json_type(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    for table in (
        "personal_ops_tasks",
        "personal_ops_projects",
        "jarvis_calendar_events",
        "jarvis_notifications",
        "jarvis_model_invocations",
        "jarvis_outbox_events",
        "jarvis_audit_events",
        "jarvis_verification_results",
        "jarvis_execution_results",
        "jarvis_execution_attempts",
        "jarvis_approval_requests",
        "jarvis_proposed_actions",
        "jarvis_tool_definitions",
        "jarvis_structured_intents",
        "jarvis_requests",
    ):
        op.drop_table(table)

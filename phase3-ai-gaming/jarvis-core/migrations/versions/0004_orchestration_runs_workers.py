"""orchestration runs jobs and workers

Revision ID: 0004_orchestration_runs_workers
Revises: 0003_automation_runs
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_orchestration_runs_workers"
down_revision = "0003_automation_runs"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "jarvis_orchestration_runs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("user_request", sa.Text(), nullable=False),
        sa.Column("request_context", json_type(), nullable=False),
        sa.Column("requested_by", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default="L0"),
        sa.Column("model_profile", sa.String(length=120), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_jarvis_orchestration_runs_status_created", "jarvis_orchestration_runs", ["status", "created_at"])

    op.create_table(
        "jarvis_orchestration_jobs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("run_id", sa.String(length=40), sa.ForeignKey("jarvis_orchestration_runs.id"), nullable=False),
        sa.Column("parent_job_id", sa.String(length=40), sa.ForeignKey("jarvis_orchestration_jobs.id"), nullable=True),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("capability", sa.String(length=120), nullable=False),
        sa.Column("worker_selector", json_type(), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_state", sa.String(length=40), nullable=False, server_default="not_required"),
        sa.Column("input", json_type(), nullable=False),
        sa.Column("output", json_type(), nullable=False),
        sa.Column("error", json_type(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_jarvis_orchestration_jobs_status_capability", "jarvis_orchestration_jobs", ["status", "capability"])
    op.create_index("ix_jarvis_orchestration_jobs_run", "jarvis_orchestration_jobs", ["run_id", "created_at"])

    op.create_table(
        "jarvis_job_dependencies",
        sa.Column("job_id", sa.String(length=40), sa.ForeignKey("jarvis_orchestration_jobs.id"), primary_key=True),
        sa.Column("depends_on_job_id", sa.String(length=40), sa.ForeignKey("jarvis_orchestration_jobs.id"), primary_key=True),
        sa.Column("dependency_type", sa.String(length=40), nullable=False, server_default="success_required"),
    )

    op.create_table(
        "jarvis_artifacts",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("run_id", sa.String(length=40), sa.ForeignKey("jarvis_orchestration_runs.id"), nullable=False),
        sa.Column("job_id", sa.String(length=40), sa.ForeignKey("jarvis_orchestration_jobs.id"), nullable=True),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("path_or_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=80), nullable=True),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "jarvis_workers",
        sa.Column("id", sa.String(length=120), primary_key=True),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("worker_type", sa.String(length=80), nullable=False),
        sa.Column("hostname", sa.String(length=160), nullable=True),
        sa.Column("os", sa.String(length=80), nullable=True),
        sa.Column("version", sa.String(length=80), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="online"),
        sa.Column("capabilities", json_type(), nullable=False),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jarvis_workers_status_type", "jarvis_workers", ["status", "worker_type"])

    op.create_table(
        "jarvis_worker_capabilities",
        sa.Column("worker_id", sa.String(length=120), sa.ForeignKey("jarvis_workers.id"), primary_key=True),
        sa.Column("capability", sa.String(length=120), primary_key=True),
        sa.Column("version", sa.String(length=40), nullable=False, server_default="1"),
        sa.Column("risk_ceiling", sa.String(length=40), nullable=False, server_default="L1"),
        sa.Column("metadata", json_type(), nullable=False),
    )

    op.create_table(
        "jarvis_orchestration_events",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("run_id", sa.String(length=40), sa.ForeignKey("jarvis_orchestration_runs.id"), nullable=True),
        sa.Column("job_id", sa.String(length=40), sa.ForeignKey("jarvis_orchestration_jobs.id"), nullable=True),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_jarvis_orchestration_events_run_created", "jarvis_orchestration_events", ["run_id", "created_at"])
    op.create_index("ix_jarvis_orchestration_events_job_created", "jarvis_orchestration_events", ["job_id", "created_at"])


def downgrade():
    op.drop_index("ix_jarvis_orchestration_events_job_created", table_name="jarvis_orchestration_events")
    op.drop_index("ix_jarvis_orchestration_events_run_created", table_name="jarvis_orchestration_events")
    op.drop_table("jarvis_orchestration_events")
    op.drop_table("jarvis_worker_capabilities")
    op.drop_index("ix_jarvis_workers_status_type", table_name="jarvis_workers")
    op.drop_table("jarvis_workers")
    op.drop_table("jarvis_artifacts")
    op.drop_table("jarvis_job_dependencies")
    op.drop_index("ix_jarvis_orchestration_jobs_run", table_name="jarvis_orchestration_jobs")
    op.drop_index("ix_jarvis_orchestration_jobs_status_capability", table_name="jarvis_orchestration_jobs")
    op.drop_table("jarvis_orchestration_jobs")
    op.drop_index("ix_jarvis_orchestration_runs_status_created", table_name="jarvis_orchestration_runs")
    op.drop_table("jarvis_orchestration_runs")

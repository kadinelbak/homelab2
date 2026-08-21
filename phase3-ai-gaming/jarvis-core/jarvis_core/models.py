from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RequestRecord(Base):
    __tablename__ = "jarvis_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(80))
    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    correlation_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StructuredIntentRecord(Base):
    __tablename__ = "jarvis_structured_intents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("jarvis_requests.id"))
    intent_type: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON)
    requires_clarification: Mapped[bool] = mapped_column(Boolean, default=False)
    clarification_question: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolDefinitionRecord(Base):
    __tablename__ = "jarvis_tool_definitions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    version: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40))
    required_permissions: Mapped[list] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProposedActionRecord(Base):
    __tablename__ = "jarvis_proposed_actions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("jarvis_requests.id"))
    tool_name: Mapped[str] = mapped_column(String(120))
    tool_version: Mapped[str] = mapped_column(String(40))
    risk_level: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    arguments: Mapped[dict] = mapped_column(JSON)
    preview: Mapped[dict] = mapped_column(JSON)
    requires_approval: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalRequestRecord(Base):
    __tablename__ = "jarvis_approval_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    proposed_action_id: Mapped[str] = mapped_column(ForeignKey("jarvis_proposed_actions.id"))
    status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(80))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutionAttemptRecord(Base):
    __tablename__ = "jarvis_execution_attempts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    proposed_action_id: Mapped[str] = mapped_column(ForeignKey("jarvis_proposed_actions.id"))
    status: Mapped[str] = mapped_column(String(40))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_category: Mapped[str | None] = mapped_column(String(80))
    safe_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionResultRecord(Base):
    __tablename__ = "jarvis_execution_results"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    execution_attempt_id: Mapped[str] = mapped_column(ForeignKey("jarvis_execution_attempts.id"))
    outcome: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VerificationResultRecord(Base):
    __tablename__ = "jarvis_verification_results"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    execution_result_id: Mapped[str] = mapped_column(ForeignKey("jarvis_execution_results.id"))
    status: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEventRecord(Base):
    __tablename__ = "jarvis_audit_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(120))
    schema_version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120))
    actor: Mapped[str] = mapped_column(String(80))
    correlation_id: Mapped[str] = mapped_column(String(80))
    causation_id: Mapped[str | None] = mapped_column(String(80))
    sensitivity: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEventRecord(Base):
    __tablename__ = "jarvis_outbox_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelInvocationRecord(Base):
    __tablename__ = "jarvis_model_invocations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str | None] = mapped_column(ForeignKey("jarvis_requests.id"))
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(80))
    invocation_metadata: Mapped[dict] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationRecord(Base):
    __tablename__ = "jarvis_notifications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(80))
    channel: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CalendarEventRecord(Base):
    __tablename__ = "jarvis_calendar_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    calendar_target: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_action_id: Mapped[str] = mapped_column(String(40), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectRecord(Base):
    __tablename__ = "personal_ops_projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    area: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="active")
    goal: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    next_action: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskRecord(Base):
    __tablename__ = "personal_ops_tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("personal_ops_projects.id"))
    title: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(40), default="open")
    priority: Mapped[int] = mapped_column(Integer, default=3)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    effort_level: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str | None] = mapped_column(String(80))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvidenceRecord(Base):
    __tablename__ = "personal_ops_evidence"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("personal_ops_projects.id"))
    title: Mapped[str] = mapped_column(String(240))
    evidence_type: Mapped[str] = mapped_column(String(80))
    uri: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaintenanceRecord(Base):
    __tablename__ = "personal_ops_maintenance_records"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    service_name: Mapped[str] = mapped_column(String(120))
    record_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="open")
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyBriefRecord(Base):
    __tablename__ = "personal_ops_daily_briefs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    brief_date: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    generated_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AutomationRunRecord(Base):
    __tablename__ = "personal_ops_automation_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    automation_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40))
    trigger: Mapped[str] = mapped_column(String(40))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    safe_summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class ScheduledAutomationRecord(Base):
    __tablename__ = "personal_ops_scheduled_automations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    automation_key: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    job_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="paused")
    schedule_kind: Mapped[str] = mapped_column(String(40), default="daily")
    schedule: Mapped[dict] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(80), default="America/New_York")
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_id: Mapped[str | None] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(String(80), default="jarvis-core")
    updated_by: Mapped[str] = mapped_column(String(80), default="jarvis-core")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrchestrationRunRecord(Base):
    __tablename__ = "jarvis_orchestration_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    status: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(80))
    user_request: Mapped[str] = mapped_column(Text)
    request_context: Mapped[dict] = mapped_column(JSON, default=dict)
    requested_by: Mapped[str] = mapped_column(String(80))
    priority: Mapped[int] = mapped_column(Integer, default=3)
    risk_level: Mapped[str] = mapped_column(String(40), default="L0")
    model_profile: Mapped[str | None] = mapped_column(String(120))
    result_summary: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrchestrationJobRecord(Base):
    __tablename__ = "jarvis_orchestration_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("jarvis_orchestration_runs.id"))
    parent_job_id: Mapped[str | None] = mapped_column(ForeignKey("jarvis_orchestration_jobs.id"))
    job_type: Mapped[str] = mapped_column(String(80))
    capability: Mapped[str] = mapped_column(String(120))
    worker_selector: Mapped[dict] = mapped_column(JSON, default=dict)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40))
    priority: Mapped[int] = mapped_column(Integer, default=3)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_state: Mapped[str] = mapped_column(String(40), default="not_required")
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(180), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobDependencyRecord(Base):
    __tablename__ = "jarvis_job_dependencies"

    job_id: Mapped[str] = mapped_column(ForeignKey("jarvis_orchestration_jobs.id"), primary_key=True)
    depends_on_job_id: Mapped[str] = mapped_column(ForeignKey("jarvis_orchestration_jobs.id"), primary_key=True)
    dependency_type: Mapped[str] = mapped_column(String(40), default="success_required")


class ArtifactRecord(Base):
    __tablename__ = "jarvis_artifacts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("jarvis_orchestration_runs.id"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jarvis_orchestration_jobs.id"))
    kind: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(240))
    path_or_uri: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(80))
    artifact_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkerRecord(Base):
    __tablename__ = "jarvis_workers"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160))
    worker_type: Mapped[str] = mapped_column(String(80))
    hostname: Mapped[str | None] = mapped_column(String(160))
    os: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(80), default="unknown")
    status: Mapped[str] = mapped_column(String(40), default="online")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    worker_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerCapabilityRecord(Base):
    __tablename__ = "jarvis_worker_capabilities"

    worker_id: Mapped[str] = mapped_column(ForeignKey("jarvis_workers.id"), primary_key=True)
    capability: Mapped[str] = mapped_column(String(120), primary_key=True)
    version: Mapped[str] = mapped_column(String(40), default="1")
    risk_ceiling: Mapped[str] = mapped_column(String(40), default="L1")
    capability_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class OrchestrationEventRecord(Base):
    __tablename__ = "jarvis_orchestration_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("jarvis_orchestration_runs.id"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jarvis_orchestration_jobs.id"))
    worker_id: Mapped[str | None] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

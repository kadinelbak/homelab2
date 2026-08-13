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

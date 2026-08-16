from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .contracts import ActionStatus, REGISTERED_TOOLS, RiskLevel, parse_calendar_request, redact, requires_approval
from .database import get_db
from .database import SessionLocal
from .models import (
    ApprovalRequestRecord,
    AuditEventRecord,
    AutomationRunRecord,
    Base,
    CalendarEventRecord,
    DailyBriefRecord,
    EvidenceRecord,
    ExecutionAttemptRecord,
    ExecutionResultRecord,
    MaintenanceRecord,
    ModelInvocationRecord,
    NotificationRecord,
    OutboxEventRecord,
    ProjectRecord,
    ProposedActionRecord,
    RequestRecord,
    StructuredIntentRecord,
    TaskRecord,
    ToolDefinitionRecord,
    VerificationResultRecord,
)
from .database import engine

app = FastAPI(title="Jarvis Core", version="0.1.0")
REQUESTS = Counter("jarvis_core_requests_total", "Jarvis Core HTTP requests", ["path"])
LATENCY = Histogram("jarvis_core_request_latency_seconds", "Jarvis Core HTTP latency", ["path"])
DEFAULT_DRIVE_EXCLUDE_NAMES = [
    "griproot",
    "grip",
    "assistive device",
    "hands team",
    "hipaa",
    "hippa",
    "ferpa",
    "prosthetic",
]
DEFAULT_DRIVE_EXCLUDE_FOLDER_IDS = {
    "1R84QIbshv7O0Q1r9kyWdhvJnMff7smkf",
    "1RKCqATXRk3IlACDIXsCWIv2KePPYX6kk",
    "1ZXUSe0CoSOKLnibscJoU673_Pbi4pMjO",
    "17F-uYbyZrg7XAjkBNjsS7FDLZOUvVUAh",
    "1hwo2BcF1Atb_zkm6o_G3sWsbw0V25GNs",
    "1mHihPp-2MigwCT7fqkBA5wZxGI11_LHI",
    "1frmx-7NKkAiGHSkTje_fQOBobaTTqjUX",
    "19qS3QEBNw2PLemBLiF87O6tAnO655vBH",
    "1oUwEp4WYdLAtjJiohfUfpCVubGxeQNnq",
    "131rnZ2BwVXIytzM-GNoOxPjYgLx9ubJK",
    "1CPVnzf_WPhSm2vf7DfC6e0qjab0AwpLZ",
    "1mH37OcqW9bnOKDuY8cfXaB_RsMdPtQSy",
    "1PXk-3hwJRc3l1_u-Qn4RKFDhzRnzx8js",
    "1aDzcpKuYOlpqSplZJZSUwU4DzsvqwVY8",
    "142EkKiFRRshOc30ImZlRydQpLpaDnxt8",
    "13hrQtaFOWfhIL3jxKXJ-kaAK0G3-NQNS",
    "1yAcl1FIE-HsbTHXScJzIYQycSmzc2QlC",
    "1ngKb3AYeMF9Lli-8dF44m_R7dnjCHAIL",
    "1clK_SJc2HOnbh5HbUX3bOzzJZDZC4qty",
    "1WOsBC8l2fM4uj1gokIBp6cIE2EGridhR",
    "1HeGMVuQl4P_Tm4ITTBt4PGOjQ6FQ_A0g",
    "1J96SPEE1DFUrcHAPMFy_b-V-UHGZlOrm",
    "1SOSLh7DEbMuKSMPn5m2LcpAWbsSu0NLG",
    "1jd9EsItjA_zjkCDkZ0Rw0TY7UNdB5jqN",
    "1fK2uqMkfOGVtlaLmtyjkkFb57UAaC6Zd",
    "15I6mnodZv1rw3E8PqPztUzEX8QgI1spP",
    "1niAEvE_aTRqn-jTxq3-lYbiyd0lmiqkL",
    "1tyGctJVqYIutYgp7LnxoqZgCxsoCz3_z",
    "14csP1HW8fZVMEVml6NQoG9e5NQEdltru",
    "1mBI96pwfvxKygUYDSbvwcbgHi4aZBl1C",
    "18B7Qyl7a9XNjkPZ5KeSw_yD7Xa6-BbPB",
    "1OxuROhEQS2nqgiyFhrbEhO7IQ01ifXNz",
    "1OxuROhEQS2nqgjyFhrbEhO7lQ01ifXNz",
    "1wGG4Z8OPpyfZkDC_kbcijkuOOVoDBEpf",
    "1xo5MU8Tk00apMBERsdw1zPR29wz86-dh",
    "1oA0rpz93htDJ0vC4j7TQhQGi989CcPvA",
    "1-Scr58zKYVlaxGMn6GN-zCm4jj7nuroC",
    "1QIU5Rnehy05nMzICuYowxmrC2WV1sdwV",
    "1AlGtNUOchkS90Xj-njcWnLKFmZdfzxv8",
    "10HgRs3i7x0dndZ2V2wBW188cVMesql_X",
}
AUTOMATION_RUNNER_STARTED = False


def default_drive_exclude_names():
    return list(DEFAULT_DRIVE_EXCLUDE_NAMES)


class RequestCreate(BaseModel):
    request: str
    source: str = "jarvis-core-api"
    idempotency_key: str | None = None


class ApprovalDecision(BaseModel):
    approved: bool
    decided_by: str = "local-user"


class ProjectCreate(BaseModel):
    name: str
    area: str | None = None
    goal: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    next_action: str | None = None
    notes: str | None = None


class TaskCreate(BaseModel):
    title: str
    project_id: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None
    estimated_minutes: int | None = None
    effort_level: str | None = None
    source: str | None = "manual"
    tags: list[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = None
    project_id: str | None = None
    status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    due_at: datetime | None = None
    estimated_minutes: int | None = None
    effort_level: str | None = None
    tags: list[str] | None = None


class UnifiedCapture(BaseModel):
    text: str
    idempotency_key: str | None = None


class EvidenceCreate(BaseModel):
    title: str
    evidence_type: str = "note"
    project_id: str | None = None
    uri: str | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)


class MaintenanceCreate(BaseModel):
    service_name: str
    record_type: str = "note"
    summary: str
    status: str = "open"
    details: dict = Field(default_factory=dict)
    next_check_at: datetime | None = None


class MaintenanceUpdate(BaseModel):
    status: str | None = None
    summary: str | None = None
    details: dict | None = None
    next_check_at: datetime | None = None
    resolved: bool = False


class CodexTaskCreate(BaseModel):
    request: str
    mode: str = Field(default="plan-only", pattern="^(inspect-only|plan-only|patch-only|test-only|execute)$")
    idempotency_key: str | None = None


class NotificationCreate(BaseModel):
    channel: str = Field(default="homepage", pattern="^(homepage|telegram|voice|audit)$")
    title: str
    body: str | None = None
    severity: str = Field(default="info", pattern="^(info|warning|critical)$")
    payload: dict = Field(default_factory=dict)


class NotificationDelivery(BaseModel):
    status: str = Field(default="delivered", pattern="^(pending|delivered|dismissed|failed)$")
    delivered_by: str = "jarvis"


class DailyBriefActionCreate(BaseModel):
    title: str
    action_type: str = Field(default="task", pattern="^(task|calendar_hold)$")
    priority: int = Field(default=3, ge=1, le=5)
    estimated_minutes: int | None = None
    when_text: str | None = None
    idempotency_key: str | None = None


class ModelGenerate(BaseModel):
    prompt: str
    profile: str = Field(default="fast", pattern="^(fast|deep|vision)$")
    model: str | None = None
    purpose: str = "general"
    system: str | None = None
    images: list[str] = Field(default_factory=list)
    max_tokens: int = Field(default=500, ge=1, le=4000)
    temperature: float = Field(default=0.2, ge=0, le=2)


class DriveInventoryRequest(BaseModel):
    query: str = "trashed = false"
    max_results: int = Field(default=1000, ge=1, le=10000)
    include_folder_ids: list[str] = Field(default_factory=list)
    include_paths: bool = False
    top_level_only: bool = False
    root_topics_only: bool = False
    my_drive_only: bool = True
    exclude_names: list[str] = Field(default_factory=default_drive_exclude_names)
    categories: list[str] = Field(
        default_factory=lambda: [
            "professional_education",
            "professional_work",
            "hobbies",
            "research",
            "personal_lifeadmin",
        ]
    )


class DriveChildrenRequest(BaseModel):
    folder_id: str | None = None
    max_results: int = Field(default=200, ge=1, le=1000)
    my_drive_only: bool = True
    exclude_names: list[str] = Field(default_factory=default_drive_exclude_names)


class DriveStagingCopyRequest(BaseModel):
    query: str = "trashed = false"
    max_results: int = Field(default=10, ge=1, le=100)
    file_ids: list[str] = Field(default_factory=list)
    include_folder_ids: list[str] = Field(default_factory=list)
    exclude_names: list[str] = Field(default_factory=default_drive_exclude_names)
    my_drive_only: bool = True
    category: str | None = None
    migration_action: str = Field(default="copy_to_homelab", pattern="^(copy_to_homelab|keep_in_google|archive|needs_review)$")
    idempotency_key: str | None = None


class DriveNextcloudImportRequest(BaseModel):
    manifest_paths: list[str] = Field(default_factory=list)
    max_results: int = Field(default=20, ge=1, le=100)
    idempotency_key: str | None = None


class DrivePaperlessImportRequest(BaseModel):
    manifest_paths: list[str] = Field(default_factory=list)
    max_results: int = Field(default=20, ge=1, le=100)
    idempotency_key: str | None = None


class GmailCleanupProposal(BaseModel):
    action_type: str = Field(default="label_classifications", pattern="^(label_classifications|archive_newsletters|mark_old_unread_read|star_needs_reply)$")
    message_ids: list[str] = Field(default_factory=list)
    max_results: int = Field(default=10, ge=1, le=50)
    idempotency_key: str | None = None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def authorize(authorization: str | None = Header(default=None)):
    if not settings.token:
        return settings.dev_auth_user
    expected = f"Bearer {settings.token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    return settings.dev_auth_user


@app.on_event("startup")
def startup():
    global AUTOMATION_RUNNER_STARTED
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        for tool in REGISTERED_TOOLS:
            existing = db.query(ToolDefinitionRecord).filter_by(name=tool.name).first()
            if not existing:
                db.add(
                    ToolDefinitionRecord(
                        id=new_id("tool"),
                        name=tool.name,
                        version=tool.version,
                        description=tool.description,
                        risk_level=tool.risk_level.value,
                        required_permissions=list(tool.required_permissions),
                    )
                )
        db.commit()
    finally:
        db.close()
    if settings.automation_runner_enabled and not AUTOMATION_RUNNER_STARTED:
        AUTOMATION_RUNNER_STARTED = True
        thread = threading.Thread(target=automation_runner_loop, name="jarvis-automation-runner", daemon=True)
        thread.start()


@app.middleware("http")
async def metrics_middleware(request, call_next):
    path = request.url.path
    with LATENCY.labels(path=path).time():
        response = await call_next(request)
    REQUESTS.labels(path=path).inc()
    return response


@app.get("/health")
@app.get("/api/v1/health")
def health():
    return {"ok": True, "service": "jarvis-core"}


@app.get("/api/v1/readiness")
def readiness(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"ok": True, "database": "ready"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/requests")
def create_request(payload: RequestCreate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    if payload.idempotency_key:
        existing = db.query(RequestRecord).filter_by(idempotency_key=payload.idempotency_key).first()
        if existing:
            return request_response(db, existing)

    request_id = new_id("req")
    correlation_id = new_id("corr")
    record = RequestRecord(
        id=request_id,
        user_id=actor,
        source=payload.source,
        raw_text=payload.request,
        status="received",
        idempotency_key=payload.idempotency_key,
        correlation_id=correlation_id,
    )
    db.add(record)
    db.flush()
    audit(db, "request.received", actor, correlation_id, request_id, {"request_id": request_id, "source": payload.source})

    calendar = parse_calendar_request(payload.request, settings.user_timezone)
    if calendar:
        intent = StructuredIntentRecord(
            id=new_id("intent"),
            request_id=request_id,
            intent_type="calendar.schedule",
            confidence=0.86,
            payload={
                "title": calendar.title,
                "starts_at": calendar.starts_at.isoformat(),
                "ends_at": calendar.ends_at.isoformat(),
                "duration_minutes": calendar.duration_minutes,
                "timezone": calendar.timezone,
                "calendar_target": calendar.calendar_target,
                "assumptions": list(calendar.assumptions),
            },
        )
        db.add(intent)
        action = ProposedActionRecord(
            id=new_id("act"),
            request_id=request_id,
            tool_name="calendar.schedule_google_event" if settings.calendar_provider == "google" else "calendar.schedule_simulated_event",
            tool_version="1.0",
            risk_level=RiskLevel.EXTERNAL_WRITE.value,
            status=ActionStatus.AWAITING_APPROVAL.value,
            arguments=intent.payload,
            preview={
                "summary": f"Create calendar event '{calendar.title}' for {calendar.duration_minutes} minutes.",
                "changes": [
                    "A new event will be written to Google Calendar."
                    if settings.calendar_provider == "google"
                    else "A new event will be written to the development calendar adapter."
                ],
                "assumptions": list(calendar.assumptions),
                "reversible": True,
                "provider": settings.calendar_provider,
            },
            requires_approval=requires_approval(RiskLevel.EXTERNAL_WRITE),
        )
        db.add(action)
        db.flush()
        db.add(
            ApprovalRequestRecord(
                id=new_id("appr"),
                proposed_action_id=action.id,
                status="pending",
                reason="Calendar writes are external actions and require explicit approval.",
            )
        )
        record.status = "awaiting_approval"
        audit(db, "intent.created", actor, correlation_id, intent.id, {"intent_type": intent.intent_type})
        audit(db, "action.proposed", actor, correlation_id, action.id, {"tool": action.tool_name, "risk_level": action.risk_level})
        audit(db, "approval.requested", actor, correlation_id, action.id, {"reason": "external_write"})
    elif is_coding_request(payload.request):
        mode = infer_codex_mode(payload.request)
        risk_level = RiskLevel.READ_ONLY if mode in {"inspect-only", "plan-only"} else RiskLevel.EXTERNAL_WRITE
        intent = StructuredIntentRecord(
            id=new_id("intent"),
            request_id=request_id,
            intent_type="codex.run_task",
            confidence=0.8,
            payload={"request": payload.request, "workspace": "jarvis-mounted-workspace", "mode": mode},
        )
        db.add(intent)
        action = ProposedActionRecord(
            id=new_id("act"),
            request_id=request_id,
            tool_name="codex.run_task",
            tool_version="1.0",
            risk_level=risk_level.value,
            status=ActionStatus.AWAITING_APPROVAL.value,
            arguments=intent.payload,
            preview={
                "summary": f"Run a Codex coding task in {mode} mode.",
                "changes": codex_mode_changes(mode),
                "assumptions": ["No git push, destructive shell command, or secret exposure is allowed."],
                "reversible": True,
                "provider": "codex-worker",
                "mode": mode,
            },
            requires_approval=True,
        )
        db.add(action)
        db.flush()
        db.add(ApprovalRequestRecord(id=new_id("appr"), proposed_action_id=action.id, status="pending", reason="Coding tasks can modify workspace files and require explicit approval."))
        record.status = "awaiting_approval"
        audit(db, "intent.created", actor, correlation_id, intent.id, {"intent_type": intent.intent_type})
        audit(db, "action.proposed", actor, correlation_id, action.id, {"tool": action.tool_name, "risk_level": action.risk_level})
        audit(db, "approval.requested", actor, correlation_id, action.id, {"reason": "codex_write"})
        notify_many(db, actor, ("homepage", "telegram", "voice"), "Approval needed", f"Codex {mode}: {payload.request[:140]}", "warning", {"action_id": action.id, "tool": action.tool_name})
    else:
        intent = StructuredIntentRecord(
            id=new_id("intent"),
            request_id=request_id,
            intent_type="clarification",
            confidence=1.0,
            payload={"raw_text": payload.request},
            requires_clarification=True,
            clarification_question="What should Jarvis do with this request?",
        )
        db.add(intent)
        record.status = "needs_clarification"
    db.commit()
    db.refresh(record)
    return request_response(db, record)


@app.get("/api/v1/requests/{request_id}")
def get_request(request_id: str, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    record = db.get(RequestRecord, request_id)
    if not record:
        raise HTTPException(status_code=404, detail={"error": "request_not_found"})
    return request_response(db, record)


@app.get("/api/v1/approvals")
def list_approvals(status: str | None = None, q: str | None = None, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    query = db.query(ApprovalRequestRecord)
    if status:
        query = query.filter(ApprovalRequestRecord.status == status)
    approvals = query.order_by(ApprovalRequestRecord.created_at.desc()).all()
    if q:
        needle = q.casefold()
        approvals = [item for item in approvals if needle in approval_search_text(db, item).casefold()]
    return {"approvals": [approval_response(db, item) for item in approvals]}


@app.post("/api/v1/approvals/decide-by-title")
def decide_approval_by_title(payload: ApprovalDecision, q: str, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    matches = [
        item
        for item in db.query(ApprovalRequestRecord).filter_by(status="pending").order_by(ApprovalRequestRecord.created_at.desc()).all()
        if q.casefold() in approval_search_text(db, item).casefold()
    ]
    if not matches:
        raise HTTPException(status_code=404, detail={"error": "approval_not_found"})
    if len(matches) > 1:
        return {"status": "ambiguous", "matches": [approval_response(db, item) for item in matches[:5]]}
    return decide_approval(matches[0].id, payload, db, actor)


@app.post("/api/v1/approvals/{approval_id}/decision")
def decide_approval(approval_id: str, payload: ApprovalDecision, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    approval = db.get(ApprovalRequestRecord, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail={"error": "approval_not_found"})
    if approval.status != "pending":
        return approval_response(db, approval)
    action = db.get(ProposedActionRecord, approval.proposed_action_id)
    approval.decided_by = payload.decided_by or actor
    approval.decided_at = now_utc()
    if not payload.approved:
        approval.status = "denied"
        action.status = ActionStatus.DENIED.value
        audit_for_action(db, "approval.denied", action, actor, {"approval_id": approval.id})
        db.commit()
        return approval_response(db, approval)

    approval.status = "approved"
    action.status = ActionStatus.APPROVED.value
    audit_for_action(db, "approval.granted", action, actor, {"approval_id": approval.id})
    execute_action(db, action, actor)
    db.commit()
    return approval_response(db, approval)


@app.get("/api/v1/executions")
def list_executions(tool_name: str | None = None, status: str | None = None, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    attempts = db.query(ExecutionAttemptRecord).order_by(ExecutionAttemptRecord.started_at.desc()).all()
    if status:
        attempts = [item for item in attempts if item.status == status]
    if tool_name:
        attempts = [item for item in attempts if action_tool_name(db, item.proposed_action_id) == tool_name]
    return {"executions": [execution_response(db, item) for item in attempts]}


@app.get("/api/v1/audit")
def list_audit(q: str | None = None, event_type: str | None = None, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    query = db.query(AuditEventRecord)
    if event_type:
        query = query.filter(AuditEventRecord.event_type == event_type)
    events = query.order_by(AuditEventRecord.created_at.desc()).limit(200).all()
    if q:
        needle = q.casefold()
        events = [item for item in events if needle in json.dumps(item.payload, default=str).casefold() or needle in item.event_type.casefold()]
    return {"events": [{"id": item.id, "event_type": item.event_type, "created_at": item.created_at, "payload": item.payload} for item in events]}


@app.get("/api/v1/tools")
def list_tools(db: Session = Depends(get_db), actor: str = Depends(authorize)):
    tools = db.query(ToolDefinitionRecord).order_by(ToolDefinitionRecord.name).all()
    return {"tools": [tool_response(item) for item in tools], "media_pipeline_url": settings.media_pipeline_url}


@app.get("/api/v1/media/automations/status")
def media_automations_status(actor: str = Depends(authorize)):
    checks = media_automation_checks()
    reachable = sum(1 for item in checks if item.get("ok"))
    preview = f"{reachable}/{len(checks)} media automations reachable"
    return {"ok": reachable == len(checks), "preview": preview, "checks": checks, "mode": "read_only"}


@app.post("/api/v1/drive/inventory")
def drive_inventory(payload: DriveInventoryRequest, actor: str = Depends(authorize)):
    files = collect_drive_files(
        payload.query,
        payload.max_results,
        payload.include_folder_ids,
        payload.exclude_names,
        include_paths=payload.include_paths,
        top_level_only=payload.top_level_only,
        root_topics_only=payload.root_topics_only,
        my_drive_only=payload.my_drive_only,
    )
    inventory = build_drive_inventory(files)
    return {"ok": True, **inventory, "mode": "metadata_only"}


@app.post("/api/v1/drive/migration-plan")
def drive_migration_plan(payload: DriveInventoryRequest, actor: str = Depends(authorize)):
    files = collect_drive_files(
        payload.query,
        payload.max_results,
        payload.include_folder_ids,
        payload.exclude_names,
        include_paths=payload.include_paths,
        top_level_only=payload.top_level_only,
        root_topics_only=payload.root_topics_only,
        my_drive_only=payload.my_drive_only,
    )
    inventory = build_drive_inventory(files)
    return {"ok": True, "inventory": inventory, "plan": build_drive_migration_plan(inventory), "mode": "metadata_only_no_downloads"}


@app.post("/api/v1/drive/folders")
def drive_folders(payload: DriveInventoryRequest, actor: str = Depends(authorize)):
    folders = drive_folder_metadata(payload.max_results, payload.exclude_names, my_drive_only=payload.my_drive_only)
    if payload.top_level_only:
        folders = top_level_drive_items(folders, folders)
    if payload.root_topics_only:
        folders = [folder for folder in folders if is_drive_root_topic(folder)]
    return {"ok": True, "folders": folders, "excluded_names": normalize_drive_exclude_names(payload.exclude_names), "mode": "metadata_only"}


@app.post("/api/v1/drive/children")
def drive_children(payload: DriveChildrenRequest, actor: str = Depends(authorize)):
    return collect_drive_children(
        payload.folder_id,
        payload.max_results,
        payload.exclude_names,
        my_drive_only=payload.my_drive_only,
    )


@app.post("/api/v1/drive/staging-copy/propose")
def propose_drive_staging_copy(payload: DriveStagingCopyRequest, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    if payload.idempotency_key:
        existing = db.query(RequestRecord).filter_by(idempotency_key=payload.idempotency_key).first()
        if existing:
            return request_response(db, existing)
    files = collect_drive_files(
        payload.query,
        payload.max_results,
        payload.include_folder_ids,
        payload.exclude_names,
        include_paths=True,
        my_drive_only=payload.my_drive_only,
    )
    inventory = build_drive_inventory(files)
    items = inventory.get("items") or []
    if payload.file_ids:
        wanted = set(payload.file_ids)
        items = [item for item in items if item.get("id") in wanted]
    if payload.category:
        items = [item for item in items if item.get("life_category") == payload.category]
    items = [item for item in items if item.get("migration_action") == payload.migration_action]
    items = items[: payload.max_results]
    if not items:
        raise HTTPException(status_code=400, detail={"error": "no_matching_drive_items", "hint": "Run the migration plan first and choose copy_to_homelab items."})

    request_id = new_id("req")
    correlation_id = new_id("corr")
    record = RequestRecord(
        id=request_id,
        user_id=actor,
        source="drive-migration",
        raw_text=f"Copy {len(items)} Google Drive item(s) to homelab staging.",
        status="awaiting_approval",
        idempotency_key=payload.idempotency_key,
        correlation_id=correlation_id,
    )
    db.add(record)
    db.flush()
    action = ProposedActionRecord(
        id=new_id("act"),
        request_id=request_id,
        tool_name="drive.copy_to_staging",
        tool_version="0.1",
        risk_level=RiskLevel.EXTERNAL_WRITE.value,
        status=ActionStatus.AWAITING_APPROVAL.value,
        arguments={"items": items, "mode": "copy_only_no_google_modifications"},
        preview={
            "summary": f"Copy {len(items)} Google Drive item(s) into homelab staging.",
            "changes": [
                "Files will be exported/downloaded from Google Drive.",
                "Copies will be written under the Google Tools worker staging data folder.",
                "Google Drive originals will not be moved, modified, archived, or deleted.",
            ],
            "sample_items": [{"name": item.get("name"), "category": item.get("life_category_label"), "home": item.get("recommended_home")} for item in items[:5]],
            "requires_scope": "https://www.googleapis.com/auth/drive.readonly",
            "reversible": True,
            "provider": "google-tools-worker",
        },
        requires_approval=True,
    )
    db.add(action)
    db.flush()
    db.add(ApprovalRequestRecord(id=new_id("appr"), proposed_action_id=action.id, status="pending", reason="Drive file copies write data to homelab staging and require explicit approval."))
    audit(db, "request.received", actor, correlation_id, request_id, {"request_id": request_id, "source": "drive-migration"})
    audit(db, "action.proposed", actor, correlation_id, action.id, {"tool": action.tool_name, "risk_level": action.risk_level, "item_count": len(items)})
    audit(db, "approval.requested", actor, correlation_id, action.id, {"reason": "drive_copy_to_staging"})
    notify_many(db, actor, ("homepage", "telegram", "voice"), "Approval needed", f"Drive staging copy: {len(items)} item(s)", "warning", {"action_id": action.id, "tool": action.tool_name})
    db.commit()
    db.refresh(record)
    return request_response(db, record)


@app.post("/api/v1/drive/staging-status")
def drive_staging_status(payload: DriveInventoryRequest, actor: str = Depends(authorize)):
    status = call_google_tools("/drive/staging-status", {"max_results": payload.max_results}, timeout=60)
    return {"ok": True, **status}


@app.get("/api/v1/drive/nextcloud-status")
def drive_nextcloud_status(actor: str = Depends(authorize)):
    status = call_google_tools("/drive/nextcloud-status", {}, timeout=60)
    return {"ok": True, **status}


@app.post("/api/v1/drive/destinations")
def drive_destinations(payload: DriveInventoryRequest, actor: str = Depends(authorize)):
    staging = call_google_tools("/drive/staging-status", {"max_results": payload.max_results}, timeout=60)
    services = drive_destination_services()
    staged_items = []
    for manifest in staging.get("manifests") or []:
        destination = manifest.get("destination") or "Needs Review"
        service_key = destination_service_key(destination)
        service = services.get(service_key) or services["needs_review"]
        staged_items.append(
            {
                "name": manifest.get("name"),
                "category": manifest.get("category"),
                "destination": destination,
                "service": service_key,
                "ready": service.get("ready"),
                "local_path": manifest.get("path"),
                "manifest_path": manifest.get("manifest_path"),
                "next_action": smart_destination_next_action(manifest, service),
                "reason": smart_destination_reason(manifest, service),
            }
        )
    return {
        "ok": True,
        "mode": "read_only_destination_planning",
        "summary": f"{len(staged_items)} staged item(s), {sum(1 for item in staged_items if item['ready'])} ready destination route(s)",
        "services": services,
        "staged_items": staged_items,
        "pathway": [
            "Confirm destination service is ready.",
            "Review staged file and manifest.",
            "Import through a destination-specific adapter only after approval.",
            "Verify destination link/counts.",
            "Record Jarvis Core index and audit trail.",
            "Consider Google archive/delete later as a separate destructive approval.",
        ],
    }


@app.post("/api/v1/drive/nextcloud-import/propose")
def propose_drive_nextcloud_import(payload: DriveNextcloudImportRequest, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    if payload.idempotency_key:
        existing = db.query(RequestRecord).filter_by(idempotency_key=payload.idempotency_key).first()
        if existing:
            return request_response(db, existing)

    staging = call_google_tools("/drive/staging-status", {"max_results": payload.max_results}, timeout=60)
    manifests = staging.get("manifests") or []
    if payload.manifest_paths:
        wanted = set(payload.manifest_paths)
        manifests = [item for item in manifests if item.get("manifest_path") in wanted]
    manifests = [item for item in manifests if item.get("file_exists") is True][: payload.max_results]
    if not manifests:
        raise HTTPException(status_code=400, detail={"error": "no_nextcloud_ready_staged_items", "hint": "Stage Drive files first, then review Smart Destinations."})

    request_id = new_id("req")
    correlation_id = new_id("corr")
    record = RequestRecord(
        id=request_id,
        user_id=actor,
        source="drive-migration",
        raw_text=f"Copy {len(manifests)} staged Google Drive item(s) to the Nextcloud import queue.",
        status="awaiting_approval",
        idempotency_key=payload.idempotency_key,
        correlation_id=correlation_id,
    )
    db.add(record)
    db.flush()
    action = ProposedActionRecord(
        id=new_id("act"),
        request_id=request_id,
        tool_name="drive.import_to_nextcloud",
        tool_version="0.1",
        risk_level=RiskLevel.EXTERNAL_WRITE.value,
        status=ActionStatus.AWAITING_APPROVAL.value,
        arguments={
            "manifest_paths": [item.get("manifest_path") for item in manifests],
            "max_results": payload.max_results,
            "mode": "copy_only_no_google_modifications",
        },
        preview={
            "summary": f"Copy {len(manifests)} staged Drive item(s) into the Nextcloud import queue.",
            "changes": [
                "Reads files already copied into homelab Drive staging.",
                "Writes duplicate copies into the Nextcloud import queue.",
                "Google Drive originals and staging copies are not moved, modified, archived, or deleted.",
            ],
            "sample_items": [{"name": item.get("name"), "category": item.get("category"), "path": item.get("staged_relative_path")} for item in manifests[:5]],
            "reversible": True,
            "provider": "google-tools-worker",
        },
        requires_approval=True,
    )
    db.add(action)
    db.flush()
    db.add(ApprovalRequestRecord(id=new_id("appr"), proposed_action_id=action.id, status="pending", reason="Nextcloud imports write data to local storage and require explicit approval."))
    audit(db, "request.received", actor, correlation_id, request_id, {"request_id": request_id, "source": "drive-migration"})
    audit(db, "action.proposed", actor, correlation_id, action.id, {"tool": action.tool_name, "risk_level": action.risk_level, "item_count": len(manifests)})
    audit(db, "approval.requested", actor, correlation_id, action.id, {"reason": "drive_import_to_nextcloud"})
    notify_many(db, actor, ("homepage", "telegram", "voice"), "Approval needed", f"Nextcloud import: {len(manifests)} staged Drive item(s)", "warning", {"action_id": action.id, "tool": action.tool_name})
    db.commit()
    db.refresh(record)
    return request_response(db, record)


@app.post("/api/v1/drive/paperless-import/propose")
def propose_drive_paperless_import(payload: DrivePaperlessImportRequest, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    if payload.idempotency_key:
        existing = db.query(RequestRecord).filter_by(idempotency_key=payload.idempotency_key).first()
        if existing:
            return request_response(db, existing)

    staging = call_google_tools("/drive/staging-status", {"max_results": payload.max_results}, timeout=60)
    manifests = staging.get("manifests") or []
    if payload.manifest_paths:
        wanted = set(payload.manifest_paths)
        manifests = [item for item in manifests if item.get("manifest_path") in wanted]
    else:
        manifests = [item for item in manifests if destination_service_key(item.get("destination") or "") == "paperless"]
    manifests = [item for item in manifests if item.get("file_exists") is True][: payload.max_results]
    if not manifests:
        raise HTTPException(status_code=400, detail={"error": "no_paperless_ready_staged_items", "hint": "Stage Drive documents first, then review Smart Destinations."})

    request_id = new_id("req")
    correlation_id = new_id("corr")
    record = RequestRecord(
        id=request_id,
        user_id=actor,
        source="drive-migration",
        raw_text=f"Queue {len(manifests)} staged Google Drive document(s) for Paperless.",
        status="awaiting_approval",
        idempotency_key=payload.idempotency_key,
        correlation_id=correlation_id,
    )
    db.add(record)
    db.flush()
    action = ProposedActionRecord(
        id=new_id("act"),
        request_id=request_id,
        tool_name="drive.import_to_paperless",
        tool_version="0.1",
        risk_level=RiskLevel.EXTERNAL_WRITE.value,
        status=ActionStatus.AWAITING_APPROVAL.value,
        arguments={"manifest_paths": [item.get("manifest_path") for item in manifests], "max_results": payload.max_results, "mode": "copy_only_no_google_modifications"},
        preview={
            "summary": f"Queue {len(manifests)} staged Drive document(s) for Paperless import.",
            "changes": [
                "Reads files already copied into homelab Drive staging.",
                "Writes duplicate copies into the Paperless consume folder.",
                "Google Drive originals and staging copies are not moved, modified, archived, or deleted.",
            ],
            "suggested_tags": ["education", "medical", "finance", "lifeadmin", "drive-migration"],
            "sample_items": [{"name": item.get("name"), "category": item.get("category"), "path": item.get("staged_relative_path")} for item in manifests[:5]],
            "reversible": True,
            "provider": "google-tools-worker",
        },
        requires_approval=True,
    )
    db.add(action)
    db.flush()
    db.add(ApprovalRequestRecord(id=new_id("appr"), proposed_action_id=action.id, status="pending", reason="Paperless imports write documents into local document storage and require explicit approval."))
    audit(db, "request.received", actor, correlation_id, request_id, {"request_id": request_id, "source": "drive-migration"})
    audit(db, "action.proposed", actor, correlation_id, action.id, {"tool": action.tool_name, "risk_level": action.risk_level, "item_count": len(manifests)})
    audit(db, "approval.requested", actor, correlation_id, action.id, {"reason": "drive_import_to_paperless"})
    notify_many(db, actor, ("homepage", "telegram", "voice"), "Approval needed", f"Paperless import: {len(manifests)} staged Drive document(s)", "warning", {"action_id": action.id, "tool": action.tool_name})
    db.commit()
    db.refresh(record)
    return request_response(db, record)


@app.get("/api/v1/gmail/cleanup-summary")
def gmail_cleanup_summary(max_results: int = 50, actor: str = Depends(authorize)):
    result = call_google_tools("/gmail/cleanup-summary", {"max_results": max_results}, timeout=180)
    return {"ok": True, **result}


@app.post("/api/v1/gmail/cleanup/propose")
def propose_gmail_cleanup(payload: GmailCleanupProposal, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    if payload.idempotency_key:
        existing = db.query(RequestRecord).filter_by(idempotency_key=payload.idempotency_key).first()
        if existing:
            return request_response(db, existing)
    summary = call_google_tools("/gmail/cleanup-summary", {"max_results": max(payload.max_results, 20)}, timeout=180)
    source_key = "likely_newsletters" if payload.action_type == "archive_newsletters" else "old_unread" if payload.action_type == "mark_old_unread_read" else "needs_reply"
    candidates = summary.get(source_key) or []
    if payload.action_type == "label_classifications":
        batches = gmail_classification_batches(summary, payload.max_results)
        message_ids = [mid for batch in batches for mid in batch.get("message_ids", [])]
    else:
        message_ids = payload.message_ids or [item.get("id") for item in candidates[: payload.max_results] if item.get("id")]
        batches = []
    if not message_ids:
        raise HTTPException(status_code=400, detail={"error": "no_matching_gmail_messages", "hint": "Run Gmail cleanup summary first."})
    if payload.action_type == "label_classifications":
        contract = {"operation": "label_batches", "batches": batches}
        title = "Classify Gmail messages with Jarvis labels"
    elif payload.action_type == "archive_newsletters":
        contract = {"operation": "label_messages", "message_ids": message_ids, "label_names": ["Jarvis/Newsletters"], "remove_label_ids": ["INBOX"]}
        title = "Archive and label likely newsletter messages"
    elif payload.action_type == "mark_old_unread_read":
        contract = {"operation": "label_messages", "message_ids": message_ids, "label_names": ["Jarvis/Needs Review"], "remove_label_ids": ["UNREAD"]}
        title = "Mark old unread messages as read and needs-review"
    else:
        contract = {"operation": "label_messages", "message_ids": message_ids, "label_ids": ["STARRED"], "label_names": ["Jarvis/Needs Reply"], "remove_label_ids": []}
        title = "Star and label likely needs-reply messages"

    request_id = new_id("req")
    correlation_id = new_id("corr")
    record = RequestRecord(
        id=request_id,
        user_id=actor,
        source="gmail-cleanup",
        raw_text=f"{title}: {len(message_ids)} Gmail message(s).",
        status="awaiting_approval",
        idempotency_key=payload.idempotency_key,
        correlation_id=correlation_id,
    )
    db.add(record)
    db.flush()
    action = ProposedActionRecord(
        id=new_id("act"),
        request_id=request_id,
        tool_name="gmail.apply_cleanup",
        tool_version="0.1",
        risk_level=RiskLevel.EXTERNAL_WRITE.value,
        status=ActionStatus.AWAITING_APPROVAL.value,
        arguments={
            "contract": contract,
            "action_type": payload.action_type,
        },
        preview={
            "summary": f"{title} for {len(message_ids)} Gmail message(s).",
            "changes": ["Applies Gmail label changes only after approval.", "No messages are deleted."],
            "labels": sorted({label for batch in batches for label in batch.get("label_names", [])}) if batches else contract.get("label_names") or contract.get("label_ids") or [],
            "sample_messages": [{"from": item.get("from"), "subject": item.get("subject"), "date": item.get("date")} for item in candidates[:5]],
            "reversible": True,
            "provider": "google-tools-worker",
        },
        requires_approval=True,
    )
    db.add(action)
    db.flush()
    db.add(ApprovalRequestRecord(id=new_id("appr"), proposed_action_id=action.id, status="pending", reason="Gmail cleanup modifies mailbox labels and requires explicit approval."))
    audit(db, "request.received", actor, correlation_id, request_id, {"request_id": request_id, "source": "gmail-cleanup"})
    audit(db, "action.proposed", actor, correlation_id, action.id, {"tool": action.tool_name, "risk_level": action.risk_level, "message_count": len(message_ids)})
    audit(db, "approval.requested", actor, correlation_id, action.id, {"reason": "gmail_cleanup"})
    notify_many(db, actor, ("homepage", "telegram", "voice"), "Approval needed", f"Gmail cleanup: {len(message_ids)} message(s)", "warning", {"action_id": action.id, "tool": action.tool_name})
    db.commit()
    db.refresh(record)
    return request_response(db, record)


@app.get("/api/v1/homelab/diagnostics")
def homelab_diagnostics(db: Session = Depends(get_db), actor: str = Depends(authorize)):
    public_base = settings.homelab_public_base_url.rstrip("/")
    public_host = urllib.parse.urlparse(public_base).netloc or "100.79.132.39"
    http_checks = [
        ("jarvis-core", "http://127.0.0.1:8097/health"),
        ("google-tools-worker", settings.google_tools_url.rstrip("/") + "/health"),
        ("codex-worker", settings.codex_worker_url.rstrip("/") + "/health"),
        ("open-webui", "http://open-webui:8080/health"),
        ("whisper-worker", "http://whisper-worker:8099/health"),
        ("tts-worker", "http://tts-worker:8101/health"),
        ("homepage", "http://homepage:3000/"),
        ("pihole", settings.pihole_url),
        ("paperless", "http://paperless:8000"),
        ("nextcloud", "http://nextcloud/status.php", {"Host": public_host}),
    ]
    optional_checks = [
        {**http_health_check("ollama", "http://ollama:11434/api/tags"), "optional": True, "summary": "Optional local LLM runtime; Jarvis uses API/Navigator models by default."},
    ]
    checks = [database_health_check(db), redis_health_check()]
    checks.extend(http_health_check(*item) for item in http_checks)
    checks.extend(optional_checks)
    checks.extend(media_automation_checks())
    checks.extend(storage_health_checks())
    return {"ok": all(item.get("ok") or item.get("optional") for item in checks), "checks": checks, "mode": "read_only"}


@app.post("/api/v1/codex/tasks")
def create_codex_task(payload: CodexTaskCreate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    text = payload.request
    if payload.mode not in text.lower():
        text = f"Codex {payload.mode}: {text}"
    return create_request(RequestCreate(request=text, source="codex-task-api", idempotency_key=payload.idempotency_key), db, actor)


@app.get("/api/v1/codex/tasks")
def list_codex_tasks(status: str | None = None, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    actions = db.query(ProposedActionRecord).filter_by(tool_name="codex.run_task").order_by(ProposedActionRecord.created_at.desc()).all()
    if status:
        actions = [item for item in actions if item.status == status]
    return {"codex_tasks": [codex_task_response(db, item) for item in actions]}


@app.get("/api/v1/notifications")
def list_notifications(channel: str | None = None, status: str | None = None, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    query = db.query(NotificationRecord).order_by(NotificationRecord.created_at.desc())
    if channel:
        query = query.filter(NotificationRecord.channel == channel)
    if status:
        query = query.filter(NotificationRecord.status == status)
    return {"notifications": [notification_response(item) for item in query.limit(100).all()]}


@app.post("/api/v1/notifications")
def create_notification(payload: NotificationCreate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    record = notify(db, actor, payload.channel, payload.title, payload.body or "", payload.severity, payload.payload)
    db.commit()
    return notification_response(record)


@app.post("/api/v1/notifications/{notification_id}/delivery")
def update_notification_delivery(notification_id: str, payload: NotificationDelivery, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    record = db.get(NotificationRecord, notification_id)
    if not record:
        raise HTTPException(status_code=404, detail={"error": "notification_not_found"})
    record.status = payload.status
    db.add(OutboxEventRecord(id=new_id("outbox"), event_type=f"notification.{record.channel}.{payload.status}", payload={"notification_id": record.id, "delivered_by": payload.delivered_by}))
    audit(db, f"notification.{payload.status}", actor, new_id("corr"), record.id, {"channel": record.channel, "delivered_by": payload.delivered_by})
    db.commit()
    return notification_response(record)


@app.get("/api/v1/notifications/summary")
def notification_summary(channel: str = "homepage", limit: int = 5, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    query = db.query(NotificationRecord).filter(NotificationRecord.channel == channel).order_by(NotificationRecord.created_at.desc()).limit(max(1, min(limit, 20)))
    rows = query.all()
    if not rows:
        return {"preview": "No Jarvis notifications", "count": 0, "items": []}
    items = [notification_response(item) for item in rows]
    first = items[0]
    title = (first.get("payload") or {}).get("title") or first["id"]
    return {"preview": f"{len(items)} Jarvis notifications: {title}", "count": len(items), "items": items}


@app.get("/api/v1/models/health")
def model_health(actor: str = Depends(authorize)):
    return {
        "profiles": {
            "fast": model_profile_status("fast"),
            "deep": model_profile_status("deep"),
            "vision": model_profile_status("vision"),
        }
    }


@app.post("/api/v1/models/generate")
def generate_model_text(payload: ModelGenerate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    profile = configured_model_profile(payload.profile)
    if payload.model:
        profile = dict(profile)
        profile["model"] = payload.model.strip()
    try:
        result = call_openai_compatible_model(
            profile=profile,
            prompt=payload.prompt,
            system=payload.system,
            images=payload.images,
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
        )
        status = "completed"
        error = None
    except Exception as exc:
        result = {"content": ""}
        status = "failed"
        error = str(exc)[:500]

    invocation = ModelInvocationRecord(
        id=new_id("model"),
        request_id=None,
        provider=profile["provider"],
        model=profile["model"],
        purpose=payload.purpose[:80],
        invocation_metadata={
            "profile": payload.profile,
            "status": status,
            "prompt_chars": len(payload.prompt),
            "image_count": len(payload.images),
            "response_chars": len(result.get("content") or ""),
            "error": error,
        },
    )
    db.add(invocation)
    audit(db, "model.invoked", actor, new_id("corr"), invocation.id, invocation.invocation_metadata)
    db.commit()

    if status != "completed":
        raise HTTPException(status_code=502, detail={"error": "model_invocation_failed", "message": error})
    return {
        "id": invocation.id,
        "profile": payload.profile,
        "provider": profile["provider"],
        "model": profile["model"],
        "content": result["content"],
    }


@app.post("/api/v1/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    project = ProjectRecord(id=new_id("proj"), name=payload.name, area=payload.area, goal=payload.goal, priority=payload.priority, next_action=payload.next_action, notes=payload.notes, status="active")
    db.add(project)
    db.commit()
    return project_response(project)


@app.get("/api/v1/projects")
def list_projects(db: Session = Depends(get_db), actor: str = Depends(authorize)):
    projects = db.query(ProjectRecord).filter(ProjectRecord.archived_at.is_(None)).order_by(ProjectRecord.created_at.desc()).all()
    return {"projects": [project_response(item) for item in projects]}


@app.get("/api/v1/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    project = db.get(ProjectRecord, project_id)
    if not project or project.archived_at:
        raise HTTPException(status_code=404, detail={"error": "project_not_found"})
    tasks = db.query(TaskRecord).filter(TaskRecord.project_id == project.id, TaskRecord.archived_at.is_(None)).all()
    evidence = db.query(EvidenceRecord).filter(EvidenceRecord.project_id == project.id, EvidenceRecord.archived_at.is_(None)).all()
    return {"project": project_response(project), "tasks": [task_response(item) for item in tasks], "evidence": [evidence_response(item) for item in evidence]}


@app.post("/api/v1/tasks")
def create_task(payload: TaskCreate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    task = TaskRecord(id=new_id("task"), title=payload.title, project_id=payload.project_id, priority=payload.priority, due_at=payload.due_at, estimated_minutes=payload.estimated_minutes, effort_level=payload.effort_level, source=payload.source, tags=payload.tags, status="open")
    db.add(task)
    db.commit()
    return task_response(task)


@app.get("/api/v1/tasks")
def list_tasks(db: Session = Depends(get_db), actor: str = Depends(authorize)):
    tasks = db.query(TaskRecord).filter(TaskRecord.archived_at.is_(None)).order_by(TaskRecord.created_at.desc()).all()
    return {"tasks": [task_response(item) for item in tasks]}


@app.patch("/api/v1/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    task = db.get(TaskRecord, task_id)
    if not task or task.archived_at:
        raise HTTPException(status_code=404, detail={"error": "task_not_found"})
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "status" and value == "completed" and task.completed_at is None:
            task.completed_at = now_utc()
        if key == "status" and value != "completed":
            task.completed_at = None
        setattr(task, key, value)
    task.updated_at = now_utc()
    db.commit()
    return task_response(task)


@app.post("/api/v1/tasks/{task_id}/complete")
def complete_task(task_id: str, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    task = db.get(TaskRecord, task_id)
    if not task or task.archived_at:
        raise HTTPException(status_code=404, detail={"error": "task_not_found"})
    task.status = "completed"
    task.completed_at = now_utc()
    task.updated_at = now_utc()
    db.commit()
    return task_response(task)


@app.post("/api/v1/evidence")
def create_evidence(payload: EvidenceCreate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    if payload.project_id and not db.get(ProjectRecord, payload.project_id):
        raise HTTPException(status_code=404, detail={"error": "project_not_found"})
    evidence = EvidenceRecord(id=new_id("evid"), title=payload.title, evidence_type=payload.evidence_type, project_id=payload.project_id, uri=payload.uri, summary=payload.summary, tags=payload.tags)
    db.add(evidence)
    audit(db, "evidence.created", actor, new_id("corr"), evidence.id, {"title": payload.title, "project_id": payload.project_id})
    db.commit()
    return evidence_response(evidence)


@app.get("/api/v1/evidence")
def list_evidence(project_id: str | None = None, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    query = db.query(EvidenceRecord).filter(EvidenceRecord.archived_at.is_(None))
    if project_id:
        query = query.filter(EvidenceRecord.project_id == project_id)
    evidence = query.order_by(EvidenceRecord.captured_at.desc()).all()
    return {"evidence": [evidence_response(item) for item in evidence]}


@app.post("/api/v1/evidence/packet")
def build_evidence_packet(project_id: str | None = None, title: str | None = None, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    project = db.get(ProjectRecord, project_id) if project_id else None
    tasks_query = db.query(TaskRecord).filter(TaskRecord.archived_at.is_(None))
    evidence_query = db.query(EvidenceRecord).filter(EvidenceRecord.archived_at.is_(None))
    if project_id:
        tasks_query = tasks_query.filter(TaskRecord.project_id == project_id)
        evidence_query = evidence_query.filter(EvidenceRecord.project_id == project_id)
    tasks = tasks_query.order_by(TaskRecord.updated_at.desc()).limit(20).all()
    evidence = evidence_query.order_by(EvidenceRecord.captured_at.desc()).limit(20).all()
    maintenance = db.query(MaintenanceRecord).order_by(MaintenanceRecord.updated_at.desc()).limit(10).all()
    calendar_events = db.query(CalendarEventRecord).order_by(CalendarEventRecord.starts_at.desc()).limit(20).all()
    commits = collect_git_commits()
    documents = collect_google_document_references()
    packet = {
        "title": title or (f"Evidence packet: {project.name}" if project else "Jarvis evidence packet"),
        "project": project_response(project) if project else None,
        "tasks": [task_response(item) for item in tasks],
        "evidence": [evidence_response(item) for item in evidence],
        "maintenance": [maintenance_response(item) for item in maintenance],
        "calendar_events": [calendar_event_response(item) for item in calendar_events],
        "commits": commits,
        "documents": documents,
        "generated_at": now_utc().isoformat(),
        "summary": render_evidence_packet_summary(project, tasks, evidence, maintenance, calendar_events, commits, documents),
    }
    record = EvidenceRecord(
        id=new_id("evid"),
        project_id=project_id,
        title=packet["title"][:240],
        evidence_type="packet",
        uri=None,
        summary=packet["summary"],
        tags=["packet", "jarvis-built"],
    )
    db.add(record)
    audit(db, "evidence.packet_built", actor, new_id("corr"), record.id, {"project_id": project_id, "task_count": len(tasks), "evidence_count": len(evidence)})
    db.commit()
    return {"packet": packet, "evidence_record": evidence_response(record)}


@app.post("/api/v1/maintenance")
def create_maintenance_record(payload: MaintenanceCreate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    record = MaintenanceRecord(id=new_id("maint"), service_name=payload.service_name, record_type=payload.record_type, status=payload.status, summary=payload.summary, details=payload.details, next_check_at=payload.next_check_at)
    db.add(record)
    audit(db, "maintenance.created", actor, new_id("corr"), record.id, {"service_name": payload.service_name, "record_type": payload.record_type})
    db.commit()
    return maintenance_response(record)


@app.get("/api/v1/maintenance")
def list_maintenance_records(db: Session = Depends(get_db), actor: str = Depends(authorize)):
    records = db.query(MaintenanceRecord).order_by(MaintenanceRecord.created_at.desc()).all()
    return {"maintenance": [maintenance_response(item) for item in records]}


@app.patch("/api/v1/maintenance/{record_id}")
def update_maintenance_record(record_id: str, payload: MaintenanceUpdate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    record = db.get(MaintenanceRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail={"error": "maintenance_record_not_found"})
    updates = payload.model_dump(exclude_unset=True)
    resolved = updates.pop("resolved", False)
    for key, value in updates.items():
        setattr(record, key, value)
    if resolved:
        record.status = "resolved"
        record.resolved_at = now_utc()
    elif updates.get("status") and updates.get("status") != "resolved":
        record.resolved_at = None
    record.updated_at = now_utc()
    db.commit()
    return maintenance_response(record)


@app.post("/api/v1/capture")
def unified_capture(payload: UnifiedCapture, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    text_lower = payload.text.lower()
    if "schedule" in text_lower or "calendar" in text_lower:
        return create_request(RequestCreate(request=payload.text, source="unified-capture", idempotency_key=payload.idempotency_key), db, actor)
    if any(word in text_lower for word in ("evidence:", "proof:", "portfolio:")):
        title = payload.text.split(":", 1)[-1].strip() or payload.text
        evidence = EvidenceRecord(id=new_id("evid"), title=title[:240], evidence_type="capture", summary=payload.text, tags=["capture"])
        db.add(evidence)
        db.commit()
        return {"type": "evidence", "evidence": evidence_response(evidence), "confidence": 0.74}
    if any(word in text_lower for word in ("homelab", "maintenance", "service health", "outage")):
        record = MaintenanceRecord(id=new_id("maint"), service_name=infer_service_name(payload.text), record_type="capture", status="open", summary=payload.text, details={"source": "unified-capture"})
        db.add(record)
        db.commit()
        return {"type": "maintenance", "maintenance": maintenance_response(record), "confidence": 0.7}
    task = TaskRecord(id=new_id("task"), title=payload.text, status="open", priority=3, source="unified-capture", tags=[])
    db.add(task)
    db.commit()
    return {"type": "task", "task": task_response(task), "confidence": 0.72}


@app.get("/api/v1/daily-brief")
def daily_brief(kind: str = "morning", save: bool = False, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    if kind not in {"morning", "evening"}:
        raise HTTPException(status_code=400, detail={"error": "brief_kind_invalid"})
    tasks = db.query(TaskRecord).filter(TaskRecord.archived_at.is_(None), TaskRecord.status != "completed").all()
    approvals = db.query(ApprovalRequestRecord).filter_by(status="pending").all()
    evidence = (
        db.query(EvidenceRecord)
        .filter(EvidenceRecord.archived_at.is_(None), EvidenceRecord.evidence_type != "packet")
        .order_by(EvidenceRecord.captured_at.desc())
        .limit(5)
        .all()
    )
    maintenance = db.query(MaintenanceRecord).filter(MaintenanceRecord.status != "resolved").order_by(MaintenanceRecord.created_at.desc()).limit(5).all()
    google_brief = call_google_briefing(kind)
    ranked = sorted(tasks, key=task_score, reverse=True)
    payload = {
        "kind": kind,
        "generated_at": now_utc().isoformat(),
        "google": google_brief,
        "overdue_tasks": [task_response(item) for item in tasks if item.due_at and item.due_at < now_utc()],
        "tasks_due_soon": [task_response(item) for item in ranked[:5]],
        "recommended_actions": [item.title for item in ranked[:3]],
        "pending_approvals": [approval_response(db, item) for item in approvals],
        "recent_evidence": [evidence_response(item) for item in evidence],
        "open_maintenance": [maintenance_response(item) for item in maintenance],
        "ranking_formula": "score = priority_weight + due_date_weight + duration_fit + staleness_placeholder",
    }
    payload["text"] = render_daily_brief_text(payload)
    if save:
        local_date = datetime.now(ZoneInfo(settings.user_timezone)).date().isoformat()
        brief = DailyBriefRecord(id=new_id("brief"), brief_date=local_date, kind=kind, payload=json_safe(payload), generated_by=actor)
        db.add(brief)
        notify_many(db, actor, ("homepage", "telegram", "voice"), f"{kind.title()} brief ready", payload["text"][:500], "info", {"brief_id": brief.id, "kind": kind})
        db.commit()
        payload["saved_brief_id"] = brief.id
    return payload


@app.get("/api/v1/automations")
def list_automations(db: Session = Depends(get_db), actor: str = Depends(authorize)):
    def latest_run(key: str):
        return (
            db.query(AutomationRunRecord)
            .filter(AutomationRunRecord.automation_key == key)
            .order_by(AutomationRunRecord.started_at.desc())
            .first()
        )

    def latest_brief(kind: str):
        record = (
            db.query(DailyBriefRecord)
            .filter(DailyBriefRecord.kind == kind)
            .order_by(DailyBriefRecord.created_at.desc())
            .first()
        )
        return record.created_at.isoformat() if record and record.created_at else None

    def next_local_time(hour: int, minute: int = 0):
        local_now = datetime.now(ZoneInfo(settings.user_timezone))
        target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= local_now:
            target += timedelta(days=1)
        return target.isoformat()

    def next_weekday_time(weekday: int, hour: int, minute: int = 0):
        local_now = datetime.now(ZoneInfo(settings.user_timezone))
        target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (weekday - target.weekday()) % 7
        if days_ahead:
            target += timedelta(days=days_ahead)
        if target <= local_now:
            target += timedelta(days=7)
        return target.isoformat()

    pending_notifications = db.query(NotificationRecord).filter(NotificationRecord.status == "pending").count()
    pending_approvals = db.query(ApprovalRequestRecord).filter(ApprovalRequestRecord.status == "pending").count()
    open_maintenance = db.query(MaintenanceRecord).filter(MaintenanceRecord.status != "resolved").count()
    recent_drive_copy = (
        db.query(ExecutionAttemptRecord)
        .join(ProposedActionRecord, ProposedActionRecord.id == ExecutionAttemptRecord.proposed_action_id)
        .filter(ProposedActionRecord.tool_name.in_(("drive.copy_to_staging", "drive.import_to_nextcloud", "drive.import_to_paperless")))
        .order_by(ExecutionAttemptRecord.started_at.desc())
        .first()
    )
    recent_gmail_cleanup = (
        db.query(ExecutionAttemptRecord)
        .join(ProposedActionRecord, ProposedActionRecord.id == ExecutionAttemptRecord.proposed_action_id)
        .filter(ProposedActionRecord.tool_name == "gmail.apply_cleanup")
        .order_by(ExecutionAttemptRecord.started_at.desc())
        .first()
    )
    latest_diag = (
        db.query(AuditEventRecord)
        .filter(AuditEventRecord.event_type.in_(("homelab.diagnostics", "maintenance.created", "maintenance.updated")))
        .order_by(AuditEventRecord.created_at.desc())
        .first()
    )

    automations = [
        {
            "key": "daily_brief_morning",
            "name": "Morning daily brief",
            "category": "briefing",
            "status": "available",
            "mode": "scheduled_or_on_demand",
            "schedule": f"07:30 daily, {settings.user_timezone}",
            "last_run": (latest_run("daily_brief_morning").started_at.isoformat() if latest_run("daily_brief_morning") else latest_brief("morning")),
            "next_run": next_local_time(7, 30),
            "source": "telegram-bridge / jarvis-core",
            "channels": ["Homepage", "Telegram", "Voice"],
            "summary": "Scheduled by Telegram bridge, saved by Jarvis Core, then delivered through Core notifications.",
            "last_status": latest_run("daily_brief_morning").status if latest_run("daily_brief_morning") else None,
            "last_output": latest_run("daily_brief_morning").safe_summary if latest_run("daily_brief_morning") else None,
        },
        {
            "key": "daily_brief_evening",
            "name": "Evening daily brief",
            "category": "briefing",
            "status": "available",
            "mode": "scheduled_or_on_demand",
            "schedule": f"20:30 daily, {settings.user_timezone}",
            "last_run": (latest_run("daily_brief_evening").started_at.isoformat() if latest_run("daily_brief_evening") else latest_brief("evening")),
            "next_run": next_local_time(20, 30),
            "source": "telegram-bridge / jarvis-core",
            "channels": ["Homepage", "Telegram", "Voice"],
            "summary": "Scheduled by Telegram bridge, saved by Jarvis Core, then delivered through Core notifications.",
            "last_status": latest_run("daily_brief_evening").status if latest_run("daily_brief_evening") else None,
            "last_output": latest_run("daily_brief_evening").safe_summary if latest_run("daily_brief_evening") else None,
        },
        {
            "key": "approval_notifications",
            "name": "Approval notifications",
            "category": "notifications",
            "status": "attention" if pending_approvals else "quiet",
            "mode": "event_driven",
            "schedule": "When approval-gated work is proposed",
            "last_run": None,
            "next_run": None,
            "source": "jarvis-core",
            "channels": ["Homepage", "Telegram", "Voice"],
            "summary": f"{pending_approvals} approval(s) currently pending.",
        },
        {
            "key": "notification_delivery",
            "name": "Notification delivery bridge",
            "category": "notifications",
            "status": "attention" if pending_notifications else "quiet",
            "mode": "continuous",
            "schedule": "Bridge services poll pending notifications",
            "last_run": None,
            "next_run": None,
            "source": "telegram-bridge / hey-jarvis / homepage",
            "channels": ["Telegram", "Voice", "Homepage"],
            "summary": f"{pending_notifications} notification(s) waiting for delivery or acknowledgement.",
        },
        {
            "key": "homelab_health",
            "name": "Homelab health check",
            "category": "maintenance",
            "status": "attention" if open_maintenance else "quiet",
            "mode": "scheduled_or_on_demand",
            "schedule": f"08:00 daily plus on demand, {settings.user_timezone}",
            "last_run": latest_run("homelab_health").started_at.isoformat() if latest_run("homelab_health") else (latest_diag.created_at.isoformat() if latest_diag else None),
            "next_run": next_local_time(8, 0),
            "source": "jarvis-core",
            "channels": ["Homepage"],
            "summary": f"{open_maintenance} open maintenance record(s) are visible to diagnostics.",
            "last_output": latest_run("homelab_health").safe_summary if latest_run("homelab_health") else (latest_diag.payload if latest_diag else None),
            "last_status": latest_run("homelab_health").status if latest_run("homelab_health") else None,
        },
        {
            "key": "drive_migration_scan",
            "name": "Drive migration scan",
            "category": "migration",
            "status": "available",
            "mode": "scheduled_or_on_demand",
            "schedule": f"09:15 weekly Saturday plus manual scan, {settings.user_timezone}",
            "last_run": latest_run("drive_migration_scan").started_at.isoformat() if latest_run("drive_migration_scan") else (recent_drive_copy.started_at.isoformat() if recent_drive_copy and recent_drive_copy.started_at else None),
            "next_run": next_weekday_time(5, 9, 15),
            "source": "jarvis-core / google-tools-worker",
            "channels": ["Homepage"],
            "summary": "Inventories My Drive metadata, hides excluded folders, and stages/imports copy jobs only after approval.",
            "last_output": latest_run("drive_migration_scan").safe_summary if latest_run("drive_migration_scan") else (recent_drive_copy.safe_summary if recent_drive_copy else None),
            "last_status": latest_run("drive_migration_scan").status if latest_run("drive_migration_scan") else (recent_drive_copy.status if recent_drive_copy else None),
        },
        {
            "key": "gmail_needs_reply_scan",
            "name": "Gmail inbox organizer",
            "category": "email",
            "status": "available",
            "mode": "scheduled_or_on_demand",
            "schedule": f"08:45 daily plus on demand, {settings.user_timezone}",
            "last_run": latest_run("gmail_needs_reply_scan").started_at.isoformat() if latest_run("gmail_needs_reply_scan") else (recent_gmail_cleanup.started_at.isoformat() if recent_gmail_cleanup and recent_gmail_cleanup.started_at else None),
            "next_run": next_local_time(8, 45),
            "source": "jarvis-core / google-tools-worker",
            "channels": ["Homepage", "Telegram"],
            "summary": "Safely labels Gmail, stars reply/interview candidates, and archives newsletter/promotional mail. It never moves Inbox mail to spam, junk, or trash.",
            "last_output": latest_run("gmail_needs_reply_scan").safe_summary if latest_run("gmail_needs_reply_scan") else (recent_gmail_cleanup.safe_summary if recent_gmail_cleanup else None),
            "last_status": latest_run("gmail_needs_reply_scan").status if latest_run("gmail_needs_reply_scan") else (recent_gmail_cleanup.status if recent_gmail_cleanup else None),
        },
        {
            "key": "pihole_dns_health",
            "name": "Pi-hole/DNS health check",
            "category": "network",
            "status": "available",
            "mode": "scheduled_or_on_demand",
            "schedule": f"08:05 daily plus on demand, {settings.user_timezone}",
            "last_run": latest_run("pihole_dns_health").started_at.isoformat() if latest_run("pihole_dns_health") else (latest_diag.created_at.isoformat() if latest_diag else None),
            "next_run": next_local_time(8, 5),
            "source": "jarvis-core diagnostics",
            "channels": ["Homepage"],
            "summary": "Checks Pi-hole reachability through the homelab diagnostics surface; DNS filtering remains hosted by Pi-hole.",
            "last_output": latest_run("pihole_dns_health").safe_summary if latest_run("pihole_dns_health") else (latest_diag.payload if latest_diag else None),
            "last_status": latest_run("pihole_dns_health").status if latest_run("pihole_dns_health") else None,
        },
        {
            "key": "media_automations",
            "name": "Media automations",
            "category": "media",
            "status": "available",
            "mode": "external_service",
            "schedule": "Managed by the media automation stack",
            "last_run": None,
            "next_run": None,
            "source": "media-creation-pipeline",
            "channels": ["Homepage"],
            "summary": "Jarvis can display status and route approval-gated media actions when the media stack is ready.",
        },
    ]
    scheduled = [item for item in automations if item["mode"] in {"scheduled_or_on_demand", "continuous", "event_driven"}]
    return {"ok": True, "automations": automations, "total": len(automations), "scheduled": len(scheduled)}


@app.post("/api/v1/automations/{automation_key}/run")
def run_automation(automation_key: str, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    return run_automation_key(db, automation_key, trigger="manual", actor=actor)


def automation_runner_loop():
    time.sleep(20)
    while True:
        try:
            db = SessionLocal()
            try:
                for key in due_automation_keys(db):
                    run_automation_key(db, key, trigger="scheduled", actor="jarvis-automation-runner")
            finally:
                db.close()
        except Exception:
            pass
        time.sleep(max(30, settings.automation_runner_interval_seconds))


def due_automation_keys(db: Session):
    local_now = datetime.now(ZoneInfo(settings.user_timezone))
    due = []
    daily_specs = [
        ("daily_brief_morning", 7, 30),
        ("homelab_health", 8, 0),
        ("pihole_dns_health", 8, 5),
        ("gmail_needs_reply_scan", 8, 45),
        ("daily_brief_evening", 20, 30),
    ]
    for key, hour, minute in daily_specs:
        if local_now.hour > hour or (local_now.hour == hour and local_now.minute >= minute):
            if not automation_ran_today(db, key, local_now):
                due.append(key)
    if local_now.weekday() == 5 and (local_now.hour > 9 or (local_now.hour == 9 and local_now.minute >= 15)):
        if not automation_ran_today(db, "drive_migration_scan", local_now):
            due.append("drive_migration_scan")
    return due


def automation_ran_today(db: Session, key: str, local_now: datetime):
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_start = local_start.astimezone(timezone.utc)
    return (
        db.query(AutomationRunRecord)
        .filter(AutomationRunRecord.automation_key == key)
        .filter(AutomationRunRecord.started_at >= utc_start)
        .filter(AutomationRunRecord.status.in_(("completed", "running")))
        .first()
        is not None
    )


def run_automation_key(db: Session, key: str, trigger: str = "manual", actor: str = "jarvis-core"):
    allowed = {
        "daily_brief_morning",
        "daily_brief_evening",
        "homelab_health",
        "pihole_dns_health",
        "drive_migration_scan",
        "gmail_needs_reply_scan",
        "approval_notifications",
        "notification_delivery",
        "media_automations",
    }
    if key not in allowed:
        raise HTTPException(status_code=404, detail={"error": "automation_not_found", "key": key})
    run = AutomationRunRecord(
        id=new_id("auto"),
        automation_key=key,
        status="running",
        trigger=trigger,
        scheduled_for=now_utc() if trigger == "scheduled" else None,
        output={},
    )
    db.add(run)
    db.commit()
    try:
        output, summary = execute_automation_key(db, key, actor)
        run.status = "completed"
        run.output = json_safe(output)
        run.safe_summary = summary
        run.completed_at = now_utc()
        audit(db, "automation.completed", actor, new_id("corr"), run.id, {"automation_key": key, "trigger": trigger, "summary": summary})
        db.commit()
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:1000]
        run.safe_summary = f"{key} failed: {str(exc)[:240]}"
        run.completed_at = now_utc()
        audit(db, "automation.failed", actor, new_id("corr"), run.id, {"automation_key": key, "trigger": trigger, "error": str(exc)[:240]})
        db.commit()
    return automation_run_response(run)


def execute_automation_key(db: Session, key: str, actor: str):
    if key == "daily_brief_morning":
        payload = daily_brief("morning", True, db, actor)
        return payload, f"Morning brief saved and queued for delivery: {payload.get('saved_brief_id')}"
    if key == "daily_brief_evening":
        payload = daily_brief("evening", True, db, actor)
        return payload, f"Evening brief saved and queued for delivery: {payload.get('saved_brief_id')}"
    if key == "gmail_needs_reply_scan":
        payload = run_safe_gmail_inbox_organizer()
        counts = payload.get("counts") or {}
        notify_many(
            db,
            actor,
            ("homepage", "telegram"),
            "Gmail inbox organized",
            payload.get("text") or "Safe Gmail labels/stars/archive actions completed.",
            "info",
            {"automation_key": key, "counts": counts, "mode": "no_spam_no_trash"},
        )
        return payload, payload.get("text") or "Gmail inbox organizer completed."
    if key == "homelab_health":
        payload = homelab_diagnostics(db, actor)
        failed = len([item for item in payload.get("checks") or [] if not item.get("ok")])
        if failed:
            notify_many(db, actor, ("homepage", "telegram"), "Homelab health attention", f"{failed} check(s) need attention.", "warning", {"automation_key": key})
        return payload, f"Homelab health check completed: {failed} issue(s)."
    if key == "pihole_dns_health":
        payload = http_health_check("pihole", settings.pihole_url)
        if not payload.get("ok"):
            notify_many(db, actor, ("homepage", "telegram"), "Pi-hole/DNS attention", payload.get("summary") or payload.get("error") or "Pi-hole check failed.", "warning", {"automation_key": key})
        return payload, "Pi-hole/DNS check OK." if payload.get("ok") else "Pi-hole/DNS check needs attention."
    if key == "drive_migration_scan":
        payload = call_google_tools("/drive/staging-status", {"max_results": 50}, timeout=60)
        return payload, f"Drive migration scan completed: {payload.get('total', 0)} staged item(s)."
    if key == "approval_notifications":
        pending = db.query(ApprovalRequestRecord).filter(ApprovalRequestRecord.status == "pending").count()
        return {"pending_approvals": pending}, f"{pending} approval(s) pending."
    if key == "notification_delivery":
        pending = db.query(NotificationRecord).filter(NotificationRecord.status == "pending").count()
        return {"pending_notifications": pending}, f"{pending} notification(s) pending delivery."
    if key == "media_automations":
        payload = media_automations_status(actor)
        return payload, payload.get("preview") or "Media automation status checked."
    raise ValueError(f"unsupported_automation_key={key}")


def automation_run_response(run: AutomationRunRecord):
    return {
        "id": run.id,
        "automation_key": run.automation_key,
        "status": run.status,
        "trigger": run.trigger,
        "scheduled_for": run.scheduled_for.isoformat() if run.scheduled_for else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "safe_summary": run.safe_summary,
        "error": run.error,
        "output": run.output,
    }


@app.post("/api/v1/daily-brief/actions")
def create_daily_brief_action(payload: DailyBriefActionCreate, db: Session = Depends(get_db), actor: str = Depends(authorize)):
    if payload.action_type == "calendar_hold":
        when_text = payload.when_text or "tomorrow morning"
        text = f"Schedule {payload.estimated_minutes or 30} minutes {when_text} for {payload.title}."
        return create_request(RequestCreate(request=text, source="daily-brief-action", idempotency_key=payload.idempotency_key), db, actor)
    task = TaskRecord(
        id=new_id("task"),
        title=payload.title,
        priority=payload.priority,
        estimated_minutes=payload.estimated_minutes,
        source="daily-brief-action",
        tags=["daily-brief"],
        status="open",
    )
    db.add(task)
    audit(db, "daily_brief.action_created", actor, new_id("corr"), task.id, {"action_type": payload.action_type, "title": payload.title})
    db.commit()
    return {"type": "task", "task": task_response(task)}


def execute_action(db: Session, action: ProposedActionRecord, actor: str):
    if action.requires_approval:
        approval = db.query(ApprovalRequestRecord).filter_by(proposed_action_id=action.id).first()
        if not approval or approval.status != "approved":
            raise HTTPException(status_code=409, detail={"error": "approval_required"})

    attempt = ExecutionAttemptRecord(id=new_id("exec"), proposed_action_id=action.id, status="running", retry_count=0)
    db.add(attempt)
    audit_for_action(db, "execution.started", action, actor, {"execution_id": attempt.id})
    if action.tool_name == "codex.run_task":
        try:
            payload = execute_codex_action(action)
            attempt.status = "completed" if payload.get("status") == "completed" else "failed"
            job_summary = payload.get("job_summary") or {}
            attempt.safe_summary = job_summary.get("summary") or payload.get("summary") or payload.get("text", "")[:240]
            attempt.completed_at = now_utc()
            result = ExecutionResultRecord(
                id=new_id("result"),
                execution_attempt_id=attempt.id,
                outcome=attempt.status,
                payload={
                    "codex": payload,
                    "summary": job_summary.get("summary"),
                    "changed_files": job_summary.get("changed_files") or [],
                    "test_results": job_summary.get("test_results") or [],
                    "mode": payload.get("mode") or action.arguments.get("mode"),
                    "job_id": payload.get("job_id"),
                },
            )
            db.add(result)
            db.flush()
            verification = VerificationResultRecord(
                id=new_id("verify"),
                execution_result_id=result.id,
                status="verified" if attempt.status == "completed" else "failed",
                payload={
                    "checked": "codex_worker_result_recorded",
                    "job_id": payload.get("job_id"),
                    "changed_file_count": len(job_summary.get("changed_files") or []),
                    "test_result_count": len(job_summary.get("test_results") or []),
                },
            )
            db.add(verification)
            db.add(OutboxEventRecord(id=new_id("outbox"), event_type="execution.completed", payload={"action_id": action.id, "result_id": result.id, "provider": "codex"}))
            action.status = ActionStatus.COMPLETED.value if attempt.status == "completed" else ActionStatus.FAILED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = action.status
            notify_many(
                db,
                actor,
                ("homepage", "telegram", "voice"),
                "Codex job completed" if attempt.status == "completed" else "Codex job failed",
                attempt.safe_summary or "",
                "info" if attempt.status == "completed" else "warning",
                {"action_id": action.id, "job_id": payload.get("job_id"), "mode": payload.get("mode") or action.arguments.get("mode")},
            )
            audit_for_action(db, "execution.completed" if action.status == ActionStatus.COMPLETED.value else "execution.failed", action, actor, {"execution_id": attempt.id, "provider": "codex", "job_id": payload.get("job_id")})
            return
        except Exception as exc:
            attempt.status = "failed"
            attempt.error_category = "codex_execution_failed"
            attempt.safe_summary = f"Codex execution failed: {str(exc)[:240]}"
            attempt.completed_at = now_utc()
            action.status = ActionStatus.FAILED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = "failed"
            notify_many(db, actor, ("homepage", "telegram", "voice"), "Codex execution failed", str(exc)[:500], "warning", {"action_id": action.id})
            audit_for_action(db, "execution.failed", action, actor, {"execution_id": attempt.id, "provider": "codex", "error": str(exc)[:240]})
            return
    if action.tool_name == "drive.copy_to_staging":
        try:
            payload = execute_drive_staging_copy_action(action)
            attempt.status = "completed"
            attempt.safe_summary = payload.get("text") or f"Copied {len(payload.get('manifests') or [])} Drive item(s) to staging."
            attempt.completed_at = now_utc()
            result = ExecutionResultRecord(id=new_id("result"), execution_attempt_id=attempt.id, outcome="success", payload={"drive_staging": payload})
            db.add(result)
            db.flush()
            verification = VerificationResultRecord(
                id=new_id("verify"),
                execution_result_id=result.id,
                status="verified",
                payload={"checked": "drive_staging_manifests_recorded", "manifest_count": len(payload.get("manifests") or [])},
            )
            db.add(verification)
            db.add(OutboxEventRecord(id=new_id("outbox"), event_type="execution.completed", payload={"action_id": action.id, "result_id": result.id, "provider": "google-drive"}))
            action.status = ActionStatus.COMPLETED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = "completed"
            notify_many(db, actor, ("homepage", "telegram", "voice"), "Drive staging copy completed", attempt.safe_summary or "", "info", {"action_id": action.id, "count": len(payload.get("manifests") or [])})
            audit_for_action(db, "execution.completed", action, actor, {"execution_id": attempt.id, "provider": "google-drive", "count": len(payload.get("manifests") or [])})
            audit_for_action(db, "verification.completed", action, actor, {"verification_id": verification.id, "provider": "google-drive"})
            return
        except Exception as exc:
            attempt.status = "failed"
            attempt.error_category = "drive_staging_copy_failed"
            attempt.safe_summary = f"Drive staging copy failed: {str(exc)[:240]}"
            attempt.completed_at = now_utc()
            action.status = ActionStatus.FAILED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = "failed"
            notify_many(db, actor, ("homepage", "telegram", "voice"), "Drive staging copy failed", str(exc)[:500], "warning", {"action_id": action.id})
            audit_for_action(db, "execution.failed", action, actor, {"execution_id": attempt.id, "provider": "google-drive", "error": str(exc)[:240]})
            return
    if action.tool_name == "drive.import_to_nextcloud":
        try:
            payload = execute_drive_nextcloud_import_action(action)
            attempt.status = "completed"
            attempt.safe_summary = payload.get("text") or f"Copied {len(payload.get('imports') or [])} staged Drive item(s) to the Nextcloud import queue."
            attempt.completed_at = now_utc()
            result = ExecutionResultRecord(id=new_id("result"), execution_attempt_id=attempt.id, outcome="success", payload={"nextcloud_import": payload})
            db.add(result)
            db.flush()
            visible_count = sum(1 for item in payload.get("imports") or [] if (item.get("nextcloud_visible") or {}).get("ok") is True)
            verification = VerificationResultRecord(
                id=new_id("verify"),
                execution_result_id=result.id,
                status="verified" if visible_count == len(payload.get("imports") or []) else "partial",
                payload={"checked": "nextcloud_webdav_visibility", "import_count": len(payload.get("imports") or []), "visible_count": visible_count, "import_root": payload.get("import_root")},
            )
            db.add(verification)
            db.add(OutboxEventRecord(id=new_id("outbox"), event_type="execution.completed", payload={"action_id": action.id, "result_id": result.id, "provider": "nextcloud"}))
            action.status = ActionStatus.COMPLETED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = "completed"
            notify_many(db, actor, ("homepage", "telegram", "voice"), "Nextcloud import completed", attempt.safe_summary or "", "info", {"action_id": action.id, "count": len(payload.get("imports") or [])})
            audit_for_action(db, "execution.completed", action, actor, {"execution_id": attempt.id, "provider": "nextcloud", "count": len(payload.get("imports") or [])})
            audit_for_action(db, "verification.completed", action, actor, {"verification_id": verification.id, "provider": "nextcloud"})
            return
        except Exception as exc:
            attempt.status = "failed"
            attempt.error_category = "drive_nextcloud_import_failed"
            attempt.safe_summary = f"Nextcloud import failed: {str(exc)[:240]}"
            attempt.completed_at = now_utc()
            action.status = ActionStatus.FAILED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = "failed"
            notify_many(db, actor, ("homepage", "telegram", "voice"), "Nextcloud import failed", str(exc)[:500], "warning", {"action_id": action.id})
            audit_for_action(db, "execution.failed", action, actor, {"execution_id": attempt.id, "provider": "nextcloud", "error": str(exc)[:240]})
            return
    if action.tool_name == "drive.import_to_paperless":
        try:
            payload = execute_drive_paperless_import_action(action)
            attempt.status = "completed"
            attempt.safe_summary = payload.get("text") or f"Queued {len(payload.get('imports') or [])} staged Drive document(s) for Paperless."
            attempt.completed_at = now_utc()
            result = ExecutionResultRecord(id=new_id("result"), execution_attempt_id=attempt.id, outcome="success", payload={"paperless_import": payload})
            db.add(result)
            db.flush()
            verification = VerificationResultRecord(
                id=new_id("verify"),
                execution_result_id=result.id,
                status="queued",
                payload={"checked": "paperless_consume_queue", "import_count": len(payload.get("imports") or []), "consume_dir": payload.get("consume_dir")},
            )
            db.add(verification)
            db.add(OutboxEventRecord(id=new_id("outbox"), event_type="execution.completed", payload={"action_id": action.id, "result_id": result.id, "provider": "paperless"}))
            action.status = ActionStatus.COMPLETED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = "completed"
            notify_many(db, actor, ("homepage", "telegram", "voice"), "Paperless import queued", attempt.safe_summary or "", "info", {"action_id": action.id, "count": len(payload.get("imports") or [])})
            audit_for_action(db, "execution.completed", action, actor, {"execution_id": attempt.id, "provider": "paperless", "count": len(payload.get("imports") or [])})
            audit_for_action(db, "verification.completed", action, actor, {"verification_id": verification.id, "provider": "paperless"})
            return
        except Exception as exc:
            attempt.status = "failed"
            attempt.error_category = "drive_paperless_import_failed"
            attempt.safe_summary = f"Paperless import failed: {str(exc)[:240]}"
            attempt.completed_at = now_utc()
            action.status = ActionStatus.FAILED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = "failed"
            notify_many(db, actor, ("homepage", "telegram", "voice"), "Paperless import failed", str(exc)[:500], "warning", {"action_id": action.id})
            audit_for_action(db, "execution.failed", action, actor, {"execution_id": attempt.id, "provider": "paperless", "error": str(exc)[:240]})
            return
    if action.tool_name == "gmail.apply_cleanup":
        try:
            payload = execute_gmail_cleanup_action(action)
            attempt.status = "completed"
            attempt.safe_summary = payload.get("text") or "Verified Gmail cleanup label update."
            attempt.completed_at = now_utc()
            result = ExecutionResultRecord(id=new_id("result"), execution_attempt_id=attempt.id, outcome="success", payload={"gmail_cleanup": payload})
            db.add(result)
            db.flush()
            verification = VerificationResultRecord(id=new_id("verify"), execution_result_id=result.id, status="verified", payload={"checked": "gmail_label_update", "message_count": len(payload.get("messages") or [])})
            db.add(verification)
            db.add(OutboxEventRecord(id=new_id("outbox"), event_type="execution.completed", payload={"action_id": action.id, "result_id": result.id, "provider": "gmail"}))
            action.status = ActionStatus.COMPLETED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = "completed"
            notify_many(db, actor, ("homepage", "telegram", "voice"), "Gmail cleanup completed", attempt.safe_summary or "", "info", {"action_id": action.id})
            audit_for_action(db, "execution.completed", action, actor, {"execution_id": attempt.id, "provider": "gmail", "message_count": len(payload.get("messages") or [])})
            audit_for_action(db, "verification.completed", action, actor, {"verification_id": verification.id, "provider": "gmail"})
            return
        except Exception as exc:
            attempt.status = "failed"
            attempt.error_category = "gmail_cleanup_failed"
            attempt.safe_summary = f"Gmail cleanup failed: {str(exc)[:240]}"
            attempt.completed_at = now_utc()
            action.status = ActionStatus.FAILED.value
            request = db.get(RequestRecord, action.request_id)
            request.status = "failed"
            notify_many(db, actor, ("homepage", "telegram", "voice"), "Gmail cleanup failed", str(exc)[:500], "warning", {"action_id": action.id})
            audit_for_action(db, "execution.failed", action, actor, {"execution_id": attempt.id, "provider": "gmail", "error": str(exc)[:240]})
            return
    if action.tool_name in {"calendar.schedule_google_event", "calendar.schedule_simulated_event"}:
        if action.tool_name == "calendar.schedule_google_event":
            try:
                payload = execute_google_calendar_action(action)
                attempt.status = "completed"
                attempt.safe_summary = payload.get("text") or f"Google Calendar event created: {action.arguments['title']}"
                attempt.completed_at = now_utc()
                result = ExecutionResultRecord(id=new_id("result"), execution_attempt_id=attempt.id, outcome="success", payload={"google_calendar": payload})
                db.add(result)
                db.flush()
                db.add(OutboxEventRecord(id=new_id("outbox"), event_type="execution.completed", payload={"action_id": action.id, "result_id": result.id, "provider": "google"}))
                verification = VerificationResultRecord(id=new_id("verify"), execution_result_id=result.id, status="verified", payload={"checked": "google_tools_worker_verified_event", "result": payload})
                db.add(verification)
                action.status = ActionStatus.COMPLETED.value
                audit_for_action(db, "execution.completed", action, actor, {"execution_id": attempt.id, "provider": "google"})
                audit_for_action(db, "verification.completed", action, actor, {"verification_id": verification.id, "provider": "google"})
                request = db.get(RequestRecord, action.request_id)
                request.status = "completed"
                return
            except Exception as exc:
                if not settings.calendar_allow_simulated_fallback:
                    attempt.status = "failed"
                    attempt.error_category = "google_calendar_execution_failed"
                    attempt.safe_summary = f"Google Calendar execution failed: {str(exc)[:240]}"
                    attempt.completed_at = now_utc()
                    action.status = ActionStatus.FAILED.value
                    audit_for_action(db, "execution.failed", action, actor, {"execution_id": attempt.id, "provider": "google", "error": str(exc)[:240]})
                    request = db.get(RequestRecord, action.request_id)
                    request.status = "failed"
                    return
                audit_for_action(db, "execution.fallback", action, actor, {"from": "google", "to": "simulated", "error": str(exc)[:240]})
        existing = db.query(CalendarEventRecord).filter_by(source_action_id=action.id).first()
        if existing:
            payload = calendar_event_response(existing)
        else:
            args = action.arguments
            event = CalendarEventRecord(
                id=new_id("cal"),
                title=args["title"],
                calendar_target=args["calendar_target"],
                timezone=args["timezone"],
                starts_at=datetime.fromisoformat(args["starts_at"]),
                ends_at=datetime.fromisoformat(args["ends_at"]),
                source_action_id=action.id,
            )
            db.add(event)
            payload = calendar_event_response(event)
        attempt.status = "completed"
        attempt.safe_summary = f"Simulated event created: {payload['title']}"
        attempt.completed_at = now_utc()
        result = ExecutionResultRecord(id=new_id("result"), execution_attempt_id=attempt.id, outcome="success", payload={"calendar_event": payload})
        db.add(result)
        db.add(OutboxEventRecord(id=new_id("outbox"), event_type="execution.completed", payload={"action_id": action.id, "result_id": result.id}))
        verification = VerificationResultRecord(id=new_id("verify"), execution_result_id=result.id, status="verified", payload={"checked": "simulated_calendar_event_exists", "event": payload})
        db.add(verification)
        action.status = ActionStatus.COMPLETED.value
        audit_for_action(db, "execution.completed", action, actor, {"execution_id": attempt.id})
        audit_for_action(db, "verification.completed", action, actor, {"verification_id": verification.id})
        request = db.get(RequestRecord, action.request_id)
        request.status = "completed"
        return
    attempt.status = "failed"
    attempt.error_category = "unsupported_tool"
    attempt.completed_at = now_utc()
    action.status = ActionStatus.FAILED.value


def execute_google_calendar_action(action: ProposedActionRecord):
    args = action.arguments
    contract = {
        "version": 1,
        "operation": "create",
        "title": args["title"],
        "start": args["starts_at"],
        "end": args["ends_at"],
        "attendees": [],
        "requires_clarification": False,
        "clarification": "",
    }
    body = json.dumps({"contract": contract, "approved": True}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = settings.google_tools_token or settings.token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        settings.google_tools_url.rstrip("/") + "/calendar/execute-contract",
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"google_tools_http_{exc.code}: {detail[:500]}") from exc
    if data.get("ok") is False:
        raise RuntimeError(data.get("error") or "google_tools_failed")
    result = {key: value for key, value in data.items() if key != "ok"}
    if result.get("status") != "completed":
        raise RuntimeError(result.get("text") or f"google_calendar_status_{result.get('status')}")
    return result


def execute_codex_action(action: ProposedActionRecord):
    payload = {
        "request": action.arguments.get("request") or "",
        "mode": action.arguments.get("mode") or infer_codex_mode(action.arguments.get("request") or ""),
        "action": {
            "action_id": action.id,
            "inputs": {"request": action.arguments.get("request") or "", "mode": action.arguments.get("mode") or infer_codex_mode(action.arguments.get("request") or "")},
        },
        "limits": {"maximum_runtime_seconds": 1800, "maximum_cost_usd": 0},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = settings.codex_worker_token or settings.token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(settings.codex_worker_url.rstrip("/") + "/run", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=1830) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"codex_worker_http_{exc.code}: {detail[:500]}") from exc
    if data.get("ok") is False:
        raise RuntimeError(data.get("error") or "codex_worker_failed")
    return data


def execute_drive_staging_copy_action(action: ProposedActionRecord):
    manifests = []
    failures = []
    for item in action.arguments.get("items") or []:
        try:
            result = call_google_tools(
                "/drive/copy-to-staging",
                {
                    "file_id": item.get("id"),
                    "category": item.get("life_category") or "needs_review",
                    "destination": item.get("recommended_home") or item.get("suggested_destination") or "Nextcloud",
                    "action_id": action.id,
                    "relative_path": item.get("google_drive_path"),
                },
                timeout=240,
            )
            manifests.append(result.get("manifest") or result)
        except Exception as exc:
            failures.append({"file_id": item.get("id"), "name": item.get("name"), "error": str(exc)[:500]})
    if failures:
        raise RuntimeError(f"drive_copy_failures={json.dumps(failures[:3])}")
    return {
        "status": "completed",
        "manifests": manifests,
        "text": f"Copied {len(manifests)} Drive item(s) to homelab staging.",
        "mode": "copy_only_no_google_modifications",
    }


def execute_drive_nextcloud_import_action(action: ProposedActionRecord):
    result = call_google_tools(
        "/drive/import-to-nextcloud",
        {
            "manifest_paths": action.arguments.get("manifest_paths") or [],
            "max_results": action.arguments.get("max_results") or 20,
            "action_id": action.id,
        },
        timeout=240,
    )
    if result.get("ok") is False:
        raise RuntimeError(result.get("error") or "nextcloud_import_failed")
    return result


def execute_drive_paperless_import_action(action: ProposedActionRecord):
    result = call_google_tools(
        "/drive/import-to-paperless",
        {
            "manifest_paths": action.arguments.get("manifest_paths") or [],
            "max_results": action.arguments.get("max_results") or 20,
            "action_id": action.id,
        },
        timeout=240,
    )
    if result.get("ok") is False:
        raise RuntimeError(result.get("error") or "paperless_import_failed")
    return result


def execute_gmail_cleanup_action(action: ProposedActionRecord):
    result = call_google_tools(
        "/gmail/execute-contract",
        {"contract": action.arguments.get("contract") or {}, "approved": True},
        timeout=240,
    )
    if result.get("ok") is False:
        raise RuntimeError(result.get("error") or "gmail_cleanup_failed")
    return result


def run_safe_gmail_inbox_organizer():
    summary = call_google_tools("/gmail/cleanup-summary", {"max_results": 50}, timeout=180)
    results = []

    classification_batches = gmail_classification_batches(summary, 50)
    if classification_batches:
        results.append(
            call_google_tools(
                "/gmail/execute-contract",
                {"contract": {"operation": "label_batches", "batches": classification_batches}, "approved": True},
                timeout=240,
            )
        )

    newsletter_ids = [item.get("id") for item in (summary.get("likely_newsletters") or [])[:25] if item.get("id")]
    if newsletter_ids:
        results.append(
            call_google_tools(
                "/gmail/execute-contract",
                {
                    "contract": {
                        "operation": "label_messages",
                        "message_ids": newsletter_ids,
                        "label_names": ["Jarvis/Newsletters"],
                        "remove_label_ids": ["INBOX"],
                    },
                    "approved": True,
                },
                timeout=240,
            )
        )

    needs_reply_ids = [item.get("id") for item in (summary.get("needs_reply") or [])[:25] if item.get("id")]
    interview_ids = []
    for item in (summary.get("admissions") or []) + (summary.get("medical_school") or []):
        text_value = " ".join(str(item.get(key, "")) for key in ("from", "subject", "snippet")).lower()
        if item.get("id") and "interview" in text_value:
            interview_ids.append(item.get("id"))
    star_ids = sorted(set(needs_reply_ids + interview_ids))
    if star_ids:
        results.append(
            call_google_tools(
                "/gmail/execute-contract",
                {
                    "contract": {
                        "operation": "label_messages",
                        "message_ids": star_ids,
                        "label_ids": ["STARRED"],
                        "label_names": ["Jarvis/Needs Reply"],
                        "remove_label_ids": [],
                    },
                    "approved": True,
                },
                timeout=240,
            )
        )

    failures = [item for item in results if item.get("ok") is False]
    if failures:
        raise RuntimeError(f"gmail_safe_organizer_failures={len(failures)}")
    return {
        "ok": True,
        "mode": "safe_no_spam_no_trash",
        "counts": {
            "classified_batches": len(classification_batches),
            "archived_newsletters": len(newsletter_ids),
            "starred_reply_or_interview": len(star_ids),
            **(summary.get("counts") or {}),
        },
        "results": results,
        "text": f"Gmail organized safely: {len(classification_batches)} label batch(es), {len(newsletter_ids)} newsletter(s) archived, {len(star_ids)} reply/interview item(s) starred. Nothing was moved to spam, junk, or trash.",
    }


def approval_search_text(db: Session, approval: ApprovalRequestRecord):
    action = db.get(ProposedActionRecord, approval.proposed_action_id)
    if not action:
        return approval.reason
    request = db.get(RequestRecord, action.request_id)
    parts = [
        approval.id,
        approval.reason,
        action.id,
        action.tool_name,
        action.preview.get("summary", "") if isinstance(action.preview, dict) else "",
        json.dumps(action.arguments, default=str),
        request.raw_text if request else "",
    ]
    return " ".join(str(item or "") for item in parts)


def action_tool_name(db: Session, action_id: str):
    action = db.get(ProposedActionRecord, action_id)
    return action.tool_name if action else ""


def codex_task_response(db: Session, action: ProposedActionRecord):
    request = db.get(RequestRecord, action.request_id)
    approval = db.query(ApprovalRequestRecord).filter_by(proposed_action_id=action.id).first()
    attempts = db.query(ExecutionAttemptRecord).filter_by(proposed_action_id=action.id).order_by(ExecutionAttemptRecord.started_at.desc()).all()
    latest = execution_response(db, attempts[0]) if attempts else None
    artifacts = []
    latest_result = (latest or {}).get("result") or {}
    if latest_result:
        artifacts = ((latest_result.get("codex") or {}).get("artifacts") or [])
    return {
        "action_id": action.id,
        "request_id": action.request_id,
        "request": request.raw_text if request else "",
        "mode": action.arguments.get("mode") or infer_codex_mode(request.raw_text if request else ""),
        "status": action.status,
        "approval": approval_response(db, approval) if approval else None,
        "latest_execution": latest,
        "artifacts": artifacts,
        "summary": latest_result.get("summary"),
        "changed_files": latest_result.get("changed_files") or [],
        "test_results": latest_result.get("test_results") or [],
        "created_at": action.created_at,
    }


def database_health_check(db: Session):
    try:
        db.execute(text("SELECT 1"))
        return {"name": "postgres", "ok": True, "status": "ready", "summary": "database query succeeded"}
    except Exception as exc:
        return {"name": "postgres", "ok": False, "error": str(exc)[:240]}


def redis_health_check():
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
        return {"name": "redis", "ok": client.ping() is True, "status": "ready", "summary": "redis ping succeeded"}
    except Exception as exc:
        return {"name": "redis", "ok": False, "error": str(exc)[:240]}


def storage_health_checks():
    checks = []
    for name, path in (("tmp", "/tmp"), ("app", "/app")):
        try:
            from pathlib import Path

            target = Path(path)
            checks.append({"name": f"storage:{name}", "ok": target.exists(), "path": path, "summary": "path exists" if target.exists() else "path missing"})
        except Exception as exc:
            checks.append({"name": f"storage:{name}", "ok": False, "path": path, "error": str(exc)[:240]})
    return checks


def is_coding_request(text: str):
    lowered = str(text or "").lower()
    return any(
        term in lowered
        for term in (
            "codex",
            "coding task",
            "code task",
            "fix code",
            "implement",
            "debug",
            "refactor",
            "write tests",
            "run tests",
            "edit repo",
            "change the code",
        )
    )


def infer_codex_mode(text: str):
    lowered = str(text or "").lower().replace("_", "-")
    for mode in ("inspect-only", "plan-only", "patch-only", "test-only"):
        if mode in lowered:
            return mode
    if "inspect" in lowered or "read-only" in lowered:
        return "inspect-only"
    if "plan" in lowered:
        return "plan-only"
    if "run tests" in lowered or "test-only" in lowered:
        return "test-only"
    if "patch" in lowered or "edit" in lowered or "fix" in lowered or "implement" in lowered or "refactor" in lowered:
        return "patch-only"
    return "plan-only"


def codex_mode_changes(mode: str):
    return {
        "inspect-only": ["Codex may inspect files and summarize findings, but must not write files."],
        "plan-only": ["Codex may inspect files and produce an implementation plan, but must not write files."],
        "patch-only": ["Codex may make scoped file edits, but should not run broad test suites unless needed for the patch."],
        "test-only": ["Codex may run targeted tests/checks and record results, but must not edit source files."],
        "execute": ["Codex may perform the approved coding workflow with scoped edits and targeted verification."],
    }.get(mode, ["Codex will use the safest available mode."])


def notify(db: Session, user_id: str, channel: str, title: str, body: str, severity: str, payload: dict):
    record = NotificationRecord(
        id=new_id("notif"),
        user_id=user_id,
        channel=channel,
        status="pending",
        payload={
            "title": title,
            "body": body,
            "severity": severity,
            **(payload or {}),
        },
    )
    db.add(record)
    db.add(OutboxEventRecord(id=new_id("outbox"), event_type=f"notification.{channel}.pending", payload={"notification_id": record.id, "title": title, "severity": severity}))
    return record


def notify_many(db: Session, user_id: str, channels, title: str, body: str, severity: str, payload: dict):
    records = []
    for channel in channels:
        records.append(notify(db, user_id, channel, title, body, severity, payload))
    return records


def notification_response(record: NotificationRecord):
    return {
        "id": record.id,
        "user_id": record.user_id,
        "channel": record.channel,
        "status": record.status,
        "payload": record.payload,
        "created_at": record.created_at,
    }


def collect_git_commits(limit: int = 20):
    headers = {"Content-Type": "application/json"}
    token = settings.codex_worker_token or settings.token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        request = urllib.request.Request(
            settings.codex_worker_url.rstrip("/") + f"/git/commits?limit={max(1, min(limit, 50))}",
            method="GET",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return [{"status": "unavailable", "error": str(exc)[:240]}]
    return data.get("commits") or []


def collect_google_document_references():
    try:
        result = call_google_tools("/drive/search", {"query": "modifiedTime > '1970-01-01T00:00:00Z'", "max_results": 10}, timeout=60)
        return {"status": "completed", "items": result.get("files") or result.get("documents") or [], "text": result.get("text")}
    except Exception as exc:
        return {"status": "not_configured", "items": [], "error": str(exc)[:240]}


def collect_drive_files(
    query: str,
    max_results: int,
    include_folder_ids: list[str] | None = None,
    exclude_names: list[str] | None = None,
    include_paths: bool = False,
    top_level_only: bool = False,
    root_topics_only: bool = False,
    my_drive_only: bool = True,
):
    include_folder_ids = [item for item in (include_folder_ids or []) if item]
    folders, excluded_folder_ids = drive_folder_metadata_with_exclusions(10000, exclude_names, my_drive_only=my_drive_only) if include_folder_ids or include_paths or top_level_only or normalize_drive_exclude_names(exclude_names) else ([], set())
    folder_ids = include_descendant_folder_ids(include_folder_ids, folders) if include_folder_ids else []
    if folder_ids:
        parent_query = " or ".join(f"'{folder_id}' in parents" for folder_id in folder_ids)
        query = f"({parent_query}) and trashed = false"
    result = call_google_tools("/drive/search", {"query": query or "trashed = false", "max_results": max_results, "my_drive_only": my_drive_only}, timeout=180)
    files = filter_drive_items(result.get("files") or [], exclude_names, excluded_folder_ids)
    if top_level_only:
        files = top_level_drive_items(files, folders)
    if root_topics_only:
        files = [item for item in files if is_drive_root_topic(item)]
    return enrich_drive_paths(files, folders) if include_paths or include_folder_ids else files


def collect_drive_children(
    folder_id: str | None,
    max_results: int,
    exclude_names: list[str] | None = None,
    my_drive_only: bool = True,
):
    folder_id = str(folder_id or "").strip()
    if not folder_id:
        roots = drive_folder_metadata(10000, exclude_names, my_drive_only=my_drive_only)
        roots = top_level_drive_items(roots, roots)
        roots = [folder for folder in roots if is_drive_root_topic(folder)]
        return {"ok": True, "folder_id": None, "folders": roots, "files": [], "mode": "metadata_only"}
    folders, excluded_folder_ids = drive_folder_metadata_with_exclusions(10000, exclude_names, my_drive_only=my_drive_only)
    query = f"'{folder_id}' in parents and trashed = false"
    result = call_google_tools("/drive/search", {"query": query, "max_results": max_results, "my_drive_only": my_drive_only}, timeout=180)
    children = filter_drive_items(result.get("files") or [], exclude_names, excluded_folder_ids)
    child_folders = [item for item in children if item.get("mime_type") == "application/vnd.google-apps.folder"]
    child_files = [item for item in children if item.get("mime_type") != "application/vnd.google-apps.folder"]
    inventory = build_drive_inventory(enrich_drive_paths(child_files, folders))
    return {
        "ok": True,
        "folder_id": folder_id,
        "folders": child_folders,
        "files": inventory["items"],
        "summary": f"{len(child_folders)} folders, {len(inventory['items'])} files",
        "mode": "metadata_only",
    }


def is_drive_root_topic(item: dict):
    name = str(item.get("name") or "").strip()
    prefix, sep, suffix = name.partition("_")
    return bool(sep and prefix.isdigit() and suffix.strip())


def top_level_drive_items(items: list[dict], folders: list[dict]):
    visible_folder_ids = {folder.get("id") for folder in folders if folder.get("id")}
    return [item for item in items if not any(parent in visible_folder_ids for parent in item.get("parents") or [])]


def drive_folder_metadata(max_results: int = 1000, exclude_names: list[str] | None = None, my_drive_only: bool = True):
    folders, _ = drive_folder_metadata_with_exclusions(max_results, exclude_names, my_drive_only=my_drive_only)
    return folders


def drive_folder_metadata_with_exclusions(max_results: int = 1000, exclude_names: list[str] | None = None, my_drive_only: bool = True):
    result = call_google_tools("/drive/folders", {"max_results": max_results, "my_drive_only": my_drive_only}, timeout=180)
    folders = result.get("folders") or []
    excluded_folder_ids = drive_excluded_folder_ids(folders, exclude_names)
    return filter_drive_items(folders, exclude_names, excluded_folder_ids), excluded_folder_ids


def include_descendant_folder_ids(selected_ids: list[str], folders: list[dict]):
    selected = set(selected_ids)
    changed = True
    while changed:
        changed = False
        for folder in folders:
            if folder.get("id") in selected:
                continue
            if any(parent in selected for parent in folder.get("parents") or []):
                selected.add(folder.get("id"))
                changed = True
    return list(selected)


def enrich_drive_paths(items: list[dict], folders: list[dict]):
    folder_by_id = {folder.get("id"): folder for folder in folders}

    def folder_path(folder_id: str, seen=None):
        seen = seen or set()
        if not folder_id or folder_id in seen or folder_id not in folder_by_id:
            return []
        seen.add(folder_id)
        folder = folder_by_id[folder_id]
        parent_ids = folder.get("parents") or []
        parent_parts = folder_path(parent_ids[0], seen) if parent_ids else []
        return parent_parts + [folder.get("name") or folder_id]

    enriched = []
    for item in items:
        parents = item.get("parents") or []
        path_parts = folder_path(parents[0]) if parents else []
        clone = dict(item)
        clone["google_drive_folder_path"] = "/".join(path_parts)
        clone["google_drive_path"] = "/".join(path_parts + [item.get("name") or item.get("id")])
        enriched.append(clone)
    return enriched


def normalize_drive_exclude_names(exclude_names: list[str] | None = None):
    tokens = [item.strip().lower() for item in DEFAULT_DRIVE_EXCLUDE_NAMES]
    tokens.extend(item.strip().lower() for item in (exclude_names or []) if item and item.strip())
    normalized = []
    for token in tokens:
        if token and token not in normalized:
            normalized.append(token)
    return normalized


def drive_excluded_folder_ids(folders: list[dict], exclude_names: list[str] | None = None):
    excluded = normalize_drive_exclude_names(exclude_names)
    if not excluded and not DEFAULT_DRIVE_EXCLUDE_FOLDER_IDS:
        return set()
    folder_ids = set(DEFAULT_DRIVE_EXCLUDE_FOLDER_IDS)
    folder_ids.update(
        folder.get("id")
        for folder in folders
        if any(token in (folder.get("name") or "").lower() for token in excluded)
    )
    changed = True
    while changed:
        changed = False
        for folder in folders:
            folder_id = folder.get("id")
            if not folder_id or folder_id in folder_ids:
                continue
            if any(parent in folder_ids for parent in folder.get("parents") or []):
                folder_ids.add(folder_id)
                changed = True
    return folder_ids


def filter_drive_items(items: list[dict], exclude_names: list[str] | None = None, excluded_folder_ids: set[str] | None = None):
    excluded = normalize_drive_exclude_names(exclude_names)
    excluded_folder_ids = excluded_folder_ids or set()
    if not excluded and not excluded_folder_ids:
        return items
    filtered = []
    for item in items:
        if item.get("id") in excluded_folder_ids:
            continue
        name = (item.get("name") or "").lower()
        if any(token in name for token in excluded):
            continue
        if any(parent in excluded_folder_ids for parent in item.get("parents") or []):
            continue
        filtered.append(item)
    return filtered


def drive_destination_for(item: dict):
    kind = drive_kind(item)
    category = drive_life_category_for(item)
    return drive_route_for(item, category, kind)["recommended_home"]


def drive_text(item: dict):
    return " ".join(str(item.get(key) or "").lower() for key in ("name", "mime_type"))


def drive_life_category_for(item: dict):
    text = drive_text(item)
    category_keywords = [
        (
            "professional_education",
            [
                "enmed",
                "mcat",
                "school",
                "course",
                "class",
                "lecture",
                "exam",
                "interview",
                "application",
                "transcript",
                "shadowing",
                "medicine",
                "premed",
            ],
        ),
        (
            "professional_work",
            [
                "work",
                "job",
                "resume",
                "cv",
                "cover letter",
                "portfolio",
                "client",
                "contract",
                "invoice",
                "meeting",
                "project",
                "okr",
            ],
        ),
        (
            "research",
            [
                "research",
                "paper",
                "pubmed",
                "manuscript",
                "abstract",
                "poster",
                "dataset",
                "study",
                "lab",
                "protocol",
                "citation",
            ],
        ),
        (
            "hobbies",
            [
                "hobby",
                "music",
                "game",
                "gaming",
                "media",
                "photo",
                "video",
                "recipe",
                "travel",
                "fitness",
                "workout",
            ],
        ),
        (
            "personal_lifeadmin",
            [
                "personal",
                "life",
                "admin",
                "tax",
                "bank",
                "insurance",
                "medical",
                "health",
                "home",
                "lease",
                "receipt",
                "bill",
                "budget",
            ],
        ),
    ]
    for category, keywords in category_keywords:
        if any(keyword in text for keyword in keywords):
            return category
    return "needs_review"


def drive_migration_action_for(item: dict, category: str):
    mime = (item.get("mime_type") or "").lower()
    name = (item.get("name") or "").lower()
    if category == "needs_review":
        return "needs_review"
    if "folder" in mime:
        return "needs_review"
    if name.startswith(("untitled", "copy of ", "duplicate")) or "archive" in name or "old" in name:
        return "archive"
    if "form" in mime or "shortcut" in mime or "jamboard" in mime:
        return "keep_in_google"
    if "google-apps" in mime and not any(token in mime for token in ("document", "spreadsheet", "presentation")):
        return "keep_in_google"
    return "copy_to_homelab"


def drive_route_for(item: dict, category: str, kind: str):
    text_value = drive_text(item)
    route = {
        "recommended_home": "Nextcloud",
        "secondary_home": None,
        "relationship_home": "Jarvis Core index",
        "reason": "General files belong in normal file storage, while Jarvis keeps the searchable index, category, decision, and source link.",
    }
    if kind == "folder":
        route.update(
            {
                "recommended_home": "Needs Review",
                "reason": "Folders need a child inventory before Jarvis can safely route the files inside.",
            }
        )
        return route

    official_terms = ("receipt", "bill", "invoice", "tax", "insurance", "lease", "transcript", "statement", "contract", "form")
    note_terms = ("note", "notes", "study guide", "outline", "plan", "summary", "brief", "prep")
    code_terms = ("repo", "github", "code", "script", "source")

    if kind == "pdf" or any(term in text_value for term in official_terms):
        route.update(
            {
                "recommended_home": "Paperless",
                "secondary_home": "Nextcloud" if category != "personal_lifeadmin" else "Nextcloud private",
                "reason": "PDFs and official documents gain the most from Paperless OCR, document dates, tags, and long-term retrieval.",
            }
        )
    elif kind == "document" or any(term in text_value for term in note_terms):
        route.update(
            {
                "recommended_home": "Docmost",
                "secondary_home": "Nextcloud",
                "reason": "Editable notes, plans, and study/work knowledge are more useful as wiki pages than as static files.",
            }
        )
    elif kind in {"spreadsheet", "presentation"}:
        route.update(
            {
                "recommended_home": "Nextcloud",
                "secondary_home": "Docmost reference",
                "reason": "Structured files and slide decks are safest as files first; Jarvis can link or summarize them into Docmost later.",
            }
        )
    elif kind in {"image", "video"}:
        route.update(
            {
                "recommended_home": "Immich" if category in {"hobbies", "personal_lifeadmin"} else "Nextcloud",
                "secondary_home": "Nextcloud",
                "reason": "Photos and videos are best browsed in Immich when personal/hobby oriented; work or education media can stay as project files in Nextcloud.",
            }
        )

    if category == "professional_work" and any(term in text_value for term in code_terms):
        route.update(
            {
                "recommended_home": "GitHub reference",
                "secondary_home": "Nextcloud",
                "reason": "Code should stay in GitHub for now; Jarvis should store repo, commit, task, and evidence links rather than self-hosting Git.",
            }
        )
    elif category == "research" and route["recommended_home"] == "Nextcloud":
        route.update(
            {
                "secondary_home": "Docmost",
                "reason": "Research files can live in Nextcloud, with summaries and interpretation linked from Docmost. Zotero is intentionally not part of the default route.",
            }
        )
    elif category == "personal_lifeadmin" and route["recommended_home"] == "Nextcloud":
        route.update(
            {
                "recommended_home": "Nextcloud private",
                "reason": "Sensitive personal files should default to private file storage, while official PDFs still route to Paperless.",
            }
        )
    elif category == "hobbies" and "media" in text_value and kind not in {"image", "video"}:
        route.update(
            {
                "recommended_home": "media folders",
                "secondary_home": "Nextcloud",
                "reason": "Media automation assets are best kept near the media stack, with Jarvis indexing links and status.",
            }
        )
    return route


def drive_item_pathway(item: dict):
    action = item.get("migration_action") or item.get("suggested_action") or "needs_review"
    if action == "keep_in_google":
        next_step = "Keep this in Google for now and let Jarvis retain the source link and metadata."
    elif action == "archive":
        next_step = "Review manually before marking for archive; no deletion should happen until a verified homelab copy exists or you explicitly decide it is disposable."
    elif action == "copy_to_homelab":
        next_step = f"After approval and broader Drive export scope, copy/export to a staging area, import into {item.get('recommended_home')}, then verify before changing Google."
    else:
        next_step = "Review the item or folder contents before choosing a destination."
    return [
        {"step": "metadata_review", "status": "available_now", "description": "Jarvis can classify from Drive metadata and show the proposed home without downloading files."},
        {"step": "approve_batch", "status": "future_approval_required", "description": "You approve a category/action batch before any export, copy, import, archive, or delete."},
        {"step": "copy_to_staging", "status": "blocked_by_scope", "description": "Requires broader Drive read/export scope; current scope is metadata-only."},
        {"step": "import_to_home", "status": "blocked_by_prior_step", "description": next_step},
        {"step": "verify_and_link", "status": "blocked_by_prior_step", "description": "Jarvis records checks, destination links, and audit events after import."},
    ]


def drive_category_label(category: str):
    labels = {
        "professional_education": "Professional Education",
        "professional_work": "Professional Work",
        "hobbies": "Hobbies",
        "research": "Research",
        "personal_lifeadmin": "Personal / Life Admin",
        "needs_review": "Needs Review",
    }
    return labels.get(category, category.replace("_", " ").title())


def drive_kind(item: dict):
    mime = (item.get("mime_type") or "").lower()
    if "folder" in mime:
        return "folder"
    if "document" in mime:
        return "document"
    if "spreadsheet" in mime:
        return "spreadsheet"
    if "presentation" in mime:
        return "presentation"
    if "pdf" in mime:
        return "pdf"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    return "file"


def build_drive_inventory(files: list[dict]):
    by_type: dict[str, int] = {}
    by_destination: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_action: dict[str, int] = {}
    items = []
    for item in files:
        kind = drive_kind(item)
        category = drive_life_category_for(item)
        action = drive_migration_action_for(item, category)
        route = drive_route_for(item, category, kind)
        destination = route["recommended_home"]
        planned_item = {
            "id": item.get("id"),
            "name": item.get("name"),
            "kind": kind,
            "mime_type": item.get("mime_type"),
                "modified_time": item.get("modified_time"),
                "web_view_link": item.get("web_view_link"),
                "parents": item.get("parents") or [],
                "google_drive_folder_path": item.get("google_drive_folder_path"),
                "google_drive_path": item.get("google_drive_path"),
                "suggested_destination": destination,
            "recommended_home": route.get("recommended_home"),
            "secondary_home": route.get("secondary_home"),
            "relationship_home": route.get("relationship_home"),
            "routing_reason": route.get("reason"),
            "life_category": category,
            "life_category_label": drive_category_label(category),
            "migration_action": action,
            "suggested_action": action,
        }
        planned_item["migration_pathway"] = drive_item_pathway(planned_item)
        by_type[kind] = by_type.get(kind, 0) + 1
        by_destination[destination] = by_destination.get(destination, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1
        items.append(planned_item)
    return {
        "summary": f"{len(items)} Drive items inventoried",
        "total": len(items),
        "by_type": by_type,
        "by_destination": by_destination,
        "by_category": by_category,
        "by_action": by_action,
        "items": items,
    }


def build_drive_migration_plan(inventory: dict):
    steps = [
        {"phase": 1, "title": "Review metadata plan", "action": "Confirm category, action, recommended home, and reason for each item. Current Google scope only allows metadata."},
        {"phase": 2, "title": "Approve a migration batch", "action": "Pick a category/action batch, such as Professional Education items marked copy_to_homelab. Approval is required before any file access."},
        {"phase": 3, "title": "Request temporary export scope", "action": "Only after approval, request the minimum Drive read/export scope needed for that specific batch."},
        {"phase": 4, "title": "Copy to staging", "action": "Export/download to a homelab staging folder under the planned category without deleting or modifying Google originals."},
        {"phase": 5, "title": "Import into destination service", "action": "Route docs/notes to Docmost, official PDFs to Paperless, general files to Nextcloud, photos/videos to Immich, code references to GitHub links, and media assets to media folders."},
        {"phase": 6, "title": "Verify and index", "action": "Record counts, destination links, checks, and audit events in Jarvis Core/Postgres."},
        {"phase": 7, "title": "Retire Google copies later", "action": "Archive or delete in Google only after a separate explicit approval and verified homelab backup."},
    ]
    batches = []
    categories = ["professional_education", "professional_work", "hobbies", "research", "personal_lifeadmin", "needs_review"]
    actions = ["copy_to_homelab", "keep_in_google", "archive", "needs_review"]
    items = inventory.get("items") or []
    for category in categories:
        category_items = [item for item in items if item.get("life_category") == category]
        if not category_items:
            continue
        action_counts = {action: len([item for item in category_items if item.get("migration_action") == action]) for action in actions}
        batches.append(
            {
                "category": category,
                "category_label": drive_category_label(category),
                "count": len(category_items),
                "actions": {key: value for key, value in action_counts.items() if value},
                "destinations": sorted({item.get("suggested_destination") for item in category_items if item.get("suggested_destination")}),
                "sample_items": category_items[:5],
                "approval_required_before_download": True,
                "current_scope_allows_copy": False,
            }
        )
    return {
        "summary": "Metadata-only migration plan created. No files were downloaded or modified.",
        "destination_map": {
            "professional_education": ["Docmost", "Paperless", "Nextcloud"],
            "professional_work": ["Docmost", "Paperless", "Nextcloud", "GitHub links", "portfolio evidence"],
            "research": ["Docmost", "Paperless", "Nextcloud"],
            "hobbies": ["Nextcloud", "Immich", "media folders", "Docmost"],
            "personal_lifeadmin": ["Paperless", "Nextcloud private", "Docmost"],
        },
        "actions": {
            "copy_to_homelab": "Good candidates to export/copy into homelab storage after approval.",
            "keep_in_google": "Google-native or integration-specific items that may be better left in Google for now.",
            "archive": "Likely stale, duplicate, or old items to review before migration.",
            "needs_review": "Folders or ambiguous files that need a human decision before routing.",
        },
        "pathway": steps,
        "categories": [drive_category_label(category) for category in categories],
        "steps": steps,
        "suggested_batches": batches,
    }


def render_evidence_packet_summary(project, tasks, evidence, maintenance, calendar_events, commits=None, documents=None):
    lines = []
    if project:
        lines.append(f"Project: {project.name}")
        if project.goal:
            lines.append(f"Goal: {project.goal}")
    lines.append(f"Tasks included: {len(tasks)}")
    for task in tasks[:8]:
        lines.append(f"- {task.status}: {task.title}")
    lines.append(f"Evidence records included: {len(evidence)}")
    for item in evidence[:8]:
        lines.append(f"- {item.evidence_type}: {item.title}")
    lines.append(f"Calendar events included: {len(calendar_events)}")
    for event in calendar_events[:6]:
        lines.append(f"- {event.title} at {event.starts_at}")
    if maintenance:
        lines.append(f"Maintenance records included: {len(maintenance)}")
    commits = commits or []
    lines.append(f"Git commits included: {len([item for item in commits if item.get('sha')])}")
    for commit in commits[:6]:
        if commit.get("sha"):
            lines.append(f"- {commit.get('short_sha')}: {commit.get('subject')}")
    doc_items = (documents or {}).get("items") if isinstance(documents, dict) else []
    lines.append(f"Google document references included: {len(doc_items or [])}")
    return "\n".join(lines)


def http_health_check(name: str, url: str, headers: dict | None = None):
    try:
        request = urllib.request.Request(url, method="GET")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        token = settings.codex_worker_token or settings.token
        if "codex-worker" in name and token:
            request.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(4096).decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "")
            body = {}
            if "json" in content_type or raw.lstrip().startswith(("{", "[")):
                body = json.loads(raw or "{}")
            ok = response.status < 400 and body.get("ok") is not False
            summary = body.get("service") or body.get("ok") if isinstance(body, dict) else None
            if summary is None:
                summary = f"http {response.status}"
            return {"name": name, "ok": ok, "status": response.status, "summary": summary, "content_type": content_type}
    except Exception as exc:
        return {"name": name, "ok": False, "status": None, "error": str(exc)[:240]}


def drive_destination_services():
    public_base = settings.homelab_public_base_url.rstrip("/")
    public_host = urllib.parse.urlparse(public_base).netloc or "100.79.132.39"
    checks = {
        "paperless": http_health_check("paperless", "http://paperless:8000"),
        "nextcloud": http_health_check("nextcloud", "http://nextcloud/status.php", {"Host": public_host}),
        "docmost": http_health_check("docmost", "http://docmost:3000"),
        "immich": http_health_check("immich", "http://immich-server:2283/api/server/ping"),
    }
    return {
        "paperless": {
            "label": "Paperless",
            "ready": checks["paperless"].get("ok") is True,
            "check": checks["paperless"],
            "best_for": "PDFs, receipts, bills, forms, transcripts, contracts, and other official/OCR documents.",
            "import_path": "approval_required_import_to_paperless_consume_or_api",
        },
        "nextcloud": {
            "label": "Nextcloud",
            "ready": checks["nextcloud"].get("ok") is True,
            "check": checks["nextcloud"],
            "best_for": "General files, folders, spreadsheets, presentations, and private file storage.",
            "import_path": "approval_required_copy_to_nextcloud_storage_or_webdav",
        },
        "docmost": {
            "label": "Docmost",
            "ready": checks["docmost"].get("ok") is True,
            "check": checks["docmost"],
            "best_for": "Editable knowledge, notes, study guides, interview prep, plans, and summaries.",
            "import_path": "approval_required_create_docmost_page_or_attach_file",
        },
        "immich": {
            "label": "Immich",
            "ready": checks["immich"].get("ok") is True,
            "check": checks["immich"],
            "best_for": "Personal photos and videos.",
            "import_path": "approval_required_immich_upload",
        },
        "media_folders": {
            "label": "Media folders",
            "ready": True,
            "check": {"ok": True, "summary": "filesystem route"},
            "best_for": "Media automation assets that should live beside the media stack.",
            "import_path": "approval_required_copy_to_media_folder",
        },
        "github_reference": {
            "label": "GitHub reference",
            "ready": True,
            "check": {"ok": True, "summary": "reference-only route"},
            "best_for": "Code references, repo URLs, commits, and portfolio evidence links.",
            "import_path": "record_reference_no_file_import",
        },
        "needs_review": {
            "label": "Needs Review",
            "ready": False,
            "check": {"ok": False, "summary": "manual decision required"},
            "best_for": "Ambiguous files or folders that need a human decision.",
            "import_path": "manual_review_required",
        },
    }


def destination_service_key(destination: str):
    lowered = (destination or "").lower()
    if "paperless" in lowered:
        return "paperless"
    if "docmost" in lowered:
        return "docmost"
    if "nextcloud" in lowered:
        return "nextcloud"
    if "immich" in lowered:
        return "immich"
    if "media" in lowered:
        return "media_folders"
    if "github" in lowered:
        return "github_reference"
    return "needs_review"


def gmail_classification_batches(summary: dict, max_results: int):
    buckets: dict[str, set[str]] = {
        "Jarvis/Newsletters": set(),
        "Jarvis/Needs Reply": set(),
        "Jarvis/Needs Review": set(),
        "Jarvis/Medical School": set(),
        "Jarvis/Admissions": set(),
        "Jarvis/Finance": set(),
        "Jarvis/Education": set(),
        "Jarvis/Work": set(),
    }

    def total_selected():
        return len({mid for values in buckets.values() for mid in values})

    def add(label: str, message: dict):
        message_id = message.get("id")
        if message_id and total_selected() < max_results:
            buckets.setdefault(label, set()).add(message_id)

    for message in summary.get("likely_newsletters") or []:
        add("Jarvis/Newsletters", message)
    for message in summary.get("needs_reply") or []:
        add("Jarvis/Needs Reply", message)
    for message in summary.get("old_unread") or []:
        add("Jarvis/Needs Review", message)
    for message in summary.get("medical_school") or []:
        add("Jarvis/Medical School", message)
        add("Jarvis/Education", message)
    for message in summary.get("admissions") or []:
        add("Jarvis/Admissions", message)
    for message in summary.get("finance_receipts") or []:
        add("Jarvis/Finance", message)

    keyword_labels = [
        ("Jarvis/Medical School", ("medical school", "med school", "enmed", "mcat", "aacom", "aamc", "osteopathic", "kcu", "lecom", "pcom")),
        ("Jarvis/Admissions", ("admissions", "interview", "application", "supplemental", "applicant", "invite")),
        ("Jarvis/Finance", ("bank", "invoice", "receipt", "statement", "payment", "tax", "tuition", "bill")),
        ("Jarvis/Education", ("university", "college", "class", "course", "student", "school", "enmed", "ufl", "edu")),
        ("Jarvis/Work", ("project", "meeting", "interview", "application", "deadline", "team", "work")),
    ]
    seen_messages = []
    for key in ("needs_reply", "old_unread", "likely_newsletters", "medical_school", "admissions", "finance_receipts"):
        seen_messages.extend(summary.get(key) or [])
    for message in seen_messages:
        text_value = " ".join(str(message.get(key, "")) for key in ("from", "subject", "snippet")).lower()
        for label, keywords in keyword_labels:
            if any(word in text_value for word in keywords):
                add(label, message)

    return [
        {"label_names": [label], "message_ids": sorted(message_ids), "remove_label_ids": []}
        for label, message_ids in buckets.items()
        if message_ids
    ]


def smart_destination_next_action(manifest: dict, service: dict):
    if not service.get("ready"):
        return f"Review or initialize {service.get('label', 'the destination')} before import."
    label = service.get("label")
    if label == "Paperless":
        return "Ready for an approval-gated Paperless import from the staged file."
    if label == "Docmost":
        return "Ready for Docmost setup/import planning; create a page or attach the staged file after approval."
    if label == "Nextcloud":
        return "Ready for an approval-gated copy into the chosen Nextcloud category folder."
    if label == "Immich":
        return "Ready for an approval-gated Immich upload if this is personal/hobby media."
    return "Ready for a destination-specific approval step."


def smart_destination_reason(manifest: dict, service: dict):
    return f"{manifest.get('name') or manifest.get('file_id')} is staged for {service.get('label')} because {service.get('best_for')}"


MEDIA_AUTOMATION_SERVICES = (
    ("media:prowlarr", "Prowlarr", 9696),
    ("media:bazarr", "Bazarr", 6767),
    ("media:sonarr", "Sonarr", 8989),
    ("media:radarr", "Radarr", 7878),
    ("media:lidarr", "Lidarr", 8686),
    ("media:readarr", "Readarr", 8787),
    ("media:qbittorrent", "qBittorrent", 8097),
)


def media_automation_checks():
    check_base = settings.media_automation_internal_base_url.rstrip("/")
    public_base = settings.homelab_public_base_url.rstrip("/")
    checks = []
    for name, label, port in MEDIA_AUTOMATION_SERVICES:
        check_url = f"{check_base}:{port}/"
        display_url = f"{public_base}:{port}/"
        try:
            request = urllib.request.Request(check_url, method="GET")
            with urllib.request.urlopen(request, timeout=8) as response:
                checks.append({"name": name, "label": label, "ok": response.status < 500, "optional": True, "status": response.status, "url": display_url, "summary": "reachable"})
        except urllib.error.HTTPError as exc:
            checks.append({"name": name, "label": label, "ok": exc.code < 500, "optional": True, "status": exc.code, "url": display_url, "summary": "reachable_auth_required" if exc.code in {401, 403} else "http_error"})
        except Exception as exc:
            checks.append({"name": name, "label": label, "ok": False, "optional": True, "status": None, "url": display_url, "check_url": check_url, "error": str(exc)[:240], "summary": "Optional media automation service is not reachable yet."})
    return checks


def call_google_briefing(kind: str):
    try:
        return call_google_tools("/briefing/build", {"kind": kind}, timeout=120)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:240], "text": "Google briefing is unavailable."}


def call_google_tools(path: str, payload: dict, timeout: int = 90):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = settings.google_tools_token or settings.token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(settings.google_tools_url.rstrip("/") + path, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"google_tools_http_{exc.code}: {detail[:500]}") from exc


def render_daily_brief_text(payload: dict):
    lines = ["Morning briefing" if payload["kind"] == "morning" else "Evening recap", ""]
    google_text = ((payload.get("google") or {}).get("text") or "").strip()
    if google_text:
        lines.extend(["Google services:", google_text, ""])
    if payload["pending_approvals"]:
        lines.append("Pending approvals:")
        for approval in payload["pending_approvals"]:
            action = approval.get("action") or {}
            lines.append(f"- {action.get('tool_name')}: {approval.get('reason')}")
        lines.append("")
    if payload["tasks_due_soon"]:
        lines.append("Core tasks:")
        for task in payload["tasks_due_soon"]:
            due = f" due {task['due_at']}" if task.get("due_at") else ""
            lines.append(f"- {task['title']}{due}")
        lines.append("")
    if payload["open_maintenance"]:
        lines.append("Homelab maintenance:")
        for item in payload["open_maintenance"]:
            lines.append(f"- {item['service_name']}: {item['summary']}")
        lines.append("")
    if payload["recent_evidence"]:
        lines.append("Recent evidence:")
        for item in payload["recent_evidence"]:
            lines.append(f"- {item['title']}")
    return "\n".join(lines).strip()


def infer_service_name(text: str):
    lowered = text.lower()
    for service in ("jarvis", "google", "postgres", "redis", "gluetun", "open_webui", "ollama", "media"):
        if service in lowered:
            return service
    return "homelab"


def json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def model_profile_status(profile_name: str):
    profile = configured_model_profile(profile_name)
    return {
        "provider": profile["provider"],
        "model": profile["model"],
        "base_url_configured": bool(profile["base_url"]),
        "api_key_configured": bool(profile["api_key"]),
        "configured": bool(profile["base_url"] and profile["api_key"]),
    }


def configured_model_profile(profile_name: str):
    if profile_name == "deep":
        return {
            "provider": settings.deep_llm_provider,
            "model": settings.deep_llm_model,
            "base_url": settings.deep_llm_base_url.rstrip("/"),
            "api_key": settings.deep_llm_api_key,
        }
    if profile_name == "vision":
        return {
            "provider": settings.vision_llm_provider,
            "model": settings.vision_llm_model,
            "base_url": settings.vision_llm_base_url.rstrip("/"),
            "api_key": settings.vision_llm_api_key,
        }
    return {
        "provider": settings.fast_llm_provider,
        "model": settings.fast_llm_model,
        "base_url": settings.fast_llm_base_url.rstrip("/"),
        "api_key": settings.fast_llm_api_key,
    }


def call_openai_compatible_model(profile: dict, prompt: str, system: str | None, images: list[str], max_tokens: int, temperature: float):
    if profile["provider"] != "external_openai_compatible":
        raise RuntimeError(f"unsupported_model_provider:{profile['provider']}")
    if not profile["base_url"] or not profile["api_key"]:
        raise RuntimeError("model_profile_missing_base_url_or_api_key")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    if images:
        content = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": image}} for image in images[:4])
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})
    body = json.dumps(
        {
            "model": profile["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        profile["base_url"] + "/chat/completions",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {profile['api_key']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"model_http_{exc.code}: {detail[:500]}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("model_response_missing_choices")
    message = choices[0].get("message") or {}
    content = message.get("content") or message.get("reasoning_content") or choices[0].get("text") or ""
    content = str(content).strip()
    return {"content": content, "raw_usage": data.get("usage")}


def audit(db: Session, event_type: str, actor: str, correlation_id: str, causation_id: str | None, payload: dict):
    db.add(
        AuditEventRecord(
            id=new_id("audit"),
            event_type=event_type,
            schema_version=1,
            source="jarvis-core",
            actor=actor,
            correlation_id=correlation_id,
            causation_id=causation_id,
            sensitivity="internal",
            payload=redact(payload),
        )
    )


def audit_for_action(db: Session, event_type: str, action: ProposedActionRecord, actor: str, payload: dict):
    request = db.get(RequestRecord, action.request_id)
    audit(db, event_type, actor, request.correlation_id, action.id, payload)


def request_response(db: Session, record: RequestRecord):
    intents = db.query(StructuredIntentRecord).filter_by(request_id=record.id).all()
    actions = db.query(ProposedActionRecord).filter_by(request_id=record.id).all()
    return {
        "request": {
            "id": record.id,
            "status": record.status,
            "source": record.source,
            "raw_text": record.raw_text,
            "correlation_id": record.correlation_id,
            "idempotency_key": record.idempotency_key,
            "created_at": record.created_at,
        },
        "intents": [intent_response(item) for item in intents],
        "actions": [action_response(db, item) for item in actions],
    }


def intent_response(intent: StructuredIntentRecord):
    return {
        "id": intent.id,
        "intent_type": intent.intent_type,
        "confidence": intent.confidence,
        "payload": intent.payload,
        "requires_clarification": intent.requires_clarification,
        "clarification_question": intent.clarification_question,
    }


def action_response(db: Session, action: ProposedActionRecord):
    approval = db.query(ApprovalRequestRecord).filter_by(proposed_action_id=action.id).first()
    return {
        "id": action.id,
        "tool_name": action.tool_name,
        "tool_version": action.tool_version,
        "risk_level": action.risk_level,
        "status": action.status,
        "arguments": action.arguments,
        "preview": action.preview,
        "requires_approval": action.requires_approval,
        "approval": approval_response(db, approval) if approval else None,
    }


def approval_response(db: Session, approval: ApprovalRequestRecord | None):
    if not approval:
        return None
    action = db.get(ProposedActionRecord, approval.proposed_action_id)
    return {
        "id": approval.id,
        "status": approval.status,
        "reason": approval.reason,
        "decided_by": approval.decided_by,
        "decided_at": approval.decided_at,
        "action": {
            "id": action.id,
            "tool_name": action.tool_name,
            "risk_level": action.risk_level,
            "preview": action.preview,
        } if action else None,
    }


def execution_response(db: Session, attempt: ExecutionAttemptRecord):
    result = db.query(ExecutionResultRecord).filter_by(execution_attempt_id=attempt.id).first()
    verification = db.query(VerificationResultRecord).filter_by(execution_result_id=result.id).first() if result else None
    return {
        "id": attempt.id,
        "action_id": attempt.proposed_action_id,
        "status": attempt.status,
        "safe_summary": attempt.safe_summary,
        "result": result.payload if result else None,
        "verification": {"status": verification.status, "payload": verification.payload} if verification else None,
    }


def tool_response(tool: ToolDefinitionRecord):
    return {
        "name": tool.name,
        "version": tool.version,
        "description": tool.description,
        "risk_level": tool.risk_level,
        "required_permissions": tool.required_permissions,
        "enabled": tool.enabled,
    }


def project_response(project: ProjectRecord):
    return {
        "id": project.id,
        "name": project.name,
        "area": project.area,
        "status": project.status,
        "goal": project.goal,
        "priority": project.priority,
        "next_action": project.next_action,
        "notes": project.notes,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def task_response(task: TaskRecord):
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "due_at": task.due_at,
        "estimated_minutes": task.estimated_minutes,
        "effort_level": task.effort_level,
        "source": task.source,
        "tags": task.tags,
        "completed_at": task.completed_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "score": task_score(task),
    }


def evidence_response(evidence: EvidenceRecord):
    return {
        "id": evidence.id,
        "project_id": evidence.project_id,
        "title": evidence.title,
        "evidence_type": evidence.evidence_type,
        "uri": evidence.uri,
        "summary": evidence.summary,
        "tags": evidence.tags,
        "captured_at": evidence.captured_at,
    }


def maintenance_response(record: MaintenanceRecord):
    return {
        "id": record.id,
        "service_name": record.service_name,
        "record_type": record.record_type,
        "status": record.status,
        "summary": record.summary,
        "details": record.details,
        "next_check_at": record.next_check_at,
        "resolved_at": record.resolved_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def calendar_event_response(event: CalendarEventRecord):
    return {
        "id": event.id,
        "title": event.title,
        "calendar_target": event.calendar_target,
        "timezone": event.timezone,
        "starts_at": event.starts_at.isoformat() if event.starts_at else None,
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
    }


def task_score(task: TaskRecord) -> float:
    score = max(0, 6 - int(task.priority or 3)) * 10
    if task.due_at:
        hours = max(0.0, (task.due_at - now_utc()).total_seconds() / 3600)
        score += max(0, 48 - hours)
    if task.estimated_minutes and task.estimated_minutes <= 30:
        score += 5
    return round(score, 2)

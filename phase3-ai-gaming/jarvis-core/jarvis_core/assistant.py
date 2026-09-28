"""ai-orchestrator compatible request API backed by jarvis-core storage.

Actions planned here are ordinary ProposedActionRecords (tool_name
"assistant.<capability>"), so approval-gated ones land in the same approval
queue as every other Jarvis action.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import router
from .contracts import RiskLevel
from .database import SessionLocal
from .models import ApprovalRequestRecord, ProposedActionRecord, RequestRecord

TOOL_PREFIX = "assistant."
STATE_WINDOW = 200


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def is_assistant_action(action: ProposedActionRecord) -> bool:
    return action.tool_name.startswith(TOOL_PREFIX)


def load_router_state():
    """Recent assistant actions in the shape the router's artifact lookups expect."""
    db = SessionLocal()
    try:
        records = (
            db.query(ProposedActionRecord)
            .filter(ProposedActionRecord.tool_name.like(TOOL_PREFIX + "%"))
            .order_by(ProposedActionRecord.created_at.desc())
            .limit(STATE_WINDOW)
            .all()
        )
        requests, actions = {}, {}
        for record in records:
            data = record.arguments or {}
            actions[record.id] = data.get("action") or {}
            requests.setdefault(record.request_id, {"original": data.get("original") or {}})
        return {"requests": requests, "actions": actions}
    finally:
        db.close()


router.STATE_LOADER = load_router_state


def action_dict(record: ProposedActionRecord) -> dict:
    return dict((record.arguments or {}).get("action") or {})


def save_action_dict(record: ProposedActionRecord, action: dict):
    # Reassign so SQLAlchemy notices the JSON change.
    record.arguments = {**(record.arguments or {}), "action": action}
    record.status = action.get("status") or record.status


def plan_request(db: Session, payload: dict, actor: str, correlation_id: str):
    text = router.request_text(payload)
    request_id = _id("req")
    db.add(
        RequestRecord(
            id=request_id,
            user_id=actor,
            source=str(payload.get("source") or "jarvis-assistant"),
            raw_text=text,
            status="planned",
            correlation_id=correlation_id,
        )
    )
    db.flush()

    subrequests = router.split_multi_command_request(payload)
    actions, routes, capabilities = [], [], []
    for index, subrequest in enumerate(subrequests or [text]):
        sub_payload = router.payload_for_subrequest(payload, subrequest) if len(subrequests) > 1 else payload
        capability, route = router.route_request(sub_payload)
        action = router.make_action(request_id, sub_payload, capability)
        action_id = _id("act")
        action.update({"action_id": action_id, "sequence": index + 1, "subrequest": subrequest})
        gated = not action["permissions"]["may_execute"]
        db.add(
            ProposedActionRecord(
                id=action_id,
                request_id=request_id,
                tool_name=TOOL_PREFIX + capability["capability"],
                tool_version="1.0",
                risk_level=(RiskLevel.EXTERNAL_WRITE if gated else RiskLevel.READ_ONLY).value,
                status=action["status"],
                arguments={"action": action, "original": payload},
                preview={"summary": f"{capability['capability']}: {subrequest[:200]}", "changes": [capability.get("description", "")]},
                requires_approval=gated,
            )
        )
        if gated:
            db.flush()
            db.add(
                ApprovalRequestRecord(
                    id=_id("appr"),
                    proposed_action_id=action_id,
                    status="pending",
                    reason=f"{capability['capability']} requires explicit approval.",
                )
            )
        actions.append(action)
        routes.append({"sequence": index + 1, "subrequest": subrequest, **route})
        capabilities.append(capability)

    primary = capabilities[0]
    request = {
        "request_id": request_id,
        "status": "planned",
        "created_at": router.now(),
        "capability": primary["capability"] if len(actions) == 1 else "multi_action",
        "worker": primary["worker"] if len(actions) == 1 else "jarvis_core",
        "summary": f"Planned {len(actions)} Jarvis action(s).",
        "route": routes[0] if len(actions) == 1 else {"router": "multi_command", "steps": routes},
        "original": payload,
        "next_actions": [
            {
                "action_id": item["action_id"],
                "tool": item["tool"],
                "authorization": "approved" if item["status"] == "approved" else "approval_required",
            }
            for item in actions
        ],
    }
    return {"ok": True, "request": request, "actions": actions}


def get_request(db: Session, request_id: str):
    record = db.get(RequestRecord, request_id)
    if not record:
        return None
    records = db.query(ProposedActionRecord).filter_by(request_id=request_id).all()
    actions = [{**action_dict(item), "status": item.status} for item in records if is_assistant_action(item)]
    request = {"request_id": record.id, "status": record.status, "created_at": record.created_at, "summary": record.raw_text}
    return {"ok": True, "request": request, "actions": actions}


def approve(db: Session, record: ProposedActionRecord, decided_by: str):
    approval = db.query(ApprovalRequestRecord).filter_by(proposed_action_id=record.id).first()
    if approval and approval.status == "pending":
        approval.status = "approved"
        approval.decided_by = decided_by
        approval.decided_at = datetime.now(timezone.utc)
    action = action_dict(record)
    action["status"] = "approved"
    action["approved_at"] = router.now()
    action["permissions"] = {**action.get("permissions", {}), "may_execute": True}
    save_action_dict(record, action)
    return action


def run(db: Session, record: ProposedActionRecord) -> dict:
    """Execute through the router and update request status like ai-orchestrator did."""
    action = action_dict(record)
    action.setdefault("permissions", {})["may_execute"] = True
    result = router.execute_action(action)
    action["result"] = result
    action["status"] = result["status"]
    save_action_dict(record, action)
    db.flush()

    siblings = [action_dict(item) for item in db.query(ProposedActionRecord).filter_by(request_id=record.request_id).all()]
    statuses = [item.get("status") for item in siblings]
    request = db.get(RequestRecord, record.request_id)
    if "awaiting_approval" in statuses:
        request.status = "partial_approval_required"
    elif any(status in {"approved", "planned"} for status in statuses):
        request.status = "partial_completed"
    elif all(status == "completed" for status in statuses):
        request.status = "completed"
    else:
        request.status = result["status"]
    return action


def capabilities():
    return {"ok": True, "capabilities": router.CAPABILITIES}

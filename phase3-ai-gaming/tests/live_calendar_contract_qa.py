#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
import uuid
from datetime import datetime, timedelta


BASE_URL = os.environ.get("AI_ORCHESTRATOR_URL", "http://127.0.0.1:8095").rstrip("/")
TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", "")


def api(method, path, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def submit(message, chat_id, execute=True, explicit_capability=True, include_plan=False):
    payload = {
        "inputs": {
            "request": message,
            "source": "calendar-contract-live-qa",
            "telegram_chat_id": chat_id,
            "conversation_context": [],
        },
        "permissions": {"may_execute": False, "may_publish": False},
    }
    if explicit_capability:
        payload["capability"] = "manage_calendar"
    planned = api("POST", "/requests", payload)
    action = planned["actions"][0]
    if execute and action["permissions"]["may_execute"]:
        action = api("POST", f"/actions/{action['action_id']}/execute")["action"]
    return (planned, action) if include_plan else action


def show(label, action):
    contract = action.get("inputs", {}).get("calendar_contract")
    result = action.get("result") or {}
    verified_event_id = None
    for artifact in result.get("artifacts") or []:
        item = artifact.get("item")
        if isinstance(item, dict) and item.get("id"):
            verified_event_id = item["id"]
    print(json.dumps({
        "label": label,
        "source": action.get("inputs", {}).get("calendar_contract_source"),
        "contract_error": action.get("inputs", {}).get("calendar_contract_error"),
        "contract": contract,
        "requires_approval": action.get("requires_approval"),
        "status": action.get("status"),
        "result_status": result.get("status"),
        "verified_event_id": verified_event_id,
    }, separators=(",", ":")))
    return contract or {}, result


def main():
    if not TOKEN:
        raise RuntimeError("AI_ORCHESTRATOR_TOKEN is required")
    suffix = uuid.uuid4().hex[:8]
    title = f"Jarvis Contract QA {suffix}"

    if os.environ.get("QA_MANAGER_ROUTING_ONLY") == "1":
        chat_id = f"qa-manager-{suffix}"
        create_plan, create_action = submit(
            f"Create a calendar event tomorrow at 8 PM titled {title} for 30 minutes.",
            chat_id,
            explicit_capability=False,
            include_plan=True,
        )
        create, create_result = show("manager_create", create_action)
        assert create_plan["request"]["capability"] == "manage_calendar"
        assert create_plan["request"]["route"].get("model") == "nemotron-3-super-120b-a12b"
        assert create.get("title") == title and create_result.get("status") == "completed"

        move_plan, move_action = submit(
            "Actually make it one hour later.",
            chat_id,
            explicit_capability=False,
            include_plan=True,
        )
        move, move_result = show("manager_contextual_move", move_action)
        print(json.dumps({"label": "manager_contextual_move_route", "route": move_plan["request"]["route"]}, separators=(",", ":")))
        assert move_plan["request"]["capability"] == "manage_calendar"
        assert move_plan["request"]["route"].get("model") == "nemotron-3-super-120b-a12b"
        assert move.get("operation") == "reschedule" and move_result.get("status") == "completed"

        delete_plan, delete_action = submit(
            "Remove it.",
            chat_id,
            explicit_capability=False,
            include_plan=True,
        )
        delete, delete_result = show("manager_contextual_delete", delete_action)
        print(json.dumps({"label": "manager_contextual_delete_route", "route": delete_plan["request"]["route"]}, separators=(",", ":")))
        assert delete_plan["request"]["capability"] == "manage_calendar"
        assert delete.get("target_event_id") == move.get("target_event_id")
        assert delete_result.get("status") == "completed"
        print(json.dumps({"ok": True, "nemotron_manager_routed_all": True}, separators=(",", ":")))
        return

    if os.environ.get("QA_FOLLOWUP_ONLY") == "1":
        chat_id = f"qa-followup-{suffix}"
        create, create_result = show(
            "create_followup_fixture",
            submit(f"Create a calendar event tomorrow at 8 PM titled {title} for 30 minutes.", chat_id),
        )
        assert create.get("title") == title and create_result.get("status") == "completed"
        move, move_result = show(
            "relative_reschedule",
            submit("Can you actually move that event by 1 hour later?", chat_id),
        )
        assert move.get("operation") == "reschedule" and move.get("target_event_id")
        assert move_result.get("status") == "completed"
        create_start = datetime.fromisoformat(create["start"].replace("Z", "+00:00"))
        move_start = datetime.fromisoformat(move["start"].replace("Z", "+00:00"))
        assert move_start == create_start + timedelta(hours=1)
        delete, delete_result = show("followup_cleanup", submit("Delete that event now.", chat_id))
        assert delete.get("target_event_id") == move.get("target_event_id")
        assert delete_result.get("status") == "completed"
        print(json.dumps({"ok": True, "title_preserved": True, "relative_shift_hours": 1}, separators=(",", ":")))
        return

    if os.environ.get("QA_APPROVAL_ONLY") == "1":
        action = submit(
            f"Create a 30-minute calendar event titled {title} Invite Test at 11 PM on August 4, 2026 and invite qa@example.com.",
            f"qa-approval-{suffix}",
            execute=False,
        )
        approval, _ = show("attendee_approval", action)
        assert approval.get("attendees") == ["qa@example.com"]
        assert action.get("requires_approval") is True and action.get("status") == "awaiting_approval"
        print(json.dumps({"ok": True, "approval_executed": False}, separators=(",", ":")))
        return

    ambiguous, ambiguous_result = show("ambiguous_delete", submit("Delete it now.", f"qa-empty-{suffix}"))
    assert ambiguous.get("requires_clarification") is True
    assert ambiguous_result.get("status") == "clarification_required"

    chat_id = f"qa-calendar-{suffix}"
    create, create_result = show(
        "create",
        submit(f"Create a calendar event titled {title} at 9:15 PM on August 4, 2026 for 30 minutes.", chat_id),
    )
    assert create.get("operation") == "create" and create.get("title") == title
    assert create_result.get("status") == "completed"

    listing, list_result = show(
        "list",
        submit("List my calendar events between 9:15 PM and 9:45 PM on August 4, 2026.", chat_id),
    )
    assert listing.get("operation") == "list" and list_result.get("status") == "completed"

    move, move_result = show(
        "reschedule",
        submit("Move that event to 10:15 PM on August 4, 2026 for 30 minutes.", chat_id),
    )
    assert move.get("operation") == "reschedule" and move.get("target_event_id")
    assert move_result.get("status") == "completed"

    delete, delete_result = show("delete", submit("Delete that event now.", chat_id))
    assert delete.get("operation") == "delete" and delete.get("target_event_id")
    assert delete_result.get("status") == "completed"

    attendee_action = submit(
        f"Create a 30-minute calendar event titled {title} Invite Test at 11 PM on August 4, 2026 and invite qa@example.com.",
        f"qa-approval-{suffix}",
        execute=False,
    )
    approval, _ = show("attendee_approval", attendee_action)
    assert approval.get("attendees") == ["qa@example.com"]
    assert attendee_action.get("requires_approval") is True and attendee_action.get("status") == "awaiting_approval"
    print(json.dumps({"ok": True, "title": title, "approval_executed": False}, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        sys.exit(1)

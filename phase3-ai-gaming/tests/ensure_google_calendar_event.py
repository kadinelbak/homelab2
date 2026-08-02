#!/usr/bin/env python3
import json
import os
import urllib.request


BASE_URL = os.environ.get("AI_ORCHESTRATOR_URL", "http://ai-orchestrator:8095").rstrip("/")
TOKEN = os.environ.get("AI_ORCHESTRATOR_TOKEN", "")
TITLE = os.environ.get("CALENDAR_EVENT_TITLE", "i eat pizza").strip()
WHEN = os.environ.get("CALENDAR_EVENT_WHEN", "today at 8:00 PM").strip()
DURATION = os.environ.get("CALENDAR_EVENT_DURATION", "1 hour").strip()


def api(method, path, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.load(response)


def submit(message, chat_id):
    planned = api("POST", "/requests", {
        "capability": "manage_calendar",
        "inputs": {
            "request": message,
            "source": "calendar-event-repair",
            "conversation_context": [],
            "chat_id": chat_id,
        },
        "permissions": {"may_execute": False, "may_publish": False},
    })
    action = planned["actions"][0]
    if action.get("permissions", {}).get("may_execute"):
        action = api("POST", f"/actions/{action['action_id']}/execute", {})["action"]
    return action


def events_from(action):
    result = action.get("result") or {}
    events = []
    for artifact in result.get("artifacts") or []:
        if artifact.get("type") not in {"calendar_event", "calendar_events"}:
            continue
        if isinstance(artifact.get("item"), dict):
            events.append(artifact["item"])
        if isinstance(artifact.get("items"), list):
            events.extend(item for item in artifact["items"] if isinstance(item, dict))
    return events


def normalized_title(event):
    return str(event.get("title") or event.get("summary") or "").strip().lower()


def event_summary(event):
    return {
        "id": event.get("id"),
        "title": event.get("title") or event.get("summary"),
        "start": event.get("start"),
        "end": event.get("end"),
    }


def main():
    if not TOKEN:
        raise RuntimeError("AI_ORCHESTRATOR_TOKEN is required")
    chat_id = "calendar-event-repair-i-eat-pizza"
    listing = submit(
        f"List my Google Calendar events from 8:00 PM to 9:00 PM today. I am checking for an event titled {TITLE}.",
        chat_id,
    )
    listed_events = events_from(listing)
    matching = [event for event in listed_events if normalized_title(event) == TITLE.lower()]
    print(json.dumps({
        "listing_status": (listing.get("result") or {}).get("status"),
        "listing_summary": (listing.get("result") or {}).get("summary"),
        "matching_events": [event_summary(event) for event in matching],
    }))
    if os.environ.get("CALENDAR_EVENT_INSPECT_ONLY") == "1":
        return
    created = False
    if not matching:
        created_action = submit(
            f"Create a Google Calendar event {WHEN} titled {TITLE} for {DURATION}.",
            chat_id,
        )
        if (created_action.get("result") or {}).get("status") != "completed":
            raise RuntimeError(f"Calendar creation did not complete: {created_action.get('status')}")
        matching = [event for event in events_from(created_action) if normalized_title(event) == TITLE.lower()]
        created = True
    if not matching or not matching[0].get("id"):
        raise RuntimeError("Google worker did not return a verified matching event ID")
    event = matching[0]
    print(json.dumps({
        "verified": True,
        "created": created,
        "title": event.get("title") or event.get("summary"),
        "event_id": event.get("id"),
        "start": event.get("start"),
        "end": event.get("end"),
    }))


if __name__ == "__main__":
    main()

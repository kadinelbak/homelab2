#!/usr/bin/env python3
import json
import urllib.error

import app


state = app.load_state()
created = {}
deleted_ids = set()
for action in state.get("actions", {}).values():
    if action.get("capability") != "manage_calendar":
        continue
    for artifact in (action.get("result") or {}).get("artifacts") or []:
        item = artifact.get("item")
        if artifact.get("type") == "calendar_event" and isinstance(item, dict):
            if str(item.get("summary") or "").startswith("Jarvis Contract QA "):
                created[item.get("id")] = item
        if artifact.get("type") == "calendar_deleted":
            for deleted in item if isinstance(item, list) else []:
                if isinstance(deleted, dict):
                    deleted_ids.add(deleted.get("id"))

results = []
for event_id in sorted(set(created) - deleted_ids):
    try:
        result = app.call_google_tools("/calendar/execute-contract", {
            "contract": {"version": 1, "operation": "delete", "target_event_id": event_id},
            "approved": False,
        })
        results.append({"event_id": event_id, "status": result.get("status")})
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 410}:
            results.append({"event_id": event_id, "status": "already_missing"})
        else:
            try:
                detail = json.loads(exc.read().decode("utf-8") or "{}").get("error")
            except Exception:
                detail = None
            if detail and ("404" in detail or "410" in detail):
                results.append({"event_id": event_id, "status": "already_missing"})
            else:
                results.append({"event_id": event_id, "status": f"worker_http_{exc.code}", "error": detail})

print(json.dumps({"synthetic_created": len(created), "already_verified_deleted": len(deleted_ids), "cleanup": results}, separators=(",", ":")))

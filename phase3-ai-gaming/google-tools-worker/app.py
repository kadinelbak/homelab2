#!/usr/bin/env python3
import base64
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = os.environ.get("GOOGLE_TOOLS_HOST", "0.0.0.0")
PORT = int(os.environ.get("GOOGLE_TOOLS_PORT", "18200"))
DATA_DIR = Path(os.environ.get("GOOGLE_TOOLS_DATA_DIR", "/data"))
TOKEN_PATH = DATA_DIR / "google-token.json"
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:18200/oauth/google/callback")
TOOLS_TOKEN = os.environ.get("GOOGLE_TOOLS_TOKEN", os.environ.get("AI_ORCHESTRATOR_TOKEN", ""))
OAUTH_STATE = os.environ.get("GOOGLE_OAUTH_STATE") or secrets.token_urlsafe(24)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/tasks",
]
DEFAULT_TIMEZONE = os.environ.get("TZ", "America/New_York")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def urlopen_json(req, timeout=60):
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8") or ""
        return json.loads(raw) if raw else {}


def exchange_code(code):
    payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = urlopen_json(req, timeout=60)
    token["created_at"] = int(time.time())
    token["obtained_at"] = now_iso()
    write_json(TOKEN_PATH, token)
    return token


def refresh_token(token):
    payload = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    updated = urlopen_json(req, timeout=60)
    token.update(updated)
    token["created_at"] = int(time.time())
    token["refreshed_at"] = now_iso()
    write_json(TOKEN_PATH, token)
    return token


def access_token():
    token = read_json(TOKEN_PATH)
    if not token.get("access_token"):
        raise RuntimeError("google_oauth_not_authorized")
    expires_in = int(token.get("expires_in", 0) or 0)
    created_at = int(token.get("created_at", 0) or 0)
    if token.get("refresh_token") and time.time() > created_at + max(60, expires_in - 120):
        token = refresh_token(token)
    return token["access_token"]


def google_request(method, url, payload=None, timeout=60):
    body = None
    headers = {"Authorization": f"Bearer {access_token()}"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    return urlopen_json(req, timeout=timeout)


def gmail_get_message(message_id):
    params = urllib.parse.urlencode({"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]}, doseq=True)
    data = google_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}?{params}")
    headers = {
        item.get("name", "").lower(): item.get("value", "")
        for item in data.get("payload", {}).get("headers", [])
    }
    return {
        "id": data.get("id"),
        "thread_id": data.get("threadId"),
        "from": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": data.get("snippet", ""),
        "labels": data.get("labelIds", []),
    }


def gmail_search(query, max_results=10):
    params = urllib.parse.urlencode({"q": query or "in:inbox newer_than:7d", "maxResults": max_results})
    listed = google_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{params}")
    return [gmail_get_message(item["id"]) for item in listed.get("messages", [])]


def infer_gmail_query(request_text):
    text = request_text.lower()
    terms = ["in:inbox"]
    if "unread" in text:
        terms.append("is:unread")
    if "important" in text:
        terms.append("is:important")
    if "today" in text:
        terms.append("newer_than:1d")
    elif "week" in text:
        terms.append("newer_than:7d")
    else:
        terms.append("newer_than:3d")
    return " ".join(terms)


def create_gmail_draft(to_addr, subject, body_text):
    raw = "\r\n".join(
        [
            f"To: {to_addr}",
            f"Subject: {subject}",
            "Content-Type: text/plain; charset=utf-8",
            "",
            body_text,
        ]
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return google_request(
        "POST",
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
        {"message": {"raw": encoded}},
        timeout=60,
    )


def gmail_get_draft(draft_id):
    params = urllib.parse.urlencode({"format": "metadata"})
    return google_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}?{params}", timeout=60)


def create_verified_gmail_draft(to_addr, subject, body_text):
    draft = create_gmail_draft(to_addr, subject, body_text)
    draft_id = draft.get("id")
    verified = {}
    if draft_id:
        verified = gmail_get_draft(draft_id)
    message = verified.get("message") or draft.get("message") or {}
    return {
        "id": draft_id,
        "message_id": message.get("id"),
        "thread_id": message.get("threadId"),
        "verified": bool(verified.get("id") == draft_id),
        "raw": draft,
    }


def contacts_search(query, max_results=10):
    data = google_request(
        "GET",
        "https://people.googleapis.com/v1/people/me/connections?"
        + urllib.parse.urlencode(
            {
                "pageSize": 100,
                "personFields": "names,emailAddresses,phoneNumbers",
            }
        ),
        timeout=60,
    )
    needle = (query or "").lower().strip()
    contacts = []
    for person in data.get("connections", []):
        names = [item.get("displayName", "") for item in person.get("names", [])]
        emails = [item.get("value", "") for item in person.get("emailAddresses", [])]
        phones = [item.get("value", "") for item in person.get("phoneNumbers", [])]
        haystack = " ".join(names + emails + phones).lower()
        if not needle or needle in haystack:
            contacts.append({"names": names, "emails": emails, "phones": phones})
        if len(contacts) >= max_results:
            break
    return contacts


def infer_contact_query(request_text):
    text = request_text.strip()
    for prefix in ("find", "lookup", "look up", "get", "contact", "contacts", "email for", "phone for"):
        if text.lower().startswith(prefix):
            text = text[len(prefix) :].strip()
    return text.replace("?", "").strip()


def response_text_for_contacts(contacts):
    if not contacts:
        return "I did not find matching contacts."
    lines = ["Contacts:"]
    for index, contact in enumerate(contacts, 1):
        lines.append(f"{index}. {', '.join(contact.get('names') or ['(no name)'])}")
        if contact.get("emails"):
            lines.append(f"   Email: {', '.join(contact['emails'])}")
        if contact.get("phones"):
            lines.append(f"   Phone: {', '.join(contact['phones'])}")
    return "\n".join(lines)


def tasklists():
    return google_request("GET", "https://tasks.googleapis.com/tasks/v1/users/@me/lists", timeout=60).get("items", [])


def default_tasklist_id():
    lists = tasklists()
    if not lists:
        raise RuntimeError("google_tasks_no_tasklists_found")
    return lists[0]["id"]


def tasks_list():
    list_id = default_tasklist_id()
    data = google_request(
        "GET",
        f"https://tasks.googleapis.com/tasks/v1/lists/{urllib.parse.quote(list_id, safe='')}/tasks?"
        + urllib.parse.urlencode({"showCompleted": "false", "maxResults": 20}),
        timeout=60,
    )
    return data.get("items", [])


def task_title_from_request(request_text):
    text = request_text.strip()
    lowered = text.lower()
    for prefix in ("add task", "create task", "new task", "todo", "to do", "remind me to", "add"):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip(" :.-")
    return text.strip(" :.-")


def task_create(request_text):
    list_id = default_tasklist_id()
    title = task_title_from_request(request_text) or "Untitled task"
    return google_request(
        "POST",
        f"https://tasks.googleapis.com/tasks/v1/lists/{urllib.parse.quote(list_id, safe='')}/tasks",
        {"title": title},
        timeout=60,
    )


def task_create_intent(request_text):
    lowered = request_text.lower()
    return any(term in lowered for term in ("add task", "create task", "new task", "todo", "to do", "remind me to"))


def response_text_for_tasks(tasks):
    if not tasks:
        return "I did not find open Google Tasks."
    lines = ["Open tasks:"]
    for index, task in enumerate(tasks, 1):
        lines.append(f"{index}. {task.get('title') or '(untitled task)'}")
    return "\n".join(lines)


def calendar_bounds(day):
    today = datetime.now().astimezone()
    if day == "tomorrow":
        target = today + timedelta(days=1)
    else:
        target = today
    start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def combined_request_text(payload):
    parts = []
    for turn in payload.get("conversation_context") or []:
        role = turn.get("role", "user")
        text = turn.get("text", "")
        if text:
            parts.append(f"{role}: {text}")
    current = payload.get("request", "")
    if current:
        parts.append(f"user: {current}")
    return "\n".join(parts)


def current_request_text(payload):
    return (payload.get("request") or "").strip()


def calendar_delete_intent(text):
    lowered = text.lower()
    return any(term in lowered for term in ("delete", "remove", "cancel", "clear"))


def vague_calendar_followup(text):
    lowered = text.lower().strip()
    return lowered in {"yes", "yeah", "yep", "do it", "please do", "create it", "create one", "create one though"} or (
        "create one" in lowered or "do that" in lowered
    )


def calendar_write_intent(text):
    lowered = text.lower()
    return any(
        term in lowered
        for term in (
            "create",
            "make",
            "add",
            "schedule",
            "put",
            "book",
            "event",
            "appointment",
            "create one",
        )
    )


def parse_event_payload(payload):
    text = combined_request_text(payload)
    lowered = text.lower()
    target = datetime.now().astimezone()
    if "tomorrow" in lowered:
        target = target + timedelta(days=1)

    time_matches = list(re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered))
    if not time_matches:
        raise ValueError("calendar_event_time_missing")
    match = time_matches[-1]
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0

    duration = timedelta(hours=1)
    duration_match = re.search(r"lasts?\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)", lowered)
    if duration_match:
        amount = float(duration_match.group(1))
        unit = duration_match.group(2)
        duration = timedelta(minutes=amount if unit.startswith("min") else amount * 60)

    start = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
    end = start + duration

    summary = "Untitled event"
    title_match = re.search(r"(?:title|called|named)\s+['\"]?([^'\"\n]+)", text, re.IGNORECASE)
    if title_match and "no title" not in lowered:
        summary = title_match.group(1).strip()[:120]
    elif "dentist" in lowered:
        summary = "Dentist appointment"
    elif "meeting" in lowered:
        summary = "Meeting"

    description = ""
    description_match = re.search(r"(?:description|desc)\s+['\"]?([^'\"\n]+)", text, re.IGNORECASE)
    if description_match and "no description" not in lowered:
        description = description_match.group(1).strip()[:1000]

    return {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": DEFAULT_TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": DEFAULT_TIMEZONE},
    }


def calendar_create_event(payload):
    event = parse_event_payload(payload)
    created = google_request(
        "POST",
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        event,
        timeout=60,
    )
    return {
        "id": created.get("id"),
        "htmlLink": created.get("htmlLink"),
        "summary": created.get("summary"),
        "start": created.get("start", {}),
        "end": created.get("end", {}),
        "text": (
            f"Verified calendar event created: {created.get('summary') or 'Untitled event'}\n"
            f"Event ID: {created.get('id')}\n"
            f"Start: {(created.get('start') or {}).get('dateTime')}\n"
            f"End: {(created.get('end') or {}).get('dateTime')}"
        ),
    }


def calendar_events_between(start, end):
    params = urllib.parse.urlencode(
        {
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": (start - timedelta(minutes=1)).isoformat(),
            "timeMax": (end + timedelta(minutes=1)).isoformat(),
            "maxResults": 20,
        }
    )
    data = google_request("GET", f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{params}")
    return data.get("items", [])


def event_start_text(event):
    return (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date") or ""


def calendar_delete_event(payload):
    inferred = parse_event_payload(payload)
    start = datetime.fromisoformat(inferred["start"]["dateTime"])
    end = datetime.fromisoformat(inferred["end"]["dateTime"])
    summary = inferred.get("summary") or "Untitled event"
    candidates = []
    for event in calendar_events_between(start, end):
        event_start = event_start_text(event)
        same_start = event_start.startswith(start.isoformat()[:16])
        event_summary = event.get("summary") or "Untitled event"
        same_summary = event_summary == summary or summary == "Untitled event"
        if same_start and same_summary:
            candidates.append(event)

    deleted = []
    for event in candidates:
        google_request(
            "DELETE",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events/" + event["id"],
            timeout=60,
        )
        deleted.append({"id": event.get("id"), "summary": event.get("summary") or "Untitled event", "start": event.get("start", {})})

    return {
        "deleted_count": len(deleted),
        "deleted": deleted,
        "text": f"Verified deleted {len(deleted)} matching calendar event(s)." if deleted else "I did not find a matching calendar event to delete.",
    }


def calendar_list(request_text):
    text = request_text.lower()
    start, end = calendar_bounds("tomorrow" if "tomorrow" in text else "today")
    params = urllib.parse.urlencode(
        {
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": start,
            "timeMax": end,
            "maxResults": 20,
        }
    )
    data = google_request("GET", f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{params}")
    events = []
    for item in data.get("items", []):
        events.append(
            {
                "id": item.get("id"),
                "summary": item.get("summary", "(no title)"),
                "start": item.get("start", {}),
                "end": item.get("end", {}),
                "location": item.get("location", ""),
            }
        )
    return {"time_min": start, "time_max": end, "events": events}


def response_text_for_gmail(messages):
    if not messages:
        return "I did not find matching Gmail messages."
    lines = ["Gmail summary:"]
    for index, msg in enumerate(messages, 1):
        labels = ", ".join(msg.get("labels", []))
        lines.append(f"{index}. {msg.get('subject') or '(no subject)'}")
        lines.append(f"   From: {msg.get('from')}")
        lines.append(f"   Date: {msg.get('date')}")
        if labels:
            lines.append(f"   Labels: {labels}")
        lines.append(f"   Snippet: {msg.get('snippet')}")
    return "\n".join(lines)


def response_text_for_calendar(payload):
    events = payload.get("events", [])
    if not events:
        return "I did not find calendar events in that window."
    lines = ["Calendar:"]
    for index, event in enumerate(events, 1):
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        lines.append(f"{index}. {event.get('summary')} | {start} -> {end}")
    return "\n".join(lines)


class Handler(BaseHTTPRequestHandler):
    server_version = "homelab-google-tools-worker/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def write_json(self, status, payload):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def write_text(self, status, text):
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def authorized(self):
        if not TOOLS_TOKEN or TOOLS_TOKEN.startswith("CHANGE_ME"):
            return False
        return self.headers.get("Authorization", "") == f"Bearer {TOOLS_TOKEN}"

    def require_auth(self):
        if self.authorized():
            return True
        self.write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
        return False

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/health":
            token = read_json(TOKEN_PATH)
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "configured": bool(CLIENT_ID and CLIENT_SECRET),
                    "authorized": bool(token.get("refresh_token") or token.get("access_token")),
                    "redirect_uri": REDIRECT_URI,
                    "scopes": SCOPES,
                },
            )
            return

        if path == "/oauth/google/start":
            if not CLIENT_ID or not CLIENT_SECRET:
                self.write_text(HTTPStatus.INTERNAL_SERVER_ERROR, "Google client credentials are not configured.")
                return
            params = urllib.parse.urlencode(
                {
                    "client_id": CLIENT_ID,
                    "redirect_uri": REDIRECT_URI,
                    "response_type": "code",
                    "scope": " ".join(SCOPES),
                    "access_type": "offline",
                    "prompt": "consent",
                    "state": OAUTH_STATE,
                }
            )
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
            self.end_headers()
            return

        if path == "/oauth/google/callback":
            if query.get("state", [""])[0] != OAUTH_STATE:
                self.write_text(HTTPStatus.BAD_REQUEST, "OAuth state mismatch.")
                return
            code = query.get("code", [""])[0]
            if not code:
                self.write_text(HTTPStatus.BAD_REQUEST, "Missing OAuth code.")
                return
            try:
                exchange_code(code)
                self.write_text(HTTPStatus.OK, "Jarvis Google authorization complete. You can close this tab.")
            except Exception as exc:
                self.write_text(HTTPStatus.INTERNAL_SERVER_ERROR, f"OAuth failed: {exc}")
            return

        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if not self.require_auth():
            return
        payload = self.read_json()
        try:
            if path == "/gmail/search":
                messages = gmail_search(payload.get("query", ""), int(payload.get("max_results", 10)))
                self.write_json(HTTPStatus.OK, {"ok": True, "messages": messages, "text": response_text_for_gmail(messages)})
                return
            if path == "/gmail/assist":
                request_text = payload.get("request", "")
                messages = gmail_search(infer_gmail_query(request_text), int(payload.get("max_results", 10)))
                self.write_json(HTTPStatus.OK, {"ok": True, "messages": messages, "text": response_text_for_gmail(messages)})
                return
            if path == "/gmail/create-draft":
                draft = create_verified_gmail_draft(payload["to"], payload.get("subject", ""), payload.get("body", ""))
                status = "Verified Gmail draft created" if draft.get("verified") else "Gmail draft created, verification incomplete"
                self.write_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "draft": draft,
                        "text": f"{status}.\nDraft ID: {draft.get('id')}\nThread ID: {draft.get('thread_id')}",
                    },
                )
                return
            if path == "/contacts/assist":
                contacts = contacts_search(infer_contact_query(payload.get("request", "")), int(payload.get("max_results", 10)))
                self.write_json(HTTPStatus.OK, {"ok": True, "contacts": contacts, "text": response_text_for_contacts(contacts)})
                return
            if path == "/tasks/assist":
                request_text = payload.get("request", "")
                if task_create_intent(request_text):
                    task = task_create(request_text)
                    self.write_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "task": task,
                            "text": f"Verified Google Task created: {task.get('title')}\nTask ID: {task.get('id')}",
                        },
                    )
                else:
                    tasks = tasks_list()
                    self.write_json(HTTPStatus.OK, {"ok": True, "tasks": tasks, "text": response_text_for_tasks(tasks)})
                return
            if path == "/calendar/list":
                result = calendar_list(payload.get("request", "today"))
                self.write_json(HTTPStatus.OK, {"ok": True, **result, "text": response_text_for_calendar(result)})
                return
            if path == "/calendar/assist":
                current = current_request_text(payload)
                combined = combined_request_text(payload)
                if calendar_delete_intent(current):
                    deleted = calendar_delete_event(payload)
                    self.write_json(HTTPStatus.OK, {"ok": True, "deleted": deleted, "text": deleted["text"]})
                elif calendar_write_intent(current) or (vague_calendar_followup(current) and calendar_write_intent(combined)):
                    created = calendar_create_event(payload)
                    self.write_json(HTTPStatus.OK, {"ok": True, "event": created, "text": created["text"]})
                else:
                    result = calendar_list(payload.get("request", "today"))
                    self.write_json(HTTPStatus.OK, {"ok": True, **result, "text": response_text_for_calendar(result)})
                return
            if path == "/calendar/create-event":
                created = calendar_create_event(payload)
                self.write_json(HTTPStatus.OK, {"ok": True, "event": created, "text": created["text"]})
                return
            if path == "/calendar/delete-event":
                deleted = calendar_delete_event(payload)
                self.write_json(HTTPStatus.OK, {"ok": True, "deleted": deleted, "text": deleted["text"]})
                return
        except Exception as exc:
            self.write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Google tools worker listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

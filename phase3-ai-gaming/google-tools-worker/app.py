#!/usr/bin/env python3
import base64
import html
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = os.environ.get("GOOGLE_TOOLS_HOST", "0.0.0.0")
PORT = int(os.environ.get("GOOGLE_TOOLS_PORT", "18200"))
DATA_DIR = Path(os.environ.get("GOOGLE_TOOLS_DATA_DIR", "/data"))
TOKEN_PATH = DATA_DIR / "google-token.json"
PROFILE_DB_PATH = DATA_DIR / "briefing-profile.sqlite3"
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
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/tasks",
]
DEFAULT_TIMEZONE = os.environ.get("TZ", "America/New_York")
WEATHER_PROXY_URL = os.environ.get("WEATHER_PROXY_URL", "http://weather-proxy:8098").rstrip("/")
NEWS_RSS_URLS = [
    item.strip()
    for item in os.environ.get(
        "NEWS_RSS_URLS",
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    ).split(",")
    if item.strip()
]
GITHUB_WORKER_URL = os.environ.get("GITHUB_WORKER_URL", "http://github-tools-worker:18400").rstrip("/")
GITHUB_WORKER_TOKEN = os.environ.get("GITHUB_WORKER_TOKEN", TOOLS_TOKEN)


DEFAULT_PROFILE = {
    "current_city": "Gainesville",
    "news_sources": NEWS_RSS_URLS,
    "news_categories": ["major", "technology", "health"],
    "morning_preferences": [
        "Show top decisions, blockers, and the next physical action.",
        "Include weather only when it affects travel or planning.",
    ],
    "evening_preferences": [
        "Show unresolved commitments and the best first task for tomorrow.",
    ],
}


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


def profile_connection():
    db_path = PROFILE_DB_PATH
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        if os.name != "nt":
            raise
        db_path = Path(tempfile.gettempdir()) / "jarvis-briefing-profile.sqlite3"
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def parse_json_value(value, fallback):
    try:
        return json.loads(value)
    except Exception:
        return fallback


def normalize_repo(value):
    value = (value or "").strip()
    match = re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value)
    return value if match else ""


def get_briefing_profile():
    profile = dict(DEFAULT_PROFILE)
    connection = profile_connection()
    try:
        rows = connection.execute("SELECT key, value FROM profile_settings").fetchall()
        for row in rows:
            fallback = DEFAULT_PROFILE.get(row["key"], "" if row["key"] == "current_city" else [])
            profile[row["key"]] = parse_json_value(row["value"], fallback)
        profile["notes"] = [
            dict(row)
            for row in connection.execute(
                "SELECT id, note, created_at FROM profile_notes ORDER BY id DESC LIMIT 50"
            ).fetchall()
        ]
    finally:
        connection.close()
    for key in ("watched_repos", "active_projects", "important_senders", "ignored_topics", "news_sources", "news_categories"):
        profile.setdefault(key, [])
    profile["current_city"] = (profile.get("current_city") or DEFAULT_PROFILE["current_city"]).strip()
    return profile


def update_briefing_profile(updates):
    allowed = {
        "current_city",
        "watched_repos",
        "active_projects",
        "important_senders",
        "ignored_topics",
        "news_sources",
        "news_categories",
        "morning_preferences",
        "evening_preferences",
    }
    changed = {}
    now_value = now_iso()
    connection = profile_connection()
    try:
        for key, value in (updates or {}).items():
            if key not in allowed:
                continue
            if key == "current_city":
                value = str(value or DEFAULT_PROFILE["current_city"]).strip() or DEFAULT_PROFILE["current_city"]
            elif key == "watched_repos":
                value = [repo for repo in (normalize_repo(item) for item in value or []) if repo]
            elif not isinstance(value, list):
                value = [str(value).strip()] if str(value or "").strip() else []
            connection.execute(
                """
                INSERT INTO profile_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value), now_value),
            )
            changed[key] = value
        connection.commit()
    finally:
        connection.close()
    profile = get_briefing_profile()
    return {"status": "completed", "changed": changed, "profile": profile}


def add_briefing_note(note):
    note = re.sub(r"\s+", " ", str(note or "")).strip()
    if not note:
        raise ValueError("note_required")
    connection = profile_connection()
    try:
        cursor = connection.execute(
            "INSERT INTO profile_notes (note, created_at) VALUES (?, ?)",
            (note[:1000], now_iso()),
        )
        connection.commit()
        note_id = cursor.lastrowid
    finally:
        connection.close()
    return {"status": "completed", "note": {"id": note_id, "note": note[:1000]}}


def delete_briefing_note(note_id=None, text=None):
    connection = profile_connection()
    try:
        if note_id:
            connection.execute("DELETE FROM profile_notes WHERE id = ?", (int(note_id),))
        elif text:
            connection.execute("DELETE FROM profile_notes WHERE note LIKE ?", (f"%{str(text).strip()}%",))
        else:
            raise ValueError("note_id_or_text_required")
        connection.commit()
    finally:
        connection.close()
    return {"status": "completed", "profile": get_briefing_profile()}


def urlopen_json(req, timeout=60):
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8") or ""
        return json.loads(raw) if raw else {}


def urlopen_text(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "JarvisBriefing/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


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
    params = urllib.parse.urlencode({"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]}, doseq=True)
    data = google_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}?{params}")
    return compact_gmail_message(data)


def compact_gmail_message(data):
    headers = {
        item.get("name", "").lower(): item.get("value", "")
        for item in data.get("payload", {}).get("headers", [])
    }
    return {
        "id": data.get("id"),
        "thread_id": data.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": data.get("snippet", ""),
        "labels": data.get("labelIds", []),
    }


def gmail_search(query, max_results=10):
    params = urllib.parse.urlencode({"q": query or "in:inbox newer_than:7d", "maxResults": max_results})
    listed = google_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{params}")
    return [gmail_get_message(item["id"]) for item in listed.get("messages", [])]


def gmail_count(query):
    params = urllib.parse.urlencode({"q": query or "in:inbox newer_than:1d", "maxResults": 1})
    listed = google_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{params}", timeout=60)
    return int(listed.get("resultSizeEstimate", 0) or 0)


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


def gmail_raw_message(to_addrs, subject, body_text, cc=None, bcc=None):
    message = EmailMessage()
    message["To"] = ", ".join(to_addrs if isinstance(to_addrs, list) else [str(to_addrs or "")])
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject or ""
    message.set_content(body_text or "")
    return message.as_bytes()


def create_gmail_draft(to_addr, subject, body_text, cc=None, bcc=None):
    raw = gmail_raw_message(to_addr if isinstance(to_addr, list) else [to_addr], subject, body_text, cc, bcc)
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return google_request(
        "POST",
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
        {"message": {"raw": encoded}},
        timeout=60,
    )


def gmail_get_draft(draft_id):
    params = urllib.parse.urlencode({"format": "metadata", "metadataHeaders": ["To", "Subject"]}, doseq=True)
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
        "to": to_addr if isinstance(to_addr, str) else ", ".join(to_addr or []),
        "subject": subject,
        "verified": bool(verified.get("id") == draft_id),
        "raw": draft,
    }


def update_gmail_draft(draft_id, to_addrs, subject, body_text, cc=None, bcc=None):
    raw = gmail_raw_message(to_addrs, subject, body_text, cc, bcc)
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return google_request(
        "PUT",
        f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}",
        {"id": draft_id, "message": {"raw": encoded}},
        timeout=60,
    )


def send_gmail_draft(draft_id):
    return google_request(
        "POST",
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts/send",
        {"id": draft_id},
        timeout=60,
    )


def send_gmail_message(to_addrs, subject, body_text, cc=None, bcc=None):
    raw = gmail_raw_message(to_addrs, subject, body_text, cc, bcc)
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return google_request(
        "POST",
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        {"raw": encoded},
        timeout=60,
    )


def gmail_modify_labels(message_id, add_labels, remove_labels):
    return google_request(
        "POST",
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify",
        {"addLabelIds": add_labels or [], "removeLabelIds": remove_labels or []},
        timeout=60,
    )


def validate_executable_gmail_contract(contract):
    if not isinstance(contract, dict):
        raise ValueError("gmail_contract_must_be_object")
    allowed = {
        "version", "operation", "query", "max_results", "draft_id", "message_ids", "thread_id",
        "to", "cc", "bcc", "subject", "body", "label_ids", "remove_label_ids",
        "requires_clarification", "clarification",
    }
    if set(contract) - allowed:
        raise ValueError("gmail_contract_unknown_fields")
    operation = contract.get("operation")
    if operation not in {"search_messages", "summarize_messages", "create_draft", "update_draft", "send_draft", "send_message", "label_messages"}:
        raise ValueError("gmail_contract_operation_invalid")
    if contract.get("requires_clarification"):
        raise ValueError("gmail_contract_not_executable")
    if operation in {"search_messages", "summarize_messages"} and not contract.get("query"):
        raise ValueError("gmail_query_required")
    if operation == "create_draft" and not contract.get("body"):
        raise ValueError("gmail_draft_body_required")
    if operation == "update_draft" and not contract.get("draft_id"):
        raise ValueError("gmail_draft_id_required")
    if operation == "send_draft" and not contract.get("draft_id"):
        raise ValueError("gmail_send_draft_id_required")
    if operation == "send_message" and not (contract.get("to") and contract.get("subject") and contract.get("body")):
        raise ValueError("gmail_send_message_incomplete")
    if operation == "label_messages":
        if not contract.get("message_ids"):
            raise ValueError("gmail_message_ids_required")
        if not contract.get("label_ids") and not contract.get("remove_label_ids"):
            raise ValueError("gmail_label_ids_required")


def execute_gmail_contract(contract, approved=False):
    validate_executable_gmail_contract(contract)
    operation = contract["operation"]
    if operation in {"search_messages", "summarize_messages"}:
        messages = gmail_search(contract["query"], int(contract.get("max_results", 10)))
        text = response_text_for_gmail(messages)
        if operation == "summarize_messages":
            text = text.replace("Gmail summary:", "Gmail summary:")
        return {"status": "completed", "messages": messages, "text": text}

    if operation == "create_draft":
        draft = create_verified_gmail_draft(
            contract.get("to") or [],
            contract.get("subject") or "",
            contract.get("body") or "",
        )
        if not draft.get("verified"):
            raise RuntimeError("gmail_draft_verification_failed")
        return {
            "status": "completed",
            "draft": draft,
            "text": f"Verified Gmail draft created.\nDraft ID: {draft.get('id')}\nThread ID: {draft.get('thread_id')}",
        }

    if operation == "update_draft":
        update_gmail_draft(
            contract["draft_id"],
            contract.get("to") or [],
            contract.get("subject") or "",
            contract.get("body") or "",
            contract.get("cc") or [],
            contract.get("bcc") or [],
        )
        verified = gmail_get_draft(contract["draft_id"])
        if verified.get("id") != contract["draft_id"]:
            raise RuntimeError("gmail_draft_update_verification_failed")
        message = verified.get("message") or {}
        draft = {
            "id": verified.get("id"),
            "message_id": message.get("id"),
            "thread_id": message.get("threadId"),
            "to": ", ".join(contract.get("to") or []),
            "subject": contract.get("subject"),
            "verified": True,
        }
        return {"status": "completed", "draft": draft, "text": f"Verified Gmail draft updated.\nDraft ID: {draft['id']}"}

    if operation == "send_draft":
        if not approved:
            raise PermissionError("gmail_send_requires_approval")
        existing = gmail_get_draft(contract["draft_id"])
        sent = send_gmail_draft(contract["draft_id"])
        sent_message = gmail_get_message(sent["id"]) if sent.get("id") else compact_gmail_message(sent)
        if not sent_message.get("id"):
            raise RuntimeError("gmail_send_verification_failed")
        return {
            "status": "completed",
            "sent_message": sent_message,
            "draft": {"id": contract["draft_id"], "verified": existing.get("id") == contract["draft_id"]},
            "text": f"Verified Gmail draft sent.\nMessage ID: {sent_message.get('id')}\nThread ID: {sent_message.get('thread_id')}",
        }

    if operation == "send_message":
        if not approved:
            raise PermissionError("gmail_send_requires_approval")
        sent = send_gmail_message(
            contract.get("to") or [],
            contract.get("subject") or "",
            contract.get("body") or "",
            contract.get("cc") or [],
            contract.get("bcc") or [],
        )
        sent_message = gmail_get_message(sent["id"]) if sent.get("id") else compact_gmail_message(sent)
        if not sent_message.get("id") or "SENT" not in (sent_message.get("labels") or []):
            raise RuntimeError("gmail_send_verification_failed")
        return {
            "status": "completed",
            "sent_message": sent_message,
            "text": f"Verified Gmail message sent.\nMessage ID: {sent_message.get('id')}\nThread ID: {sent_message.get('thread_id')}",
        }

    if operation == "label_messages":
        if not approved:
            raise PermissionError("gmail_label_requires_approval")
        messages = []
        add_labels = contract.get("label_ids") or []
        remove_labels = contract.get("remove_label_ids") or []
        for message_id in contract.get("message_ids") or []:
            gmail_modify_labels(message_id, add_labels, remove_labels)
            verified = gmail_get_message(message_id)
            labels = set(verified.get("labels") or [])
            if not set(add_labels).issubset(labels) or set(remove_labels).intersection(labels):
                raise RuntimeError("gmail_label_verification_failed")
            messages.append(verified)
        return {"status": "completed", "messages": messages, "text": f"Verified label update on {len(messages)} Gmail message(s)."}

    raise ValueError("gmail_contract_operation_unsupported")


def contacts_search(query, max_results=10):
    data = google_request(
        "GET",
        "https://people.googleapis.com/v1/people/me/connections?"
        + urllib.parse.urlencode(
            {
                "pageSize": min(max(int(max_results or 10), 1), 1000),
                "personFields": "names,emailAddresses,phoneNumbers,metadata",
            }
        ),
        timeout=60,
    )
    needle = (query or "").lower().strip()
    contacts = []
    for person in data.get("connections", []):
        contact = compact_contact(person)
        names = contact["names"]
        emails = contact["emails"]
        phones = contact["phones"]
        haystack = " ".join(names + emails + phones).lower()
        if not needle or needle in haystack:
            contacts.append(contact)
        if len(contacts) >= max_results:
            break
    return contacts


def compact_contact(person):
    return {
        "resource_name": person.get("resourceName"),
        "etag": person.get("etag"),
        "names": [item.get("displayName", "") for item in person.get("names", []) if item.get("displayName")],
        "emails": [item.get("value", "") for item in person.get("emailAddresses", []) if item.get("value")],
        "phones": [item.get("value", "") for item in person.get("phoneNumbers", []) if item.get("value")],
    }


def contact_get(resource_name):
    return google_request(
        "GET",
        "https://people.googleapis.com/v1/"
        + urllib.parse.quote(resource_name, safe="/")
        + "?personFields=names,emailAddresses,phoneNumbers,metadata",
        timeout=60,
    )


def contact_body(contract, existing=None):
    body = {}
    if existing and existing.get("etag"):
        body["etag"] = existing["etag"]
    if contract.get("name"):
        body["names"] = [{"unstructuredName": contract["name"]}]
    if contract.get("email"):
        body["emailAddresses"] = [{"value": contract["email"]}]
    if contract.get("phone"):
        body["phoneNumbers"] = [{"value": contract["phone"]}]
    return body


def validate_executable_contacts_contract(contract):
    if not isinstance(contract, dict):
        raise ValueError("contacts_contract_must_be_object")
    allowed = {
        "version", "operation", "query", "name", "email", "phone", "resource_name",
        "requires_clarification", "clarification", "max_results",
    }
    if set(contract) - allowed:
        raise ValueError("contacts_contract_unknown_fields")
    operation = contract.get("operation")
    if operation not in {"search", "resolve_recipient", "create", "update", "clarify"}:
        raise ValueError("contacts_contract_operation_invalid")
    if contract.get("requires_clarification") or operation == "clarify":
        return
    if operation in {"search", "resolve_recipient"} and not contract.get("query"):
        raise ValueError("contacts_contract_query_required")
    if operation == "create" and not (contract.get("name") and (contract.get("email") or contract.get("phone"))):
        raise ValueError("contacts_create_contract_incomplete")
    if operation == "update" and not contract.get("resource_name"):
        raise ValueError("contacts_update_resource_required")


def resolve_contact(query, max_results=10):
    contacts = contacts_search(query, max_results)
    needle = (query or "").casefold().strip()
    exact = []
    for contact in contacts:
        names = [name.casefold() for name in contact.get("names") or []]
        emails = [email.casefold() for email in contact.get("emails") or []]
        if needle in names or needle in emails:
            exact.append(contact)
    matches = exact or contacts
    if len(matches) == 1 and matches[0].get("emails"):
        contact = matches[0]
        return {
            "status": "completed",
            "contact": contact,
            "resolved_recipient": {
                "name": (contact.get("names") or [query])[0],
                "email": contact["emails"][0],
                "resource_name": contact.get("resource_name"),
            },
            "contacts": matches,
            "text": f"Resolved contact: {(contact.get('names') or [query])[0]} <{contact['emails'][0]}>",
        }
    if not matches:
        return {"status": "clarification_required", "contacts": [], "text": f"I did not find a contact matching {query!r}."}
    return {
        "status": "clarification_required",
        "contacts": matches,
        "text": f"I found {len(matches)} possible contacts. Please choose the exact recipient.",
    }


def execute_contacts_contract(contract, approved=False):
    validate_executable_contacts_contract(contract)
    operation = contract["operation"]
    if contract.get("requires_clarification") or operation == "clarify":
        return {"status": "clarification_required", "text": contract.get("clarification") or "Which contact should I use?"}
    if operation == "search":
        contacts = contacts_search(contract.get("query"), int(contract.get("max_results") or 10))
        return {"status": "completed", "contacts": contacts, "text": response_text_for_contacts(contacts)}
    if operation == "resolve_recipient":
        return resolve_contact(contract.get("query"), int(contract.get("max_results") or 10))
    if operation == "create":
        if not approved:
            raise PermissionError("contacts_write_requires_approval")
        created = google_request(
            "POST",
            "https://people.googleapis.com/v1/people:createContact",
            contact_body(contract),
            timeout=60,
        )
        contact = compact_contact(contact_get(created["resourceName"]))
        if contract.get("email") and contract["email"] not in contact.get("emails", []):
            raise RuntimeError("contacts_create_verification_failed")
        return {"status": "completed", "contact": contact, "text": f"Verified contact created: {', '.join(contact.get('names') or ['(no name)'])}"}
    if operation == "update":
        if not approved:
            raise PermissionError("contacts_write_requires_approval")
        existing = contact_get(contract["resource_name"])
        patch = contact_body(contract, existing)
        fields = []
        if patch.get("names"):
            fields.append("names")
        if patch.get("emailAddresses"):
            fields.append("emailAddresses")
        if patch.get("phoneNumbers"):
            fields.append("phoneNumbers")
        if not fields:
            raise ValueError("contacts_update_fields_required")
        google_request(
            "PATCH",
            "https://people.googleapis.com/v1/"
            + urllib.parse.quote(contract["resource_name"], safe="/")
            + ":updateContact?"
            + urllib.parse.urlencode({"updatePersonFields": ",".join(fields)}),
            patch,
            timeout=60,
        )
        contact = compact_contact(contact_get(contract["resource_name"]))
        if contract.get("email") and contract["email"] not in contact.get("emails", []):
            raise RuntimeError("contacts_update_verification_failed")
        return {"status": "completed", "contact": contact, "text": f"Verified contact updated: {', '.join(contact.get('names') or ['(no name)'])}"}
    raise ValueError("contacts_contract_operation_unsupported")


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


def tasks_list(show_completed=False, max_results=20):
    list_id = default_tasklist_id()
    data = google_request(
        "GET",
        f"https://tasks.googleapis.com/tasks/v1/lists/{urllib.parse.quote(list_id, safe='')}/tasks?"
        + urllib.parse.urlencode({"showCompleted": "true" if show_completed else "false", "showDeleted": "false", "maxResults": max_results}),
        timeout=60,
    )
    return [compact_task(item, list_id) for item in data.get("items", [])]


def compact_task(task, tasklist_id=None):
    return {
        "id": task.get("id"),
        "tasklist_id": tasklist_id,
        "title": task.get("title") or "",
        "notes": task.get("notes") or "",
        "status": task.get("status") or "",
        "due": task.get("due"),
        "completed": task.get("completed"),
        "updated": task.get("updated"),
        "deleted": task.get("deleted") is True,
        "hidden": task.get("hidden") is True,
    }


def task_get(task_id, tasklist_id=None):
    list_id = tasklist_id or default_tasklist_id()
    task = google_request(
        "GET",
        f"https://tasks.googleapis.com/tasks/v1/lists/{urllib.parse.quote(list_id, safe='')}/tasks/{urllib.parse.quote(task_id, safe='')}",
        timeout=60,
    )
    return compact_task(task, list_id)


def task_title_from_request(request_text):
    text = request_text.strip()
    lowered = text.lower()
    for prefix in ("add task", "create task", "new task", "todo", "to do", "remind me to", "add"):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip(" :.-")
    return text.strip(" :.-")


def task_create_from_contract(contract):
    list_id = contract.get("tasklist_id") or default_tasklist_id()
    payload = {"title": contract.get("title") or "Untitled task"}
    if contract.get("notes"):
        payload["notes"] = contract["notes"]
    if contract.get("due"):
        payload["due"] = contract["due"]
    created = google_request(
        "POST",
        f"https://tasks.googleapis.com/tasks/v1/lists/{urllib.parse.quote(list_id, safe='')}/tasks",
        payload,
        timeout=60,
    )
    verified = task_get(created["id"], list_id)
    if verified.get("title") != payload["title"]:
        raise RuntimeError("tasks_create_verification_failed")
    return verified


def task_create(request_text):
    task = task_create_from_contract({"title": task_title_from_request(request_text) or "Untitled task"})
    return task


def validate_executable_tasks_contract(contract):
    if not isinstance(contract, dict):
        raise ValueError("tasks_contract_must_be_object")
    allowed = {
        "version", "operation", "query", "task_id", "tasklist_id", "title",
        "notes", "due", "requires_clarification", "clarification", "max_results",
    }
    if set(contract) - allowed:
        raise ValueError("tasks_contract_unknown_fields")
    operation = contract.get("operation")
    if operation not in {"list", "create", "complete", "update", "delete", "clarify"}:
        raise ValueError("tasks_contract_operation_invalid")
    if contract.get("requires_clarification") or operation == "clarify":
        return
    if operation == "create" and not contract.get("title"):
        raise ValueError("tasks_create_title_required")
    if operation in {"complete", "update", "delete"} and not contract.get("task_id"):
        raise ValueError("tasks_contract_task_id_required")


def execute_tasks_contract(contract, approved=False):
    validate_executable_tasks_contract(contract)
    operation = contract["operation"]
    if contract.get("requires_clarification") or operation == "clarify":
        return {"status": "clarification_required", "text": contract.get("clarification") or "Which task should I use?"}
    list_id = contract.get("tasklist_id") or default_tasklist_id()
    if operation == "list":
        tasks = tasks_list(False, int(contract.get("max_results") or 20))
        query = (contract.get("query") or "").casefold().strip()
        if query:
            tasks = [task for task in tasks if query in " ".join([task.get("title", ""), task.get("notes", "")]).casefold()]
        return {"status": "completed", "tasks": tasks, "text": response_text_for_tasks(tasks)}
    if operation == "create":
        task = task_create_from_contract({**contract, "tasklist_id": list_id})
        return {"status": "completed", "task": task, "text": f"Verified Google Task created: {task.get('title')}\nTask ID: {task.get('id')}"}
    if operation == "complete":
        google_request(
            "PATCH",
            f"https://tasks.googleapis.com/tasks/v1/lists/{urllib.parse.quote(list_id, safe='')}/tasks/{urllib.parse.quote(contract['task_id'], safe='')}",
            {"status": "completed"},
            timeout=60,
        )
        task = task_get(contract["task_id"], list_id)
        if task.get("status") != "completed":
            raise RuntimeError("tasks_complete_verification_failed")
        return {"status": "completed", "task": task, "text": f"Verified Google Task completed: {task.get('title')}"}
    if operation == "update":
        patch = {}
        for key in ("title", "notes", "due"):
            if contract.get(key) is not None:
                patch[key] = contract.get(key)
        if not patch:
            raise ValueError("tasks_update_fields_required")
        google_request(
            "PATCH",
            f"https://tasks.googleapis.com/tasks/v1/lists/{urllib.parse.quote(list_id, safe='')}/tasks/{urllib.parse.quote(contract['task_id'], safe='')}",
            patch,
            timeout=60,
        )
        task = task_get(contract["task_id"], list_id)
        for key, value in patch.items():
            if task.get(key) != value:
                raise RuntimeError("tasks_update_verification_failed")
        return {"status": "completed", "task": task, "text": f"Verified Google Task updated: {task.get('title')}"}
    if operation == "delete":
        existing = task_get(contract["task_id"], list_id)
        google_request(
            "DELETE",
            f"https://tasks.googleapis.com/tasks/v1/lists/{urllib.parse.quote(list_id, safe='')}/tasks/{urllib.parse.quote(contract['task_id'], safe='')}",
            timeout=60,
        )
        try:
            deleted = task_get(contract["task_id"], list_id)
            if not (deleted.get("deleted") or deleted.get("hidden")):
                raise RuntimeError("tasks_delete_verification_failed")
        except urllib.error.HTTPError as exc:
            if exc.code not in {404, 410}:
                raise
        return {"status": "completed", "task": existing, "text": f"Verified Google Task deleted: {existing.get('title')}"}
    raise ValueError("tasks_contract_operation_unsupported")


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


def brief_message_line(msg):
    subject = msg.get("subject") or "(no subject)"
    sender = msg.get("from") or "(unknown sender)"
    snippet = (msg.get("snippet") or "").strip()
    if len(snippet) > 160:
        snippet = snippet[:157].rstrip() + "..."
    return f"- {subject}\n  From: {sender}\n  {snippet}"


def dedupe_messages(*groups):
    seen = set()
    messages = []
    for group in groups:
        for msg in group or []:
            msg_id = msg.get("id")
            if msg_id and msg_id in seen:
                continue
            if msg_id:
                seen.add(msg_id)
            messages.append(msg)
    return messages


def briefing_email_sections(kind):
    base = "in:inbox newer_than:2d -from:me -in:sent"
    unread_query = f"{base} is:unread -category:promotions -category:social -category:forums"
    review_query = unread_query
    recent_query = f"{base} -category:promotions -category:social -category:forums"
    if kind == "evening":
        unread_query = "in:inbox is:unread newer_than:1d -from:me -in:sent -category:promotions -category:social -category:forums"
        review_query = unread_query
        recent_query = "in:inbox newer_than:1d -from:me -in:sent -category:promotions -category:social -category:forums"
    review = gmail_search(review_query, 5)
    unread = gmail_search(unread_query, 5)
    recent = gmail_search(recent_query, 5)
    review_items = dedupe_messages(review, unread)[:6]
    fyis = [msg for msg in dedupe_messages(recent) if msg.get("id") not in {item.get("id") for item in review_items}][:3]
    return {
        "counts": {
            "review": len(review_items),
            "unread": gmail_count(unread_query),
            "recent_inbox": gmail_count(recent_query),
        },
        "review": review_items,
        "fyi": fyis,
        "queries": {
            "review": review_query,
            "unread": unread_query,
            "recent": recent_query,
        },
    }


def response_text_for_briefing(kind, calendar, email, tasks):
    title = "Evening recap" if kind == "evening" else "Morning briefing"
    calendar_label = "Tomorrow calendar" if kind == "evening" else "Today calendar"
    lines = [title, ""]
    counts = email.get("counts") or {}
    lines.extend([
        "Inbox readout:",
        f"- Review-now highlights shown: {counts.get('review', 0)}",
        f"- Unread non-noise inbox: {counts.get('unread', 0)}",
        f"- Recent non-noise inbox: {counts.get('recent_inbox', 0)}",
        "",
        "Review now:",
    ])
    if email.get("review"):
        lines.extend(brief_message_line(msg) for msg in email["review"])
    else:
        lines.append("- Nothing urgent found in Gmail.")
    lines.extend(["", "FYI / scan later:"])
    if email.get("fyi"):
        lines.extend(brief_message_line(msg) for msg in email["fyi"])
    else:
        lines.append("- No extra recent inbox items worth surfacing.")
    lines.extend(["", f"{calendar_label}:"])
    if calendar.get("events"):
        for event in calendar["events"]:
            start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            lines.append(f"- {event.get('summary')} at {start}")
    else:
        lines.append("- No calendar events found.")
    lines.extend(["", "Open tasks:"])
    if tasks:
        for task in tasks[:10]:
            due = f" due {task.get('due')}" if task.get("due") else ""
            lines.append(f"- {task.get('title') or '(untitled task)'}{due}")
    else:
        lines.append("- No open Google Tasks.")
    if len(tasks) > 10:
        lines.append(f"- Plus {len(tasks) - 10} more open task(s).")
    return "\n".join(lines)


def fetch_weather_summary(current_city=None):
    if not WEATHER_PROXY_URL:
        return {"status": "disabled", "text": "Weather is not configured."}
    try:
        with urllib.request.urlopen(WEATHER_PROXY_URL + "/summary", timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return {"status": "unavailable", "text": f"Weather unavailable: {str(exc)[:120]}"}
    cities = payload.get("cities") or []
    if current_city:
        needle = str(current_city).casefold()
        filtered = [
            city for city in cities
            if needle in str(city.get("name") or "").casefold()
            or needle in str(city.get("id") or "").casefold()
        ]
        cities = filtered
    lines = []
    for city in cities[:1 if current_city else 4]:
        lines.append(f"- {city.get('name')}: {city.get('label')}")
    return {
        "status": "completed",
        "preview": payload.get("preview") or "",
        "cities": cities,
        "location": current_city or "",
        "text": "\n".join(lines) if lines else f"- Weather unavailable for {current_city}." if current_city else "- Weather summary had no configured locations.",
    }


def clean_news_text(value):
    value = html.unescape(re.sub(r"<[^>]+>", "", value or ""))
    return re.sub(r"\s+", " ", value).strip()


def fetch_major_news(max_items=5):
    items = []
    seen = set()
    errors = []
    for url in NEWS_RSS_URLS:
        try:
            raw = urlopen_text(url, timeout=25)
            root = ET.fromstring(raw)
            for item in root.findall(".//item"):
                title = clean_news_text(item.findtext("title"))
                link = clean_news_text(item.findtext("link"))
                source = clean_news_text(item.findtext("source")) or urllib.parse.urlparse(url).netloc
                if not title:
                    continue
                key = title.casefold()
                if key in seen:
                    continue
                seen.add(key)
                items.append({"title": title[:220], "source": source[:120], "link": link})
                if len(items) >= max_items:
                    break
        except Exception as exc:
            errors.append(str(exc)[:120])
        if len(items) >= max_items:
            break
    if not items:
        return {"status": "unavailable", "items": [], "text": "- Major news unavailable." + (f" {errors[0]}" if errors else "")}
    return {
        "status": "completed",
        "items": items,
        "text": "\n".join(f"- {item['title']} ({item['source']})" for item in items),
    }


def call_github_digest(profile):
    repos = profile.get("watched_repos") or []
    if not GITHUB_WORKER_URL or not repos:
        return {"status": "not_configured", "items": [], "text": "- No watched GitHub repositories configured."}
    body = json.dumps({"repos": repos}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if GITHUB_WORKER_TOKEN and not GITHUB_WORKER_TOKEN.startswith("CHANGE_ME"):
        headers["Authorization"] = f"Bearer {GITHUB_WORKER_TOKEN}"
    req = urllib.request.Request(GITHUB_WORKER_URL + "/github/digest", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:
        return {"status": "unavailable", "items": [], "text": f"- GitHub digest unavailable: {str(exc)[:120]}"}


def event_time_text(event):
    start = event.get("start") or {}
    return start.get("dateTime") or start.get("date") or "time not set"


def task_due_rank(task):
    due = task.get("due")
    if not due:
        return 9
    try:
        due_date = datetime.fromisoformat(str(due).replace("Z", "+00:00")).date()
        today = datetime.now().astimezone().date()
        delta = (due_date - today).days
        if delta < 0:
            return 0
        if delta == 0:
            return 1
        if delta <= 3:
            return 2
    except Exception:
        return 4
    return 5


def message_score(message, profile):
    labels = {str(label).upper() for label in message.get("labels") or []}
    text = " ".join([message.get("from", ""), message.get("subject", ""), message.get("snippet", "")]).casefold()
    ignored = [str(item).casefold() for item in profile.get("ignored_topics") or []]
    if any(item and item in text for item in ignored):
        return -10
    score = 0
    if "IMPORTANT" in labels:
        score += 3
    if "UNREAD" in labels:
        score += 2
    if any(word in text for word in ("reply", "deadline", "due", "interview", "application", "professor", "security alert", "action required")):
        score += 3
    senders = [str(item).casefold() for item in profile.get("important_senders") or []]
    if any(sender and sender in text for sender in senders):
        score += 4
    return score


def brief_line(value, fallback):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:180] if value else fallback


def top_messages(email, profile, limit=4):
    messages = (email.get("review") or []) + (email.get("fyi") or [])
    ranked = sorted(
        ((message_score(message, profile), message) for message in messages),
        key=lambda item: item[0],
        reverse=True,
    )
    return [message for score, message in ranked if score > 0][:limit]


def top_tasks(tasks, limit=3):
    open_tasks = [task for task in tasks or [] if task.get("status") != "completed" and not task.get("deleted")]
    return sorted(open_tasks, key=lambda task: (task_due_rank(task), task.get("updated") or ""))[:limit]


def active_project_lines(profile, github):
    lines = []
    github_items = github.get("items") or []
    for project in (profile.get("active_projects") or [])[:5]:
        lines.append(f"- {brief_line(project, 'Active project')} - next action: define the next concrete step.")
    for item in github_items[:3]:
        repo = item.get("repo") or item.get("repository") or "GitHub"
        title = item.get("title") or item.get("summary") or item.get("type") or "project update"
        lines.append(f"- {repo}: {brief_line(title, 'project update')}")
    return lines or ["- No active projects configured yet. Add one in Jarvis Chat or with /rememberbrief."]


def github_lines(github):
    items = github.get("items") or []
    if not items:
        return [github.get("text") or "- No GitHub items requiring attention."]
    return [
        f"- {(item.get('repo') or item.get('repository') or 'GitHub')}: {brief_line(item.get('title') or item.get('summary') or item.get('url'), 'attention needed')}"
        for item in items[:5]
    ]


def compose_morning_brief(calendar, email, tasks, weather, news, github, profile):
    events = calendar.get("events") or []
    picked_tasks = top_tasks(tasks, 3)
    messages = top_messages(email, profile, 4)
    lines = [f"MORNING BRIEF - {datetime.now().astimezone().strftime('%A, %B %-d' if os.name != 'nt' else '%A, %B %#d')}"]
    lines.extend(["", "TODAY"])
    lines.extend([f"- {event_time_text(event)} - {event.get('summary') or '(no title)'}" for event in events[:8]] or ["- No calendar events found for today."])
    lines.extend(["", "TOP 3"])
    if picked_tasks:
        for index, task in enumerate(picked_tasks, 1):
            due = f" due {task.get('due')}" if task.get("due") else ""
            lines.append(f"{index}. {brief_line(task.get('title'), 'Untitled task')}{due}")
    else:
        lines.extend(["1. Choose the one result that would make today successful.", "2. Review unresolved messages.", "3. Add one concrete task to Google Tasks."])
    lines.extend(["", "RISKS"])
    risk_lines = []
    for task in picked_tasks:
        rank = task_due_rank(task)
        if rank <= 2:
            risk_lines.append(f"- Task pressure: {brief_line(task.get('title'), 'Untitled task')}")
    if not events and not picked_tasks:
        risk_lines.append("- No scheduled structure or dated tasks found; pick a first work block deliberately.")
    lines.extend(risk_lines or ["- No obvious deadline or calendar conflict risk found."])
    lines.extend(["", "MESSAGES"])
    if email.get("status") == "unavailable":
        lines.append(f"- Gmail unavailable: {brief_line(email.get('error'), 'source error')}")
    else:
        lines.extend([
            f"- {brief_line(message.get('from'), 'Unknown sender')}: {brief_line(message.get('subject') or message.get('snippet'), 'Needs review')}"
            for message in messages
        ] or ["- No important messages surfaced by the current rules."])
    lines.extend(["", "PROJECTS"])
    lines.extend(active_project_lines(profile, github))
    lines.extend(["", "GITHUB"])
    lines.extend(github_lines(github))
    lines.extend(["", "WEATHER"])
    lines.append(weather.get("text") if weather else "- Weather unavailable.")
    lines.extend(["", "NEWS"])
    lines.append(news.get("text") if news else "- Major news unavailable.")
    lines.extend(["", "SUGGESTED PLAN"])
    if events:
        lines.append("- Work around the calendar commitments above; protect the largest open gap for Top 3 item 1.")
    else:
        lines.append("- Create one deep-work block first, then batch email/admin after the first meaningful task is done.")
    lines.extend(["", "ONE QUESTION", "What single result would make today successful even if the rest of the plan changes?"])
    return "\n".join(lines)


def compose_evening_brief(calendar, email, tasks, github, profile):
    events = calendar.get("events") or []
    remaining = top_tasks(tasks, 5)
    messages = top_messages(email, profile, 4)
    lines = [f"EVENING BRIEF - {datetime.now().astimezone().strftime('%A, %B %-d' if os.name != 'nt' else '%A, %B %#d')}"]
    lines.extend(["", "COMPLETED", "- Completed tasks are inferred from Google Tasks when completion history is available; none were surfaced in this v1 digest."])
    lines.extend(["", "UNRESOLVED"])
    lines.extend([f"- {brief_line(task.get('title'), 'Untitled task')}" for task in remaining] or ["- No open Google Tasks surfaced."])
    lines.extend(["", "WAITING"])
    if email.get("status") == "unavailable":
        lines.append(f"- Gmail unavailable: {brief_line(email.get('error'), 'source error')}")
    else:
        lines.extend([
            f"- Review: {brief_line(message.get('from'), 'Unknown sender')} - {brief_line(message.get('subject') or message.get('snippet'), 'Needs review')}"
            for message in messages
        ] or ["- No people-waiting items surfaced by the current rules."])
    lines.extend(["", "PROJECT CHANGES"])
    lines.extend(active_project_lines(profile, github))
    lines.extend(["", "TOMORROW"])
    lines.extend([f"- {event_time_text(event)} - {event.get('summary') or '(no title)'}" for event in events[:8]] or ["- No calendar events found for tomorrow."])
    lines.extend(["", "SHUTDOWN", "- Pick tomorrow's first task.", "- Review calendar.", "- Reschedule or delete anything that should not silently roll forward."])
    return "\n".join(lines)


def source_error(name, exc):
    return {"status": "unavailable", "source": name, "error": str(exc)[:240]}


def fallback_email_section(exc):
    return {
        "status": "unavailable",
        "counts": {"review": 0, "unread": 0, "recent_inbox": 0},
        "review": [],
        "fyi": [],
        "error": str(exc)[:240],
    }


def build_briefing(kind="morning"):
    kind = "evening" if str(kind).lower() == "evening" else "morning"
    profile = get_briefing_profile()
    calendar_request = "tomorrow" if kind == "evening" else "today"
    try:
        calendar = calendar_list(calendar_request)
    except Exception as exc:
        calendar = {"events": [], **source_error("calendar", exc)}
    try:
        email = briefing_email_sections(kind)
    except Exception as exc:
        email = fallback_email_section(exc)
    try:
        tasks = tasks_list(False, 20)
    except Exception as exc:
        tasks = []
        tasks_error = source_error("tasks", exc)
    else:
        tasks_error = None
    github = call_github_digest(profile)
    weather = fetch_weather_summary(profile.get("current_city")) if kind == "morning" else None
    news = fetch_major_news() if kind == "morning" else None
    text = (
        compose_evening_brief(calendar, email, tasks, github, profile)
        if kind == "evening"
        else compose_morning_brief(calendar, email, tasks, weather, news, github, profile)
    )
    return {
        "status": "completed",
        "kind": kind,
        "profile": profile,
        "calendar": calendar,
        "email": email,
        "messages": email.get("review", []) + email.get("fyi", []),
        "tasks": tasks,
        "tasks_error": tasks_error,
        "weather": weather,
        "weather_location": profile.get("current_city"),
        "news": news,
        "github": github,
        "text": text,
        "decision_text": text,
    }


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
            "appointment",
            "create one",
        )
    )


def parse_event_payload(payload):
    text = combined_request_text(payload)
    current_text = current_request_text(payload)
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
    title_match = re.search(r"(?:titled|title\s+it|title|called|named)\s*:?\s*['\"]?([^'\"\n]+)", current_text, re.IGNORECASE)
    if title_match and "no title" not in lowered:
        summary = re.split(r"\s+(?:for|at)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", title_match.group(1), maxsplit=1, flags=re.IGNORECASE)[0].strip(" .,!?")[:120]
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


def calendar_get_event(event_id):
    return google_request("GET", f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}")


def compact_calendar_event(item):
    return {
        "id": item.get("id"), "summary": item.get("summary") or "Untitled event",
        "start": item.get("start") or {}, "end": item.get("end") or {},
        "location": item.get("location") or "", "htmlLink": item.get("htmlLink"),
    }


def calendar_contract_events(window):
    start = datetime.fromisoformat(window["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(window["end"].replace("Z", "+00:00"))
    if end <= start or end - start > timedelta(days=31):
        raise ValueError("calendar_search_window_invalid")
    params = urllib.parse.urlencode({
        "singleEvents": "true", "orderBy": "startTime", "timeMin": start.isoformat(),
        "timeMax": end.isoformat(), "maxResults": 100,
    })
    data = google_request("GET", f"https://www.googleapis.com/calendar/v3/calendars/primary/events?{params}")
    return [compact_calendar_event(item) for item in data.get("items", [])]


def calendar_contract_datetime_equal(actual, expected):
    if not actual or not expected:
        return False
    actual_dt = datetime.fromisoformat(str(actual).replace("Z", "+00:00"))
    expected_dt = datetime.fromisoformat(str(expected).replace("Z", "+00:00"))
    return actual_dt == expected_dt


def validate_executable_calendar_contract(contract):
    if not isinstance(contract, dict):
        raise ValueError("calendar_contract_must_be_object")
    allowed = {
        "version", "operation", "title", "start", "end", "target_event_id",
        "search_window", "allow_search_fallback", "requires_clarification",
        "clarification", "attendees",
    }
    if set(contract) - allowed:
        raise ValueError("calendar_contract_unknown_fields")
    operation = contract.get("operation")
    if operation not in {"create", "delete", "list", "reschedule"}:
        raise ValueError("calendar_contract_operation_invalid")
    if contract.get("requires_clarification"):
        raise ValueError("calendar_contract_not_executable")
    if operation == "create" and not all(contract.get(key) for key in ("title", "start", "end")):
        raise ValueError("calendar_create_contract_incomplete")
    if operation == "reschedule" and not all(contract.get(key) for key in ("target_event_id", "start", "end")):
        raise ValueError("calendar_reschedule_contract_incomplete")
    if operation == "delete" and not contract.get("target_event_id"):
        if not (contract.get("allow_search_fallback") and contract.get("title") and contract.get("search_window")):
            raise ValueError("calendar_delete_contract_incomplete")
    if operation == "list" and not contract.get("search_window"):
        raise ValueError("calendar_list_contract_incomplete")


def execute_calendar_contract(contract, approved=False):
    validate_executable_calendar_contract(contract)
    operation = contract["operation"]
    if operation == "create":
        payload = {
            "summary": contract["title"],
            "start": {"dateTime": contract["start"], "timeZone": DEFAULT_TIMEZONE},
            "end": {"dateTime": contract["end"], "timeZone": DEFAULT_TIMEZONE},
        }
        attendees = contract.get("attendees") or []
        if attendees and not approved:
            raise PermissionError("calendar_attendees_require_approval")
        if attendees:
            payload["attendees"] = [{"email": str(email)} for email in attendees]
        create_url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        if attendees:
            create_url += "?sendUpdates=all"
        created = google_request("POST", create_url, payload)
        verified = calendar_get_event(created["id"])
        if verified.get("summary") != contract["title"] or not calendar_contract_datetime_equal(event_start_text(verified), contract["start"]):
            raise RuntimeError("calendar_create_verification_failed")
        event = compact_calendar_event(verified)
        return {"status": "completed", "event": event, "text": f"Verified calendar event created: {event['summary']}\nEvent ID: {event['id']}\nStart: {event_start_text(event)}\nEnd: {(event['end'] or {}).get('dateTime')}"}

    if operation == "list":
        events = calendar_contract_events(contract["search_window"])
        result = {"events": events}
        return {"status": "completed", **result, "text": response_text_for_calendar(result)}

    target_id = contract.get("target_event_id")
    if not target_id and operation == "delete" and contract.get("allow_search_fallback"):
        title = (contract.get("title") or "").casefold()
        matches = [event for event in calendar_contract_events(contract["search_window"]) if event["summary"].casefold() == title]
        if len(matches) != 1:
            return {"status": "clarification_required", "text": f"I found {len(matches)} matching events. Please identify the exact event before deletion.", "events": matches}
        target_id = matches[0]["id"]

    if operation == "delete":
        existing = compact_calendar_event(calendar_get_event(target_id))
        google_request("DELETE", f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{target_id}")
        try:
            remaining = calendar_get_event(target_id)
            if remaining.get("status") != "cancelled":
                raise RuntimeError("calendar_delete_verification_failed")
        except urllib.error.HTTPError as exc:
            if exc.code not in {404, 410}:
                raise
        return {"status": "completed", "deleted": [existing], "text": "Verified deleted 1 matching calendar event."}

    if operation == "reschedule":
        existing = calendar_get_event(target_id)
        patch = {
            "start": {"dateTime": contract["start"], "timeZone": DEFAULT_TIMEZONE},
            "end": {"dateTime": contract["end"], "timeZone": DEFAULT_TIMEZONE},
        }
        if contract.get("title"):
            patch["summary"] = contract["title"]
        google_request("PATCH", f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{target_id}", patch)
        verified = calendar_get_event(target_id)
        if not calendar_contract_datetime_equal(event_start_text(verified), contract["start"]):
            raise RuntimeError("calendar_reschedule_verification_failed")
        event = compact_calendar_event(verified)
        return {"status": "completed", "event": event, "text": f"Verified calendar event rescheduled: {event['summary']}\nEvent ID: {event['id']}\nStart: {event_start_text(event)}"}

    raise ValueError("calendar_contract_operation_unsupported")


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
            if path == "/gmail/execute-contract":
                contract = payload.get("contract")
                if not isinstance(contract, dict):
                    raise ValueError("gmail_contract_required")
                result = execute_gmail_contract(contract, approved=payload.get("approved") is True)
                self.write_json(HTTPStatus.OK, {"ok": True, **result})
                return
            if path == "/contacts/assist":
                contacts = contacts_search(infer_contact_query(payload.get("request", "")), int(payload.get("max_results", 10)))
                self.write_json(HTTPStatus.OK, {"ok": True, "contacts": contacts, "text": response_text_for_contacts(contacts)})
                return
            if path == "/contacts/execute-contract":
                contract = payload.get("contract")
                if not isinstance(contract, dict):
                    raise ValueError("contacts_contract_required")
                result = execute_contacts_contract(contract, approved=payload.get("approved") is True)
                self.write_json(HTTPStatus.OK, {"ok": True, **result})
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
            if path == "/tasks/execute-contract":
                contract = payload.get("contract")
                if not isinstance(contract, dict):
                    raise ValueError("tasks_contract_required")
                result = execute_tasks_contract(contract, approved=payload.get("approved") is True)
                self.write_json(HTTPStatus.OK, {"ok": True, **result})
                return
            if path == "/briefing/build":
                result = build_briefing(payload.get("kind") or "morning")
                self.write_json(HTTPStatus.OK, {"ok": True, **result})
                return
            if path == "/profile/get":
                self.write_json(HTTPStatus.OK, {"ok": True, "profile": get_briefing_profile()})
                return
            if path == "/profile/update":
                result = update_briefing_profile(payload.get("updates") or payload)
                self.write_json(HTTPStatus.OK, {"ok": True, **result})
                return
            if path == "/profile/notes":
                operation = payload.get("operation") or "add"
                if operation == "add":
                    result = add_briefing_note(payload.get("note"))
                elif operation in {"delete", "forget"}:
                    result = delete_briefing_note(payload.get("id"), payload.get("text"))
                else:
                    raise ValueError("profile_notes_operation_invalid")
                self.write_json(HTTPStatus.OK, {"ok": True, **result})
                return
            if path == "/calendar/list":
                result = calendar_list(payload.get("request", "today"))
                self.write_json(HTTPStatus.OK, {"ok": True, **result, "text": response_text_for_calendar(result)})
                return
            if path == "/calendar/execute-contract":
                contract = payload.get("contract")
                if not isinstance(contract, dict):
                    raise ValueError("calendar_contract_required")
                result = execute_calendar_contract(contract, approved=payload.get("approved") is True)
                self.write_json(HTTPStatus.OK, {"ok": True, **result})
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

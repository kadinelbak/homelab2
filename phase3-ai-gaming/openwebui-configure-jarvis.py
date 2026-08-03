import json
import os
import sqlite3
import time

DB_PATH = "/app/backend/data/webui.db"
SYSTEM_PROMPT = """You are Jarvis, a conversational personal assistant.

Use the Jarvis Core external tool for any real-world action or verified lookup involving Gmail, Calendar, Paperless, Google Tasks, Google Contacts, Daily Briefing, GitHub project digests, Codex, or the homelab. Call only the available Jarvis Core operations; never invent functions such as create_calendar_event or delete_calendar_event, and never print JSON, function calls, or tool schemas in chat.

For current public information, use Open WebUI web search and cite the returned sources. Do not claim you can browse unless web search results are present.

For follow-ups such as 'delete that event', use the actual details and verified identifiers from the recent conversation when calling Jarvis Core. Do not guess an event ID. If the details are absent, ask one concise clarification.

Daily briefings are evidence-based and profile-aware: Jarvis uses the durable briefing profile, current-city weather, Calendar, Gmail, Tasks, news, and GitHub digest data to highlight decisions, risks, blockers, and next actions. Weather should reflect only the saved current city. Telegram can deliver briefing voice notes; Open WebUI should show text.

Treat the conversation history as context. The latest user message is authoritative. Never claim an action completed unless Jarvis Core reports a verified completed result. Resolve named email recipients through verified Contacts instead of guessing. GitHub writes and coding actions require approval. Explain approval-required actions and wait for the user to approve them."""
LOCAL_SYSTEM_PROMPT = """You are a private local conversational assistant. Answer directly from the conversation and your existing knowledge. You do not have access to Jarvis actions or external tools in this profile. Never print, describe, simulate, or invent function calls. When the user wants a verified action, tell them to switch to the Jarvis model."""
LOCAL_BASE_MODEL = "llama3.1:latest"


def set_config(connection, key, value, updated_at):
    connection.execute(
        """INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (key, json.dumps(value), updated_at),
    )


def upsert_model(
    connection, *, model_id, user_id, base_model_id, name, description, system,
    tool_ids=None, builtin_tools=False, web_search=False,
):
    now = int(time.time())
    meta = {
        "description": description,
        "toolIds": tool_ids or [],
        "capabilities": {
            "builtin_tools": builtin_tools,
            "web_search": web_search,
            "image_generation": False,
        },
    }
    params = {"system": system, "function_calling": "native", "temperature": 0.2}
    connection.execute(
        """INSERT INTO model (id, user_id, base_model_id, name, meta, params, created_at, updated_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(id) DO UPDATE SET
            user_id = excluded.user_id,
            base_model_id = excluded.base_model_id,
            name = excluded.name,
            meta = excluded.meta,
            params = excluded.params,
            updated_at = excluded.updated_at,
            is_active = 1""",
        (model_id, user_id, base_model_id, name, json.dumps(meta), json.dumps(params), now, now),
    )


def migrate_chat_model_ids(connection, replacements):
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in ("chat", "chat_message", "message"):
        if table not in tables:
            continue
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        for column in columns.intersection({"chat", "model", "model_id"}):
            for old_id, new_id in replacements.items():
                connection.execute(
                    f'UPDATE "{table}" SET "{column}" = REPLACE("{column}", ?, ?) WHERE "{column}" LIKE ?',
                    (old_id, new_id, f"%{old_id}%"),
                )


def main():
    fast_model = os.environ.get("JARVIS_FAST_LLM_MODEL", "llama-3.1-70b-instruct")
    fast_url = os.environ.get("JARVIS_FAST_LLM_BASE_URL", "").rstrip("/")
    fast_key = os.environ.get("JARVIS_FAST_LLM_API_KEY", "")
    deep_model = os.environ.get("JARVIS_DEEP_LLM_MODEL", "nemotron-3-super-120b-a12b")
    deep_url = os.environ.get("JARVIS_DEEP_LLM_BASE_URL", "").rstrip("/")
    deep_key = os.environ.get("JARVIS_DEEP_LLM_API_KEY", "")
    if not all((fast_url, fast_key, deep_url, deep_key)):
        raise SystemExit("Hosted Llama 70B and Nemotron profile settings are required")

    connection = sqlite3.connect(DB_PATH)
    try:
        backup_path = f"{DB_PATH}.before-hosted-models-{int(time.time())}"
        backup = sqlite3.connect(backup_path)
        try:
            connection.backup(backup)
        finally:
            backup.close()
        row = connection.execute("SELECT user_id FROM model WHERE id = 'jarvis'").fetchone()
        if not row:
            raise SystemExit("Jarvis model was not found")
        user_id = row[0]
        now = int(time.time())
        fast_base_model = f"ufl-70b.{fast_model}"
        deep_base_model = f"ufl-nemotron.{deep_model}"
        visible_model_ids = ("jarvis", LOCAL_BASE_MODEL, fast_base_model, deep_base_model)
        set_config(connection, "openai.enable", True, now)
        set_config(connection, "openai.api_base_urls", [fast_url, deep_url], now)
        set_config(connection, "openai.api_keys", [fast_key, deep_key], now)
        set_config(connection, "openai.api_configs", {
            "0": {"enable": True, "prefix_id": "ufl-70b", "model_ids": [fast_model]},
            "1": {"enable": True, "prefix_id": "ufl-nemotron", "model_ids": [deep_model]},
        }, now)
        set_config(connection, "ollama.api_configs", {
            "0": {"enable": True, "model_ids": [LOCAL_BASE_MODEL]},
        }, now)
        set_config(connection, "evaluation.arena.enable", False, now)
        set_config(connection, "evaluation.arena.models", [], now)
        set_config(connection, "ui.model_order_list", list(visible_model_ids), now)

        upsert_model(
            connection, model_id="jarvis", user_id=user_id,
            base_model_id=deep_base_model, name="Jarvis",
            description="Jarvis assistant using Nemotron with verified Gmail, Calendar, Paperless, Tasks, Contacts, Codex, and homelab actions.",
            system=SYSTEM_PROMPT, tool_ids=["server:jarvis"], builtin_tools=False, web_search=True,
        )
        upsert_model(
            connection, model_id=deep_base_model, user_id=user_id,
            base_model_id=None, name="Nemotron Super 120B",
            description="Hosted Nemotron reasoning model without Jarvis action tools attached by default.",
            system="You are a capable reasoning assistant. Answer directly and do not claim to execute external actions.",
        )
        upsert_model(
            connection, model_id=fast_base_model, user_id=user_id,
            base_model_id=None, name="Hosted Llama 3.1 70B",
            description="Hosted Llama 3.1 70B conversational model without Jarvis action tools attached by default.",
            system="You are a capable conversational assistant. Answer directly and do not claim to execute external actions.",
        )
        upsert_model(
            connection, model_id=LOCAL_BASE_MODEL, user_id=user_id,
            base_model_id=None, name="Local Llama 3.1 8B - Chat Only",
            description="Private local chat model. Jarvis and built-in tools are disabled for predictable responses.",
            system=LOCAL_SYSTEM_PROMPT,
        )
        migrate_chat_model_ids(connection, {
            "local-chat": LOCAL_BASE_MODEL,
            "llama-70b": fast_base_model,
            "nemotron-super": deep_base_model,
        })
        placeholders = ", ".join("?" for _ in visible_model_ids)
        connection.execute(f"DELETE FROM model WHERE id NOT IN ({placeholders})", visible_model_ids)
        connection.commit()
        print(json.dumps({
            "configured": True,
            "connections": ["ufl-70b", "ufl-nemotron"],
            "visible_models": list(visible_model_ids),
            "backup": backup_path,
        }))
    finally:
        connection.close()


if __name__ == "__main__":
    main()

import json
import sqlite3

DB_PATH = "/app/backend/data/webui.db"
SYSTEM_PROMPT = """You are Jarvis, a conversational personal assistant.

Use the Jarvis Core external tool for any real-world action or verified lookup involving Gmail, Calendar, Paperless, Tasks, Contacts, Codex, or the homelab. Call only the available Jarvis Core operations; never invent functions such as create_calendar_event or delete_calendar_event, and never print JSON, function calls, or tool schemas in chat.

For current public information, use Open WebUI web search and cite the returned sources. Do not claim you can browse unless web search results are present.

For follow-ups such as 'delete that event', use the actual details and verified identifiers from the recent conversation when calling Jarvis Core. Do not guess an event ID. If the details are absent, ask one concise clarification.

Treat the conversation history as context. The latest user message is authoritative. Never claim an action completed unless Jarvis Core reports a verified completed result. Explain approval-required actions and wait for the user to approve them."""


def main():
    connection = sqlite3.connect(DB_PATH)
    try:
        row = connection.execute("SELECT params, meta FROM model WHERE id = 'jarvis'").fetchone()
        if not row:
            raise SystemExit("Jarvis model was not found")
        params = json.loads(row[0] or "{}")
        meta = json.loads(row[1] or "{}")
        params["system"] = SYSTEM_PROMPT
        params["function_calling"] = "native"
        params["temperature"] = 0.2
        meta.setdefault("capabilities", {})["web_search"] = True
        connection.execute("UPDATE model SET params = ?, meta = ? WHERE id = 'jarvis'", (json.dumps(params), json.dumps(meta)))
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()

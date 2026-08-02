# AI Orchestration Layer

The active orchestration layer is `ai-orchestrator`, a Phase 3 HTTP service for turning natural-language requests into structured, approval-aware action contracts and local Ollama fallback responses.

It does not require n8n. Jarvis Chat sends requests directly to `ai-orchestrator`, which routes requests to a capability, stores the planned action, and either executes a local Ollama response or prepares an approval-gated action proposal for a future worker service.

## Service

- Container: `ai_orchestrator`
- Compose profile: `orchestration`
- Internal URL: `http://ai-orchestrator:8095`
- Host URL over Tailscale: `http://<tailscale-host-or-ip>:8095`
- Data: `${DATA_PATH}/phase3-ai-gaming/data/ai-orchestrator`

## GUI

For day-to-day use, Open WebUI is the preferred long-context Jarvis frontend:

```text
http://<tailscale-host-or-ip>:8080
```

Register Jarvis Core in Open WebUI as a Global Tool Server from Admin Settings:

```text
http://jarvis-openwebui-tools:18400/openapi.json
```

The tool bridge is Docker-internal only. It keeps `AI_ORCHESTRATOR_TOKEN` server-side and exposes these OpenAPI tools to Open WebUI:

```text
jarvis_request
jarvis_get_request
jarvis_approve_action
jarvis_capabilities
jarvis_health
```

Recommended Open WebUI model/system prompt for a model named `Jarvis`:

```text
You are Jarvis, Kadin's personal homelab assistant. Use normal chat and Open WebUI memory for conversation, planning, and questions that do not need external action. Use Jarvis tools for Gmail, Calendar, Paperless, Tasks, Contacts, Codex, homelab, document, or verified worker actions. Never claim that an external action is done unless the Jarvis tool result says it is completed or verified. If Jarvis returns approval required, show the action ID and ask for explicit approval before using jarvis_approve_action. Telegram remains available for mobile voice and document uploads. Jarvis Chat remains available as the debugging/admin console.
```

Jarvis Chat remains available as a debugging/admin console:

```text
http://<tailscale-host-or-ip>:18100
```

Jarvis Chat is a small request console that sends requests directly to `ai-orchestrator`, shows the planned action, and gives you Approve and Queue Execution buttons.

Jarvis Chat now behaves like a lightweight chat for assistant and drafting requests. Level-0 assistant requests execute through local Ollama and return text directly. Higher-level actions still show an approval flow, then fall back to a local Ollama action proposal until a dedicated connector is wired.

## Telegram

The `telegram-bridge` service provides a phone-friendly text and voice-note interface. It uses Telegram long polling, so no public inbound webhook or extra exposed port is required.

Set these values in `.env`:

```text
JARVIS_TELEGRAM_BOT_TOKEN=<token from BotFather>
JARVIS_TELEGRAM_ALLOWED_CHAT_IDS=<optional comma-separated chat ids>
JARVIS_TELEGRAM_BOT_URL=https://t.me/<your_bot_username>
```

If `JARVIS_TELEGRAM_ALLOWED_CHAT_IDS` is blank, any chat that can message the bot is accepted. For private use, set it after sending `/health` once and checking the bridge logs for the chat id.

Supported commands:

```text
/start
/help
/health
/approve act-...
/forget
```

Text messages, including phone/Telegram voice typing, go directly to Jarvis Core. Telegram voice-note and audio attachments are not transcribed; use Open WebUI for uploaded-audio transcription through `whisper-worker`. Document uploads are saved into Paperless' consume folder so Paperless can OCR/import them; Jarvis verifies the file was queued, waits briefly to see whether Paperless picked it up, then polls the Paperless API until the imported document appears or the import wait expires. The bridge keeps durable per-chat memory in `${DATA_PATH}/phase3-ai-gaming/data/telegram-bridge`: recent turns are authoritative, while older turns are summarized only to resolve references such as "that event." Use `/forget` to start fresh context for the current chat.

## Google Tools

The `google-tools-worker` service is the Gmail and Google Calendar connector. It exposes a Tailscale-bound OAuth callback on port `18200` and stores the Google refresh token under the homelab data path.

Set these values in `.env`:

```text
GOOGLE_CLIENT_ID=<Google OAuth client id>
GOOGLE_CLIENT_SECRET=<Google OAuth client secret>
GOOGLE_REDIRECT_URI=http://localhost:18200/oauth/google/callback
```

Start the OAuth flow with an SSH tunnel from your workstation:

```bash
ssh -L 18200:100.79.132.39:18200 kelbakkouri@kadin-main-sys
```

Then open:

```text
http://localhost:18200/oauth/google/start
```

After consent, Google redirects back to localhost through the tunnel and Jarvis stores the refresh token.

Current Google worker endpoints:

```text
GET  /health
GET  /oauth/google/start
GET  /oauth/google/callback
POST /gmail/search
POST /gmail/assist
POST /gmail/create-draft
POST /contacts/assist
POST /tasks/assist
POST /calendar/list
POST /calendar/assist
```

Contacts and Tasks require enabling the People API and Google Tasks API in Google Cloud, then rerunning the Google OAuth flow because the worker requests additional scopes.

## Codex Worker

The `codex-worker` service is the approval-gated coding backend for Jarvis. Jarvis Core routes repo/code/test/debug requests to the `edit_repository` capability, but execution still requires approval before the worker runs.

Runtime shape:

```text
Telegram / Jarvis Chat -> ai-orchestrator -> approval gate -> codex-worker -> /workspace
```

Useful endpoints:

```text
GET  http://<tailscale-host-or-ip>:18300/health
POST http://<tailscale-host-or-ip>:18300/run
```

The worker stores per-action artifacts under `${DATA_PATH}/phase3-ai-gaming/data/codex-worker/jobs`. Its Codex home/auth directory is mounted at `${DATA_PATH}/phase3-ai-gaming/data/codex-home`. The workspace mount is intentionally limited to Phase 3 Jarvis service code plus `phase3-ai-gaming/docker-compose.yml`; the root homelab `.env` is not mounted into Codex.

Required configuration:

```env
CODEX_COMMAND_PREFIX=codex exec --json --sandbox workspace-write --ask-for-approval never
CODEX_WORKER_TIMEOUT_SECONDS=1800
```

Codex should be authenticated with the ChatGPT sign-in flow inside the worker, not with an API key:

```bash
docker exec -it jarvis_codex_worker codex logout
docker exec -it jarvis_codex_worker codex login
```

Safety rules:

- Jarvis coding actions are approval-gated.
- The worker prompt instructs Codex to stay inside `/workspace`.
- The worker must not push, publish, or expose secrets.
- If Codex CLI is missing or not authenticated, the worker returns `worker_not_configured` instead of pretending it completed work.

## Model Tiers

The orchestrator uses local Ollama first for routing, then attaches an execution profile to each planned action:

```text
local      Ollama llama3.1:latest for cheap routing and fallback
fast_70b   External 70B-style model for drafting, summaries, and normal planning
deep_120b  External larger reasoning model for architecture, coding plans, and complex decomposition
```

UF LiteLLM/OpenAI-compatible profiles use:

```text
JARVIS_FAST_LLM_BASE_URL=https://api.ai.it.ufl.edu/v1
JARVIS_DEEP_LLM_BASE_URL=https://api.ai.it.ufl.edu/v1
JARVIS_DEEP_LLM_MODEL=nemotron-3-super-120b-a12b
```

External model keys belong only in `.env`, never in tracked files. Set:

```text
JARVIS_FAST_LLM_BASE_URL
JARVIS_FAST_LLM_API_KEY
JARVIS_DEEP_LLM_BASE_URL
JARVIS_DEEP_LLM_API_KEY
```

## Workflow Levels

Every planned action receives a workflow level:

```text
L0 answer_only            Conversational response, no external state change
L1 draft_or_plan          Creates a plan or draft action contract
L2 homelab_state_change   May change homelab/home state, approval required
L3 external_or_spend      May publish, spend, or use metered external workers
L4 danger_zone            Destructive/sensitive requests, manual review
```

## Voice

The `whisper-worker` service exposes speech-to-text:

```text
GET  http://<tailscale-host-or-ip>:18101/health
POST http://<tailscale-host-or-ip>:18101/transcribe
```

For upload requests, send `multipart/form-data` with an `audio` file field. Jarvis Chat includes a **Transcribe Audio** control that calls the worker, inserts the transcript into the message box, and shows the transcript in chat.

## n8n Archive

n8n is no longer in the active Jarvis request path. Old workflow experiments are archived under:

```text
docs/n8n-archive/
```

The `n8n` Compose profile remains available for separate automation experiments, but the `orchestration` profile starts Jarvis without n8n.

## Endpoints

```text
GET  /health
GET  /capabilities
POST /requests
GET  /requests/{request_id}
POST /actions/{action_id}/approve
POST /actions/{action_id}/execute
```

All endpoints except `/health` and `/capabilities` require:

```text
Authorization: Bearer <AI_ORCHESTRATOR_TOKEN>
```

## Example Request

```bash
curl -s http://localhost:8095/requests \
  -H "Authorization: Bearer $AI_ORCHESTRATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "request": "Add a project filtering control to my portfolio repo",
    "limits": {
      "maximum_runtime_seconds": 1800,
      "maximum_cost_usd": 1.00
    },
    "permissions": {
      "may_execute": false,
      "may_publish": false
    }
  }'
```

The response includes one planned action. Approve it before execution handoff:

```bash
curl -s -X POST http://localhost:8095/actions/<action_id>/approve \
  -H "Authorization: Bearer $AI_ORCHESTRATOR_TOKEN"

curl -s -X POST http://localhost:8095/actions/<action_id>/execute \
  -H "Authorization: Bearer $AI_ORCHESTRATOR_TOKEN"
```

When a dedicated worker is not implemented yet, execution returns a local Ollama fallback draft or action proposal. The next step is to add real connectors for email, calendar, tasks, contacts, expenses, coding, CAD, Home Assistant, and media actions.

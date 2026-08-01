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

For day-to-day use, open Jarvis Chat:

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
```

If `JARVIS_TELEGRAM_ALLOWED_CHAT_IDS` is blank, any chat that can message the bot is accepted. For private use, set it after sending `/health` once and checking the bridge logs for the chat id.

Supported commands:

```text
/start
/help
/health
/approve act-...
```

Text messages go directly to Jarvis Core. Voice notes are downloaded from Telegram, transcribed through `whisper-worker`, then sent to Jarvis Core as text.

## Model Tiers

The orchestrator uses local Ollama first for routing, then attaches an execution profile to each planned action:

```text
local      Ollama llama3.1:latest for cheap routing and fallback
fast_70b   External 70B-style model for drafting, summaries, and normal planning
deep_120b  External larger reasoning model for architecture, coding plans, and complex decomposition
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

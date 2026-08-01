# AI Orchestration Layer

The first orchestration slice is `ai-orchestrator`, a Phase 3 HTTP service for turning natural-language requests into structured, approval-aware action contracts.

It does not run Codex, Meshy, Home Assistant, or CAD tools directly yet. It routes requests to a capability, stores the planned action, and exposes approval and execution handoff endpoints for n8n or future worker services.

## Service

- Container: `ai_orchestrator`
- Compose profile: `orchestration`
- Internal URL: `http://ai-orchestrator:8095`
- Host URL over Tailscale: `http://<tailscale-host-or-ip>:8095`
- Data: `${DATA_PATH}/phase3-ai-gaming/data/ai-orchestrator`

## GUI

n8n is the recommended first GUI for orchestration. Use it for intake forms, webhook triggers, approvals, notifications, and visible workflow editing. Keep durable policy decisions, action contracts, and worker boundaries in `ai-orchestrator` code so the visual workflow cannot accidentally become an unrestricted super-agent.

Import this workflow into n8n:

```text
docs/n8n/ai-orchestrator-workflow.json
```

Or import it on the server with the one-shot Compose importer:

```bash
cd phase3-ai-gaming
docker compose --env-file ../.env --profile orchestration up n8n-import-ai-workflows
```

Then open n8n over Tailscale:

```text
http://<tailscale-host-or-ip>:5678
```

The workflow exposes three webhooks:

```text
POST /webhook/jarvis/request
POST /webhook/jarvis/action/approve
POST /webhook/jarvis/action/execute
```

n8n receives `AI_ORCHESTRATOR_URL` and `AI_ORCHESTRATOR_TOKEN` from Compose, then calls the internal orchestrator service.

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

Execution currently marks the action `queued_for_worker`. The next step is to add dedicated workers for `coding_worker`, `meshy`, `cad_worker`, `homeassistant`, and `media_adapter`.

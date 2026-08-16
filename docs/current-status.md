# Current Status

## Completed

- Restored the local checkout from `https://github.com/kadinelbak/homelab2.git`.
- Added Phase 3 `jarvis-core` as a durable FastAPI service while keeping `ai-orchestrator`, Jarvis Chat, Telegram, Google tools, Codex, Whisper, and TTS paths intact.
- Added PostgreSQL-backed records for requests, intents, proposed actions, approvals, execution attempts/results, verification, audit events, outbox events, model invocations, notifications, calendar events, projects, and tasks.
- Added central risk levels, approval enforcement, idempotent request creation, health/readiness/metrics endpoints, tools registry, Personal Ops projects/tasks/capture, and deterministic daily brief.
- Registered media and homelab tool boundaries for follow-on integrations.
- Added `jarvis_core` database bootstrap to Phase 1 Postgres init.
- Added Compose, Homepage, and `services.yaml` metadata.
- Kept Gluetun unchanged. The live host already uses host port `8097`, so Jarvis Core maps `127.0.0.1:18097 -> 8097`.

## Live Homelab State

- SSH host: `kadin-main-sys`
- Running container: `jarvis_core`
- Live health: `http://127.0.0.1:18097/health`
- Current live response: `{"ok":true,"service":"jarvis-core"}`
- Jarvis Core has the real Google Tools worker URL/token configured and can resolve `google-tools-worker:18200`.
- Jarvis Core has the Navigator/OpenAI-compatible fast and deep model env vars copied from `open_webui`.
- Ollama is now optional and is no longer part of the default Jarvis dependency chain. Normal Jarvis deploys use Navigator/OpenAI-compatible API model profiles and should use `--no-deps` for targeted restarts.
- Jarvis Chat is intended to bind to the homelab Tailscale IP through `JARVIS_CHAT_BIND_IP`, so Homepage can open `/core` from tailnet clients without exposing the service on all host interfaces.

## Real Service Checks

- `GET /api/v1/models/health` succeeds and reports both profiles configured:
  - fast: `llama-3.1-70b-instruct`
  - deep: `nemotron-3-super-120b-a12b`
- `POST /api/v1/models/generate` succeeds for both profiles and writes `jarvis_model_invocations` rows.
- Google Calendar is wired to the real `jarvis_google_tools` worker with simulated fallback disabled.
- Google OAuth was refreshed successfully after registering the localhost redirect URI.
- Read-only Google checks passed:
  - Calendar list and Calendar contract list
  - Gmail `search_messages`
  - Google Tasks list
  - People/Contacts search
- Real Calendar approval slice passed through Jarvis Core:
  - Request: `Schedule 90 minutes on Tuesday evening to prepare for my EnMed interview.`
  - Approval: granted through `/api/v1/approvals/{id}/decision`
  - Event: `Prepare for my EnMed interview`
  - Google event ID: `gv7932jf2utsj2d8l8qu2p1phg`
  - Time: `2026-08-11T18:00:00-04:00` to `2026-08-11T19:30:00-04:00`
  - Verification: Jarvis Core execution result and direct Google Calendar read-back both matched.
- Phase 4 Personal Operations is deployed:
  - Projects now support detail views with related tasks and evidence.
  - Tasks support create, list, update, and complete flows.
  - Unified capture routes calendar requests, portfolio/evidence notes, homelab/maintenance notes, and default tasks.
  - Portfolio evidence records are stored in `personal_ops_evidence`.
  - Homelab maintenance records are stored in `personal_ops_maintenance_records`.
  - Daily briefs combine real Google briefing data with Jarvis Core tasks, pending approvals, recent evidence, and open maintenance records.
  - Saved daily brief snapshots are stored in `personal_ops_daily_briefs`.
  - Live DB migration is at `0003_automation_runs`.
- Jarvis Core automation run history is deployed:
  - Automation runs are stored in `personal_ops_automation_runs`.
  - Core owns a conservative in-process runner for daily briefs, Gmail inbox organization, homelab health, Pi-hole/DNS health, and Drive migration scan status.
  - Automation cards show last run, next run, last status, and safe output.
  - Manual "run now" is available from the automation detail drawer.
  - Gmail inbox organization is automatic and safe-scoped: it applies Jarvis labels, stars likely reply/interview items, and archives newsletter/promotional mail by removing `INBOX`. It never applies spam/junk/trash labels.
- Local `Hey Jarvis` compatibility is wired through Jarvis Chat:
  - The laptop voice client still only needs the existing Jarvis Chat tunnel on `127.0.0.1:18100`.
  - Jarvis Chat routes Phase 4 voice requests to Jarvis Core internally.
  - Live smoke tests passed for daily brief, task capture, evidence capture, and homelab maintenance capture through `/api/voice/request`.
- Open WebUI tool compatibility now exposes Jarvis Core routes:
  - Core capture
  - Core daily brief
  - Read-only homelab diagnostics
  - Approval-gated Codex coding task proposals
  - Codex task dashboard
  - Projects, tasks, evidence, maintenance
  - Approvals, executions, and audit search
  - Daily brief recommendation actions
- Read-only homelab diagnostics are live at `/api/v1/homelab/diagnostics`.
  - Current check set includes Postgres, Redis, Jarvis Core, Google Tools, Codex Worker, Open WebUI, Ollama, Whisper, TTS, Homepage, Pi-hole, Paperless, Nextcloud, media automations, and container-local storage paths.
  - Ollama is reported as optional/offline when it is not running; it does not make overall diagnostics fail.
  - Media automation reachability is now included for Prowlarr, Bazarr, Sonarr, Radarr, Lidarr, Readarr, and qBittorrent without changing Gluetun bindings. These checks are optional until the media pipeline is ready.
- Private DNS and ad blocking are live through Pi-hole:
  - DNS listens on the homelab Tailscale IP at `100.79.132.39:53`.
  - Admin UI is available at `http://100.79.132.39:8053/admin`.
  - Upstream DNS uses CleanBrowsing Adult Filter (`185.228.168.10`, `185.228.169.11`) as a second layer for explicit adult-content filtering while avoiding the broader overblocking of family/kids presets.
  - Validation: `google.com`, `nih.gov`, `mayoclinic.org`, and `plannedparenthood.org` resolve; an explicit adult-domain test returns no usable answer.
  - The service is in Phase 1 core infrastructure and appears in Homepage/Core diagnostics.
  - It is not bound as a public resolver and does not change Gluetun.
- Telegram brief delivery was repaired:
  - The Telegram bridge now uses stable external DNS resolvers.
  - Notification delivery only marks an item delivered if at least one allowed chat ID was actually sent to.
  - Live validation delivered a generated evening brief notification and Gmail organizer notification.
- Drive migration destination workflow is live:
  - Nextcloud WebDAV visibility is verified after approved imports.
  - Paperless import proposals queue staged Drive documents into the Paperless consume folder after approval.
  - Paperless suggested tags include education, medical, finance, lifeadmin, and drive-migration.
  - Google Drive originals are not moved, archived, deleted, or modified.
- Gmail cleanup workflow is live:
  - Read-only summary reports top senders, old unread mail, likely newsletters, and likely needs-reply messages.
  - Approval-gated classification can create/apply sensible labels under `Jarvis/...`, including `Jarvis/Needs Reply`, `Jarvis/Newsletters`, `Jarvis/Needs Review`, `Jarvis/Finance`, `Jarvis/Education`, and `Jarvis/Work`.
  - No Gmail archive, read-state, star, label, send, or delete action runs without a Core approval.
- Automation cards now include daily briefs, Gmail needs-reply scan, homelab health check, Drive migration scan, and Pi-hole/DNS health check with last run, next run, summary, and last output fields where available.
- Media automation status is live:
  - Core endpoint: `/api/v1/media/automations/status`
  - Jarvis Chat/Homepage summary proxy: `/api/media/automations/summary`
  - Open WebUI tool route: `/jarvis/core/media-automations`
  - Voice route: ask `Hey Jarvis` for `media automation status`.
  - Homepage has a Media Automation Status widget above the individual service links.
- Codex coding task proposals are live:
  - Voice path: `Hey Jarvis` -> Jarvis Chat -> Jarvis Core -> approval required.
  - Open WebUI path: `jarvis_core_codex_task` -> Jarvis Core -> approval required.
  - Codex worker reports the Codex CLI is configured.
  - Execution remains approval-gated because coding tasks can edit mounted workspace files.
- Voice approval shortcuts are live:
  - `what approvals are pending`
  - `approve <matching title>`
  - Ambiguous matches return a shortlist instead of executing.
- Daily brief actions are live:
  - Recommendations can become Core tasks directly.
  - Calendar holds route through the existing approval-gated Calendar workflow.
- Jarvis Chat Core console is live:
  - Browser path: `http://127.0.0.1:18100/core` through the existing Jarvis Chat tunnel.
  - It shows pending Core approvals, Codex Core tasks, Codex worker jobs, diagnostics, tasks, evidence, maintenance, daily brief, and recent audit entries.
  - It does not require manually calling Core APIs.
  - Dashboard items are clickable and open a shared detail drawer.
  - Approvals can be approved/rejected with browser confirmation.
  - Tasks can be completed/reopened, and maintenance records can be resolved/reopened.
  - Codex worker jobs open request/stdout/stderr previews and paths.
  - Daily brief entries can become Core tasks or approval-gated calendar holds.
- Codex artifact browser is live through Jarvis Chat:
  - Job list: `/api/codex/jobs`
  - Job detail: `/api/codex/jobs/{job_id}`
  - Artifact text: `/api/codex/jobs/{job_id}/artifact?name=request.json|summary.json|stdout.txt|stderr.txt`
  - Artifact responses include the worker job paths plus concise stdout/stderr previews.
  - Codex worker jobs now record durable `summary.json` files with mode, status, changed files, test-result lines, and concise stdout/stderr previews.
  - Codex worker supports `inspect-only`, `plan-only`, `patch-only`, `test-only`, and `execute` modes.
  - Codex worker retention preserves `summary.json` and trims old stdout/stderr logs after `CODEX_WORKER_RETENTION_DAYS`.
- Voice approval hardening is live:
  - For normal low-risk approvals, `approve <title>` can approve by title match.
  - For Codex/code-executing, sensitive, or destructive approvals, `approve <title>` only reads back the risk and asks for a second phrase.
  - The required second phrase is `confirm approve <title>`.
  - No Codex coding task has been executed during validation.
- Voice task editing is live:
  - `complete task <title>`
  - `confirm complete task <title>`
  - `reopen task <title>`
  - `confirm reopen task <title>`
  - `resolve maintenance <title or service>`
  - `confirm resolve maintenance <title or service>`
  - `reopen maintenance <title or service>`
  - `confirm reopen maintenance <title or service>`
- Notification routing foundation is live:
  - Core notifications are stored in `jarvis_notifications`.
  - Important approvals, Codex results/failures, and saved daily briefs create shared notification records and outbox events.
  - Jarvis Chat Core console shows notifications as clickable dashboard items.
  - Telegram Bridge polls pending `telegram` notifications from Jarvis Core and marks delivery status after send.
  - `Hey Jarvis` voice requests can read pending `voice` notifications and mark them delivered.
  - Homepage reads a redacted Jarvis notification summary through Jarvis Chat at `/api/core/notifications/summary`.
- Portfolio evidence packet builder is live:
  - `POST /api/v1/evidence/packet`
  - The packet collects Core tasks, evidence, maintenance, recorded calendar events, Codex Worker git commits, and Google Drive/Docs references into a durable evidence record.
  - Codex Worker exposes read-only git commit metadata at `/git/commits` and uses a read-only `.git` mount for the main homelab repo.
  - Google Drive metadata search is implemented at Google Tools `/drive/search`; live smoke now succeeds with `drive.metadata.readonly`.
- Google Drive de-Google planning is live:
  - Core Drive inventory: `POST /api/v1/drive/inventory`
  - Core migration plan: `POST /api/v1/drive/migration-plan`
  - Jarvis Chat dashboard shows a Drive Inventory panel at `/core`.
  - `Hey Jarvis` can answer `Google Drive inventory` and `Google Drive migration plan`.
  - Open WebUI tool routes are `/jarvis/core/drive-inventory` and `/jarvis/core/drive-migration-plan`.
  - Current mode is metadata-only; no files are downloaded, exported, modified, or deleted.

## Google OAuth

The Google worker is intentionally bound to localhost. For future re-authentication, use an SSH tunnel from Windows:

```powershell
ssh -L 18200:127.0.0.1:18200 kadin-main-sys
```

Then open:

```text
http://127.0.0.1:18200/oauth/google/start
```

The callback should show:

```text
Jarvis Google authorization complete. You can close this tab.
```

Then test a read-only Calendar path before any writes:

```bash
TOKEN="$(grep -m1 '^AI_ORCHESTRATOR_TOKEN=' /home/kadin/homelab2/.env | cut -d= -f2-)"
curl -sS -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"request":"today"}' \
  http://127.0.0.1:18200/calendar/list
```

## Local Validation

```powershell
python -m unittest discover phase3-ai-gaming/jarvis-core/tests
python -m unittest discover phase3-ai-gaming/tests -p "test_voice_client.py"
python -m compileall phase3-ai-gaming\jarvis-core\jarvis_core
```

Both passed.

## Remaining Work

- Implement media pipeline HTTP calls for `media.social_image.create`, `media.workflow.status`, `media.workflow.approve_step`, and `media.gallery.list` after the media pipeline is ready.
- Add approval-gated Drive export/download batches only when ready to temporarily request broader Drive read scope.
- Add richer Codex artifact summarization after real coding jobs accumulate.

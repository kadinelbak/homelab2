# Jarvis Future Capabilities

## Near Term

- Completed: Codex task dashboard lists proposed, running, completed, and failed coding tasks with worker artifacts.
- Completed: Voice approval shortcuts let `Hey Jarvis` read pending approvals and approve a specific action by matching title text.
- Completed: Homelab diagnostics include read-only checks for Postgres, Redis, Open WebUI, Ollama, Google Tools, Codex Worker, Whisper, TTS, Homepage, and storage paths visible to Core.
- Completed: Open WebUI Core tools expose projects, tasks, evidence, maintenance, approvals, executions, and audit search as first-class tools.
- Completed: Daily brief actions turn recommendations into tasks or approval-gated calendar holds.
- Completed: Jarvis Chat Core console shows Core approvals, Codex jobs, diagnostics, tasks, evidence, maintenance, audit entries, and daily briefs without manual API calls.
- Completed: Approval confirmation hardening requires a second spoken confirmation for destructive, sensitive, or code-executing approvals.
- Completed: Codex artifact browser shows request/stdout/stderr paths and concise summaries from the Codex worker job directory.

## Medium Term

- Completed: Jarvis Chat Core console detail drawer supports clickable approvals, Codex jobs, diagnostics, tasks, evidence, maintenance, daily brief, and audit entries.
- Completed: Jarvis Chat Core console approve/reject buttons use explicit browser confirmation prompts and refresh after action.
- Completed: Jarvis Chat Core console task complete/reopen, maintenance resolve/reopen, Codex artifact viewing, and daily brief task/calendar-hold actions.
- Completed: Codex worker modes support inspect-only, plan-only, patch-only, test-only, and execute modes before write execution.
- Completed: Codex artifact summaries store durable summaries, changed-file lists, and test-result lines after coding jobs.
- Completed: Codex job retention policy preserves request metadata and `summary.json` while trimming old stdout/stderr logs.
- Completed: Voice task editing can complete/reopen tasks and resolve/reopen maintenance records by spoken title with confirmation.
- Completed: Portfolio evidence builder collects Core calendar events, tasks, evidence, maintenance, Codex Worker git commits, and Google Drive/Docs metadata references into structured evidence packets.
- Completed: Notification routing stores important approvals, Codex results/failures, and daily briefs for Homepage/Jarvis Chat surfaces.
- Completed: Notification routing delivers stored notifications outward to Telegram, `Hey Jarvis` voice readout, and a Homepage custom API widget.
- Completed: Media automation stack status is visible in Homepage, Jarvis Core diagnostics, Open WebUI tools, and `Hey Jarvis` voice readout without changing Gluetun bindings.
- Completed: Google Drive API/consent works with the read-only `drive.metadata.readonly` scope.
- Completed: Drive inventory and migration planner produce metadata-only de-Google plans across Jarvis Core, Jarvis Chat, Open WebUI tools, and `Hey Jarvis`.
- Next: Add approval-gated Drive export/download batches only after explicitly requesting temporary broader Drive read scope.

## Later

- Media pipeline integration after the service is ready: image generation, workflow status, approval steps, and gallery browsing.
- Home Assistant tools: read-only state first, then approval-gated device actions.
- Personal knowledge retrieval: index local notes, docs, project history, and evidence records for grounded answers.
- Proactive maintenance: scheduled health checks that create maintenance records when services degrade.
- Multi-agent coding workflows: one agent plans, one edits, one reviews, and one runs tests, all through the same Core approval/audit layer.

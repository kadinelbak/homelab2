# AGENTS.md

## Goal

Minimize context usage and token consumption.

Only read, analyze, or modify files directly related to the current task.

## Repository Exploration

Before opening files:

1. Use `rg` or targeted file search.
2. Identify likely relevant files.
3. Open the smallest number of files necessary.

Do not scan the entire repository unless explicitly requested.

## Files Never To Read

Ignore these unless specifically requested:

- `node_modules/`
- `.git/`
- `dist/`
- `build/`
- `out/`
- `.next/`
- `coverage/`
- `logs/`
- `backups/`
- `vendor/`
- `cache/`
- `tmp/`

For homelab projects also ignore:

- Immich media storage
- Paperless document storage
- Database dumps
- Grafana data
- Prometheus data
- Loki data
- service data directories under `${DATA_PATH}`

## File Reading Rules

Read files incrementally.

Do not open large files in full.

When inspecting a file:

- Read only relevant sections.
- Read surrounding context only when needed.
- Avoid loading files larger than 500 lines unless required.

## Command Output Rules

Never generate excessive terminal output.

Prefer:

- `tail`
- `head`
- `grep`
- `rg`
- targeted `docker inspect --format`

Avoid dumping entire files or unrestricted logs.

Examples:

Good:

```bash
tail -n 100 logfile.log
```

Good:

```bash
journalctl -n 100
```

Bad:

```bash
cat logfile.log
```

Bad:

```bash
docker logs container
```

## Docker Rules

Do not inspect all containers unless explicitly requested.

Only inspect containers directly related to the task.

Do not dump full logs.

Use:

```bash
docker logs --tail 100 container
```

instead of unrestricted logs.

When possible, filter logs with task-specific terms and redact secrets.

## Testing Rules

Run the smallest test scope possible.

Prefer:

- Single-file tests
- Single-component tests
- Single-function tests
- Targeted health checks for the changed service

Avoid full test suites unless requested.

## Search Strategy

Search before reading.

Prefer:

1. `rg`
2. targeted file opens
3. targeted edits

Avoid broad repository exploration.

## Code Changes

Modify the smallest possible surface area.

Avoid refactoring unrelated code.

Avoid style-only changes.

Avoid touching files unrelated to the task.

## Planning

For tasks under 30 minutes:

- Make a short plan.
- Execute.

For simple tasks, implementation is preferred over lengthy analysis.

## Explanations

Keep reasoning and status updates concise.

Focus on:

- Findings
- Changes
- Risks
- Next steps

Avoid lengthy summaries of files already inspected.

## Validation

Validate only what was changed.

Do not run full repository validation unless requested.

Use targeted checks whenever possible.

# Ask Claude about health data

Claude (Claude Code on the PC, or a Remote Control session from the project) queries
TimescaleDB through `health-sql.sh` as the read-only `health_ro` role. No new service,
no new port: it is `ssh kadin-main-sys` + `docker exec psql`.

## One-time setup (on the server)

```bash
docker exec -i health_timescaledb psql -U health -d health < phase5-health-data/claude/readonly_role.sql
```

Rerun after new tables appear if they are not owned by `health`. Undo with
`DROP OWNED BY health_ro; DROP ROLE health_ro;`.

## Using it

Ask Claude something like "look for trends in my sleep and resting heart rate" — the
`health-trends` skill (`.claude/skills/health-trends/SKILL.md`) tells it the tables and the
command. `fitbit_oauth_tokens` is not readable by this role, and every session is read-only
with a 60s statement timeout.

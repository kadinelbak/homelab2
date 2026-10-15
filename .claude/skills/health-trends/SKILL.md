---
name: health-trends
description: Query the homelab health TimescaleDB (Fitbit metrics, sleep, N-of-1 check-ins/experiments) read-only to find trends. Use when asked about health data, sleep, heart rate, HRV, steps, or experiments.
---

# Health data trends

Run SQL with `phase5-health-data/claude/health-sql.sh "<SQL>"` (CSV out). It SSHes to
`kadin-main-sys` and runs psql as the read-only `health_ro` role. On the server itself,
prefix `HEALTH_SSH_HOST=""`.

Rules: aggregate in SQL (daily/weekly), never pull raw minute-level rows wholesale; keep
output small (`LIMIT`); never print secrets. Times are `timestamptz`; use
bucket with `date_trunc('day', ts)` (session TZ is the server's; check `SHOW timezone`).

## Main tables

- `metric_samples(ts, metric_type, value, unit, source, metadata)` — hypertable. Known
  `metric_type`s include heart_rate (intraday), resting_heart_rate, hrv, steps, calories,
  distance, breathing_rate. Start with
  `SELECT metric_type, count(*), min(ts), max(ts) FROM metric_samples GROUP BY 1`.
- `sleep_sessions(log_id, date_of_sleep, start_time, end_time, duration_seconds, efficiency,
  minutes_asleep, minutes_awake, is_main_sleep)`; `sleep_stages(log_id, ts, level, seconds)`.
- N-of-1 app: `daily_checkins`, `intervention_events`, `experiments`, `meal_entries`,
  `context_events`; views `n1_daily_nutrition`, `n1_experiment_day`, `n1_context_days`.
  Check columns with
  `SELECT column_name, data_type FROM information_schema.columns WHERE table_name='<t>'`.

## Finding trends

Good first pass: weekly averages and 4-week vs prior-4-week deltas per metric; day-of-week
patterns; correlations between sleep (minutes_asleep, efficiency, bedtime) and next-day
resting HR / HRV / steps (`corr()` in SQL); outlier days (> 2 SD). Very high step days (20k+) and 11h+ sleeps are real for this user, not errors. Say how many days back
each claim rests on and flag gaps in the data.

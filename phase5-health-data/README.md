# Phase 5: Personal Health Data

This stack is for private analysis of Fitbit Inspire 3 data synced through the
Fitbit app on a Pixel 9, plus a Tailnet-only N-of-1 health logger for manual
check-ins, interventions, and nutrition.

## Data Flow

```text
Inspire 3 -> Fitbit app on Pixel 9 -> Fitbit/Google export -> raw archive
                                                -> TimescaleDB -> notebooks/dashboards
N-of-1 logger -> TimescaleDB -> Metabase views
```

The importer keeps every JSON file in `raw_documents` before normalizing known
records into analysis tables. That gives you a provenance trail while keeping
the schema flexible as you add labs, weight, nutrition, or other sources.

## First Run

1. Add the Phase 5 values from `.env.example` into `.env`.
2. Create data folders:

```bash
bash scripts/setup.sh
```

3. Start the database:

```bash
cd phase5-health-data
docker compose --env-file ../.env up -d health-db
```

4. Export your Fitbit/Google Health data and unpack JSON files into:

```text
${DATA_PATH}/phase5-health-data/raw/fitbit-export
```

5. Run the importer:

```bash
docker compose --env-file ../.env run --rm health-importer import-export
```

## Daily Fitbit API Sync

For automatic updates, create a **Personal** app in the Fitbit developer portal,
authorize it for your own account with at least `activity`, `heartrate`, and
`sleep` scopes, then place its client ID, client secret, and initial refresh
token in `FITBIT_CLIENT_ID`, `FITBIT_CLIENT_SECRET`, and
`FITBIT_REFRESH_TOKEN` in the server's `.env`. Start the sync service:

```bash
docker compose --env-file ../.env --profile sync up -d health-sync
```

It immediately refreshes the prior two days (to catch delayed phone syncs),
then repeats every 24 hours. Set `HEALTH_SYNC_INTERVAL_SECONDS` in `.env` to
change the interval. Refreshed OAuth tokens are retained only in the private
health database; do not expose that database or commit `.env`.

Google OAuth apps in Testing typically issue refresh tokens that expire after
about seven days. Reauthorize when the sync reports an OAuth error, or complete
the required Google production configuration before relying on unattended sync.

## N-of-1 Logger and Metabase

The N-of-1 logger is included in the default stack at
`https://<tailnet-host>:13001`. Use it to create experiments and conditions,
schedule interventions, record one-off events, complete daily check-ins, and
upload Nutrition Facts labels for review before nutrient values are saved.

It writes directly to the same TimescaleDB database that Metabase queries;
there is no intermediary synchronization service. Food-label images and raw OCR
output stay under `${DATA_PATH}/phase5-health-data/raw/n1-uploads` and are not
versioned. After the initial deployment, refresh Metabase's database metadata
once to discover `n1_daily_nutrition`, `n1_experiment_adherence`, and
`n1_experiment_day`. New rows appear in those views automatically.

6. Start analysis tools when needed:

```bash
docker compose --env-file ../.env --profile analysis up -d
```

JupyterLab mounts the starter notebook at
`/home/jovyan/examples/health-start-here.ipynb`.

## URLs

- JupyterLab: `http://<tailnet-host>:18888`
- Metabase: `http://<tailnet-host>:13000`

The health database is intentionally not published on a host port. JupyterLab,
Metabase, and the importer reach it over the stack's private Docker network.

## Tables

- `raw_documents`: original JSON payloads with file path and SHA-256 hash
- `metric_samples`: time-series samples such as heart rate, steps, calories, SpO2
- `sleep_sessions`: nightly sleep summaries
- `sleep_stages`: timestamped sleep-stage intervals
- `import_runs`: import status and row counts

## Notes

- Keep this stack private behind Tailscale or your trusted network.
- Set `HEALTH_BIND_IP` to your Tailscale IP so browser tools do not bind to LAN
  or public interfaces.
- Back up both `${DATA_PATH}/phase5-health-data/raw` and the TimescaleDB volume.
- Do not expose JupyterLab, Metabase, or Postgres directly to the public internet.

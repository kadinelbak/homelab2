# N-of-1 Health Logger

This mobile-first app records manual experiment data in the same Postgres database
used by the health importer and Metabase. It is intended for private Tailnet use.

## Data flow

Wearables continue to import into `metric_samples` and `sleep_sessions`. The app
writes manual records through versioned migrations, and Metabase queries the views
`n1_daily_nutrition`, `n1_experiment_adherence`, and `n1_experiment_day` directly.
Rows appear in Metabase as soon as they are committed; after first deployment, use
Metabase Admin → Databases → Homelab Health → Sync database schema once.

## Food labels

Only JPG, PNG, and WEBP Nutrition Facts label images are accepted. Images and OCR
text remain in the private `${DATA_PATH}/phase5-health-data/raw/n1-uploads` volume.
OCR is a draft: values are not included in nutrition totals until confirmed.

## Access

Bind the container to loopback with `HEALTH_N1_BIND_IP=127.0.0.1`, then publish
the port through private Tailscale Serve HTTPS. Set `HEALTH_N1_PUBLIC_URL` to that
Tailnet HTTPS URL so Homepage links to the secure endpoint. This app has no
separate login in its single-user deployment; Tailscale access is its access
boundary. The reminder service uses the existing allowlisted Jarvis Telegram
configuration only to send outbound reminders.

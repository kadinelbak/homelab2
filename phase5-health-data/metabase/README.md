# Metabase dashboard provisioning

`fitbit-n1-dashboard.json` is the versioned definition of the private **Fitbit & N-of-1 Health** dashboard. It queries the existing Homelab Health database; it does not export, copy, or expose health records.

Create a scoped Metabase API key, then add it only to the server's untracked `/home/kadin/homelab2/.env`:

```dotenv
METABASE_API_KEY=replace-with-private-key
METABASE_DATABASE_NAME=Homelab Health
```

After loading `.env`, apply with:

```bash
python3 phase5-health-data/metabase/provision_dashboard.py --dry-run
python3 phase5-health-data/metabase/provision_dashboard.py
```

The URL defaults to `http://${HEALTH_BIND_IP}:${HEALTH_METABASE_HOST_PORT}` (where Metabase is published); pass `--url` to override.

The provisioner updates its named cards in place and adds missing cards only. It never deletes unrelated Metabase content. The dashboard remains protected by the existing Tailnet and Metabase login. After schema changes, use Metabase Admin → Databases → Homelab Health → **Sync database schema** once; later rows appear automatically. The context-period card surfaces tagged illness, travel, alcohol, injury, medication, stress, sleep, and other time ranges so confounders remain visible during experiment review.

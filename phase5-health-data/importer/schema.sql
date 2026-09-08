DO $$
BEGIN
  CREATE EXTENSION IF NOT EXISTS timescaledb;
EXCEPTION
  WHEN undefined_file OR feature_not_supported THEN
    RAISE NOTICE 'TimescaleDB extension is unavailable; continuing with plain PostgreSQL tables.';
END
$$;

CREATE TABLE IF NOT EXISTS import_runs (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  source_path TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  files_seen INTEGER NOT NULL DEFAULT 0,
  raw_documents_inserted INTEGER NOT NULL DEFAULT 0,
  metric_samples_inserted INTEGER NOT NULL DEFAULT 0,
  sleep_sessions_inserted INTEGER NOT NULL DEFAULT 0,
  sleep_stages_inserted INTEGER NOT NULL DEFAULT 0,
  error TEXT
);

CREATE TABLE IF NOT EXISTS raw_documents (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  source_file TEXT NOT NULL,
  document_hash TEXT NOT NULL,
  payload JSONB NOT NULL,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  import_run_id BIGINT REFERENCES import_runs(id),
  UNIQUE (source, source_file, document_hash)
);

-- Tokens stay on the private health network so refreshed OAuth credentials
-- survive container restarts without writing back to the deployment .env file.
CREATE TABLE IF NOT EXISTS fitbit_oauth_tokens (
  source TEXT PRIMARY KEY,
  refresh_token TEXT NOT NULL,
  access_token TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS metric_samples (
  ts TIMESTAMPTZ NOT NULL,
  metric_type TEXT NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  unit TEXT,
  source TEXT NOT NULL,
  source_file TEXT,
  confidence INTEGER,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  import_run_id BIGINT REFERENCES import_runs(id),
  PRIMARY KEY (ts, metric_type, source, source_file)
);

DO $$
BEGIN
  IF to_regproc('create_hypertable') IS NOT NULL THEN
    PERFORM create_hypertable('metric_samples', 'ts', if_not_exists => TRUE);
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS sleep_sessions (
  source TEXT NOT NULL,
  log_id TEXT NOT NULL,
  date_of_sleep DATE,
  start_time TIMESTAMPTZ,
  end_time TIMESTAMPTZ,
  duration_seconds INTEGER,
  efficiency INTEGER,
  minutes_asleep INTEGER,
  minutes_awake INTEGER,
  is_main_sleep BOOLEAN,
  source_file TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  import_run_id BIGINT REFERENCES import_runs(id),
  PRIMARY KEY (source, log_id)
);

CREATE TABLE IF NOT EXISTS sleep_stages (
  source TEXT NOT NULL,
  log_id TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  level TEXT NOT NULL,
  seconds INTEGER NOT NULL,
  source_file TEXT,
  import_run_id BIGINT REFERENCES import_runs(id),
  PRIMARY KEY (source, log_id, ts, level)
);

DO $$
BEGIN
  IF to_regproc('create_hypertable') IS NOT NULL THEN
    PERFORM create_hypertable('sleep_stages', 'ts', if_not_exists => TRUE);
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_metric_samples_type_ts ON metric_samples (metric_type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_raw_documents_source_file ON raw_documents (source, source_file);
CREATE INDEX IF NOT EXISTS idx_sleep_sessions_date ON sleep_sessions (date_of_sleep DESC);

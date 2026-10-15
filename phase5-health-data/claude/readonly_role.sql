-- Read-only role for ad-hoc analysis (Claude, notebooks). Idempotent; rerun anytime.
-- Login only via `docker exec` on the server (local socket); no network port is exposed.
-- Undo: DROP OWNED BY health_ro; DROP ROLE health_ro;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'health_ro') THEN
    CREATE ROLE health_ro LOGIN;
  END IF;
END
$$;

ALTER ROLE health_ro SET default_transaction_read_only = on;
ALTER ROLE health_ro SET statement_timeout = '60s';
GRANT CONNECT ON DATABASE health TO health_ro;
GRANT USAGE ON SCHEMA public TO health_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO health_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE health IN SCHEMA public GRANT SELECT ON TABLES TO health_ro;
-- Never expose OAuth secrets.
REVOKE ALL ON fitbit_oauth_tokens FROM health_ro;

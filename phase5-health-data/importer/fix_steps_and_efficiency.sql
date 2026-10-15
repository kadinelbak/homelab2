-- One-off cleanup (2026-10): older syncs stored phone (Health Connect) steps, distance and
-- calories next to the watch's, doubling daily totals, and never stored sleep efficiency.
-- Phone rows are removed only on days the watch also reported, so phone-only history stays.
-- Raw API payloads remain in raw_documents. Safe to re-run.
BEGIN;
DELETE FROM metric_samples p
USING (
  SELECT DISTINCT metric_type, ts::date AS day FROM metric_samples
  WHERE source = 'google_health_fitbit_inspire_3' AND metric_type IN ('steps', 'distance', 'calories')
    AND metadata->'data_source'->>'platform' = 'FITBIT'
) w
WHERE p.source = 'google_health_fitbit_inspire_3'
  AND p.metric_type = w.metric_type AND p.ts::date = w.day
  AND p.metadata->'data_source'->>'platform' IS DISTINCT FROM 'FITBIT';
UPDATE sleep_sessions
SET efficiency = round(100.0 * minutes_asleep / (duration_seconds / 60.0))
WHERE efficiency IS NULL AND minutes_asleep IS NOT NULL AND duration_seconds > 0;
COMMIT;

-- One-off cleanup (safe to re-run): the phone (Health Connect) steps/distance/calories were stored
-- alongside the watch's under the same source, doubling daily totals. Drop the phone rows from the
-- day the watch's data starts (earlier phone-only history is kept), and backfill sleep efficiency
-- as asleep / (asleep + awake), matching the importer.
BEGIN;
DELETE FROM metric_samples
WHERE source = 'google_health_fitbit_inspire_3'
  AND metric_type IN ('steps', 'distance', 'calories')
  AND metadata->'data_source'->>'platform' = 'HEALTH_CONNECT'
  AND ts >= (SELECT min(ts) FROM metric_samples
             WHERE source = 'google_health_fitbit_inspire_3' AND metric_type = 'steps'
               AND metadata->'data_source'->>'platform' = 'FITBIT');
UPDATE sleep_sessions
SET efficiency = round(100.0 * minutes_asleep / (minutes_asleep + minutes_awake))
WHERE source = 'google_health_fitbit_inspire_3' AND efficiency IS NULL
  AND minutes_asleep IS NOT NULL AND minutes_awake IS NOT NULL AND minutes_asleep + minutes_awake > 0;
COMMIT;

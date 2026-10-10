-- One-off cleanup: older syncs stored each Google Health reading once per sync day
-- (source_file google-health/<day>/<type>.json). Keep one row per reading under the
-- stable source_file the importer now uses. Safe to re-run.
BEGIN;
DELETE FROM metric_samples a
USING metric_samples b
WHERE a.source = 'google_health_fitbit_inspire_3' AND b.source = a.source
  AND a.metric_type = b.metric_type AND a.ts = b.ts
  AND a.source_file LIKE 'google-health/%' AND b.source_file LIKE 'google-health/%'
  AND a.source_file < b.source_file;
UPDATE metric_samples
SET source_file = 'google-health/' || split_part(source_file, '/', 3)
WHERE source = 'google_health_fitbit_inspire_3' AND source_file LIKE 'google-health/%/%';
COMMIT;

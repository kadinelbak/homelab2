CREATE TABLE IF NOT EXISTS context_events (
  id BIGSERIAL PRIMARY KEY,
  subject_id BIGINT NOT NULL REFERENCES subjects(id),
  category TEXT NOT NULL CHECK (category IN ('illness', 'travel', 'alcohol', 'injury', 'medication', 'stress', 'other')),
  label TEXT NOT NULL,
  starts_at TIMESTAMPTZ NOT NULL,
  ends_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (ends_at IS NULL OR ends_at >= starts_at)
);
CREATE INDEX IF NOT EXISTS idx_context_events_subject_time ON context_events (subject_id, starts_at DESC);

CREATE OR REPLACE VIEW n1_context_days AS
SELECT ce.subject_id,
       day::date AS day,
       string_agg(ce.category || ': ' || ce.label, '; ' ORDER BY ce.starts_at) AS contexts
FROM context_events ce
JOIN subjects s ON s.id = ce.subject_id
CROSS JOIN LATERAL generate_series(
  (ce.starts_at AT TIME ZONE s.timezone)::date,
  (COALESCE(ce.ends_at, now()) AT TIME ZONE s.timezone)::date,
  interval '1 day'
) AS day
GROUP BY ce.subject_id, day::date;

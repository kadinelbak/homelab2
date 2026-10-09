ALTER TABLE context_events DROP CONSTRAINT IF EXISTS context_events_category_check;
ALTER TABLE context_events ADD CONSTRAINT context_events_category_check
  CHECK (category IN ('illness', 'travel', 'alcohol', 'injury', 'medication', 'stress', 'sleep', 'other'));

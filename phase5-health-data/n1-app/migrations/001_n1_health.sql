CREATE TABLE IF NOT EXISTS n1_schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS subjects (
  id BIGSERIAL PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'America/New_York',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO subjects (slug, display_name)
VALUES ('owner', 'Owner') ON CONFLICT (slug) DO NOTHING;

CREATE TABLE IF NOT EXISTS experiments (
  id BIGSERIAL PRIMARY KEY,
  subject_id BIGINT NOT NULL REFERENCES subjects(id),
  name TEXT NOT NULL,
  hypothesis TEXT,
  primary_outcome TEXT,
  starts_on DATE,
  ends_on DATE,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','completed','archived')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS experiment_conditions (
  id BIGSERIAL PRIMARY KEY,
  experiment_id BIGINT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'intervention' CHECK (kind IN ('baseline','intervention','washout')),
  starts_on DATE,
  ends_on DATE,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS intervention_templates (
  id BIGSERIAL PRIMARY KEY,
  subject_id BIGINT NOT NULL REFERENCES subjects(id),
  experiment_id BIGINT REFERENCES experiments(id) ON DELETE SET NULL,
  condition_id BIGINT REFERENCES experiment_conditions(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  dose TEXT,
  unit TEXT,
  scheduled_times TIME[] NOT NULL DEFAULT '{}',
  active_from DATE NOT NULL DEFAULT CURRENT_DATE,
  active_until DATE,
  is_active BOOLEAN NOT NULL DEFAULT true,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS intervention_events (
  id BIGSERIAL PRIMARY KEY,
  subject_id BIGINT NOT NULL REFERENCES subjects(id),
  template_id BIGINT REFERENCES intervention_templates(id) ON DELETE SET NULL,
  experiment_id BIGINT REFERENCES experiments(id) ON DELETE SET NULL,
  condition_id BIGINT REFERENCES experiment_conditions(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  scheduled_for TIMESTAMPTZ,
  occurred_at TIMESTAMPTZ,
  dose TEXT,
  unit TEXT,
  adherence TEXT NOT NULL DEFAULT 'completed' CHECK (adherence IN ('completed','skipped','missed')),
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS daily_checkins (
  id BIGSERIAL PRIMARY KEY,
  subject_id BIGINT NOT NULL REFERENCES subjects(id),
  checkin_date DATE NOT NULL,
  weight_kg NUMERIC(6,2),
  energy SMALLINT CHECK (energy BETWEEN 1 AND 5),
  mood SMALLINT CHECK (mood BETWEEN 1 AND 5),
  stress SMALLINT CHECK (stress BETWEEN 1 AND 5),
  sleep_quality SMALLINT CHECK (sleep_quality BETWEEN 1 AND 5),
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(subject_id, checkin_date)
);
CREATE TABLE IF NOT EXISTS meal_entries (
  id BIGSERIAL PRIMARY KEY,
  subject_id BIGINT NOT NULL REFERENCES subjects(id),
  eaten_at TIMESTAMPTZ NOT NULL,
  meal_name TEXT NOT NULL DEFAULT 'Meal',
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS food_label_images (
  id BIGSERIAL PRIMARY KEY,
  subject_id BIGINT NOT NULL REFERENCES subjects(id),
  storage_path TEXT NOT NULL UNIQUE,
  original_filename TEXT NOT NULL,
  ocr_text TEXT,
  parsed_draft JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence SMALLINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS food_items (
  id BIGSERIAL PRIMARY KEY,
  meal_id BIGINT NOT NULL REFERENCES meal_entries(id) ON DELETE CASCADE,
  label_image_id BIGINT REFERENCES food_label_images(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  serving_count NUMERIC(8,3) NOT NULL DEFAULT 1,
  scale_weight_g NUMERIC(8,2),
  calories NUMERIC(10,2) NOT NULL DEFAULT 0,
  protein_g NUMERIC(10,2) NOT NULL DEFAULT 0,
  carbohydrates_g NUMERIC(10,2) NOT NULL DEFAULT 0,
  fat_g NUMERIC(10,2) NOT NULL DEFAULT 0,
  is_confirmed BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS notification_deliveries (
  id BIGSERIAL PRIMARY KEY,
  subject_id BIGINT NOT NULL REFERENCES subjects(id),
  dedupe_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed')),
  attempted_at TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_n1_events_subject_time ON intervention_events(subject_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_n1_meals_subject_time ON meal_entries(subject_id, eaten_at DESC);

CREATE OR REPLACE VIEW n1_daily_nutrition AS
SELECT m.subject_id, (m.eaten_at AT TIME ZONE s.timezone)::date AS day,
       COALESCE(SUM(f.calories) FILTER (WHERE f.is_confirmed),0) AS calories,
       COALESCE(SUM(f.protein_g) FILTER (WHERE f.is_confirmed),0) AS protein_g,
       COALESCE(SUM(f.carbohydrates_g) FILTER (WHERE f.is_confirmed),0) AS carbohydrates_g,
       COALESCE(SUM(f.fat_g) FILTER (WHERE f.is_confirmed),0) AS fat_g
FROM meal_entries m JOIN subjects s ON s.id=m.subject_id
LEFT JOIN food_items f ON f.meal_id=m.id GROUP BY m.subject_id, (m.eaten_at AT TIME ZONE s.timezone)::date;

CREATE OR REPLACE VIEW n1_experiment_adherence AS
SELECT e.id AS experiment_id, e.name AS experiment_name, ev.name AS intervention,
       (ev.occurred_at AT TIME ZONE s.timezone)::date AS day,
       ev.adherence, ev.dose, ev.unit
FROM intervention_events ev JOIN subjects s ON s.id=ev.subject_id
LEFT JOIN experiments e ON e.id=ev.experiment_id;

CREATE OR REPLACE VIEW n1_experiment_day AS
SELECT d.checkin_date AS day, d.subject_id, d.weight_kg, d.energy, d.mood, d.stress, d.sleep_quality,
       n.calories, n.protein_g, n.carbohydrates_g, n.fat_g,
       (SELECT count(*) FROM intervention_events ev WHERE ev.subject_id=d.subject_id
         AND (ev.occurred_at AT TIME ZONE s.timezone)::date=d.checkin_date AND ev.adherence='completed') AS interventions_completed
FROM daily_checkins d JOIN subjects s ON s.id=d.subject_id
LEFT JOIN n1_daily_nutrition n ON n.subject_id=d.subject_id AND n.day=d.checkin_date;

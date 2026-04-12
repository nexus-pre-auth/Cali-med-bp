-- migrations/004_supabase_platform.sql
--
-- Full multi-state, multi-product platform schema for blueprintIQ / Medblueprints / CodeBlue.
-- Run this in the Supabase SQL editor or via psql:
--
--   psql $SUPABASE_DB_URL -f migrations/004_supabase_platform.sql
--
-- Row-Level Security (RLS) policies are included at the bottom.

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy text search on rules

-- ---------------------------------------------------------------------------
-- jurisdictions
-- ---------------------------------------------------------------------------
-- One row per state/territory AHJ. Seeded via scripts/seed_jurisdictions.py.

CREATE TABLE IF NOT EXISTS jurisdictions (
    id           UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    state_code   TEXT  NOT NULL UNIQUE,  -- 'CA', 'TX', 'FL'
    state_name   TEXT  NOT NULL,
    ahj_name     TEXT  NOT NULL,         -- 'HCAI', 'DSHS', 'AHCA', 'DOH'
    ahj_website  TEXT,
    is_active    BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed California (the first live jurisdiction)
INSERT INTO jurisdictions (state_code, state_name, ahj_name, ahj_website)
VALUES ('CA', 'California', 'HCAI', 'https://hcai.ca.gov')
ON CONFLICT (state_code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- rule_packs
-- ---------------------------------------------------------------------------
-- A versioned bundle of rules for one jurisdiction + discipline.
-- e.g. "HCAI Healthcare Facilities 2024", "DSHS Healthcare 2023"

CREATE TABLE IF NOT EXISTS rule_packs (
    id               UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    jurisdiction_id  UUID  NOT NULL REFERENCES jurisdictions(id) ON DELETE CASCADE,
    name             TEXT  NOT NULL,
    discipline       TEXT  NOT NULL DEFAULT 'Healthcare',
    version          TEXT  NOT NULL DEFAULT '2024',
    effective_date   DATE,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (jurisdiction_id, name, version)
);

-- ---------------------------------------------------------------------------
-- rules
-- ---------------------------------------------------------------------------
-- Individual compliance rules. Mirrors the structure of hcai_rules.json but
-- stored in Postgres for cross-state querying, versioning, and API delivery.

CREATE TABLE IF NOT EXISTS rules (
    id                   UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_pack_id         UUID  NOT NULL REFERENCES rule_packs(id) ON DELETE CASCADE,
    rule_key             TEXT  NOT NULL,          -- 'RULE-001', 'TX-HC-001'
    discipline           TEXT  NOT NULL,
    description          TEXT  NOT NULL,
    trigger_occupancies  JSONB NOT NULL DEFAULT '[]',
    trigger_systems      JSONB NOT NULL DEFAULT '[]',
    trigger_rooms        JSONB NOT NULL DEFAULT '[]',
    trigger_seismic_zones JSONB NOT NULL DEFAULT '[]',
    violation_template   TEXT,
    fix_template         TEXT,
    code_references      JSONB NOT NULL DEFAULT '[]',
    severity_override    TEXT  CHECK (severity_override IN ('Critical','High','Medium','Low')),
    is_active            BOOLEAN NOT NULL DEFAULT true,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (rule_pack_id, rule_key)
);

CREATE INDEX IF NOT EXISTS idx_rules_pack       ON rules (rule_pack_id);
CREATE INDEX IF NOT EXISTS idx_rules_discipline ON rules (discipline);
CREATE INDEX IF NOT EXISTS idx_rules_key        ON rules (rule_key);
-- Full-text search across description + templates
CREATE INDEX IF NOT EXISTS idx_rules_fts ON rules
    USING gin(to_tsvector('english', description || ' ' || COALESCE(violation_template,'')));

-- ---------------------------------------------------------------------------
-- products
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS products (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        TEXT UNIQUE NOT NULL,  -- 'medblueprints', 'codeblue'
    name        TEXT NOT NULL,
    description TEXT,
    domain      TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO products (slug, name, description, domain) VALUES
    ('medblueprints', 'Medblueprints', 'Healthcare construction pre-submission compliance checker', 'medblueprints.com'),
    ('codeblue',      'CodeBlue',      'General building and fire code compliance checker',         'codeblue.io')
ON CONFLICT (slug) DO NOTHING;

-- ---------------------------------------------------------------------------
-- product_rule_packs
-- ---------------------------------------------------------------------------
-- Which rule packs each product loads when running a review.

CREATE TABLE IF NOT EXISTS product_rule_packs (
    product_id    UUID NOT NULL REFERENCES products(id)    ON DELETE CASCADE,
    rule_pack_id  UUID NOT NULL REFERENCES rule_packs(id) ON DELETE CASCADE,
    PRIMARY KEY (product_id, rule_pack_id)
);

-- ---------------------------------------------------------------------------
-- firms  (customers)
-- ---------------------------------------------------------------------------
-- One row per subscribing company. Links to Supabase Auth user.

CREATE TABLE IF NOT EXISTS firms (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    name                    TEXT NOT NULL,
    contact_email           TEXT,
    state                   TEXT,
    license_number          TEXT,
    tier                    TEXT NOT NULL DEFAULT 'single'
                            CHECK (tier IN ('single','studio','firm','enterprise')),
    reviews_used            INTEGER NOT NULL DEFAULT 0,
    reviews_limit           INTEGER NOT NULL DEFAULT 1,  -- -1 = unlimited
    stripe_customer_id      TEXT UNIQUE,
    stripe_subscription_id  TEXT,
    is_active               BOOLEAN NOT NULL DEFAULT true,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_firms_user    ON firms (user_id);
CREATE INDEX IF NOT EXISTS idx_firms_stripe  ON firms (stripe_customer_id);

-- ---------------------------------------------------------------------------
-- projects
-- ---------------------------------------------------------------------------
-- One row per uploaded drawing set / plan submission.

CREATE TABLE IF NOT EXISTS projects (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id           UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    jurisdiction_id   UUID REFERENCES jurisdictions(id),
    product_slug      TEXT REFERENCES products(slug),
    pdf_storage_path  TEXT,     -- Supabase Storage object path
    occupancy_type    TEXT,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','processing','complete','failed')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_firm   ON projects (firm_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status);

-- ---------------------------------------------------------------------------
-- reviews
-- ---------------------------------------------------------------------------
-- Compliance review result for a project.

CREATE TABLE IF NOT EXISTS reviews (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id         UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    total_violations   INTEGER NOT NULL DEFAULT 0,
    critical_count     INTEGER NOT NULL DEFAULT 0,
    high_count         INTEGER NOT NULL DEFAULT 0,
    medium_count       INTEGER NOT NULL DEFAULT 0,
    low_count          INTEGER NOT NULL DEFAULT 0,
    report_json        JSONB,
    report_html_path   TEXT,   -- Supabase Storage object path
    conditions_json    JSONB,  -- extracted ProjectConditions
    completed_at       TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reviews_project ON reviews (project_id);

-- ---------------------------------------------------------------------------
-- violations
-- ---------------------------------------------------------------------------
-- Individual violations found within a review.

CREATE TABLE IF NOT EXISTS violations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id        UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    rule_key         TEXT NOT NULL,
    severity         TEXT NOT NULL CHECK (severity IN ('Critical','High','Medium','Low')),
    discipline       TEXT,
    description      TEXT,
    ahj_comment      TEXT,
    fix_instructions TEXT,
    citations        JSONB NOT NULL DEFAULT '[]',
    is_resolved      BOOLEAN NOT NULL DEFAULT false,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_violations_review   ON violations (review_id);
CREATE INDEX IF NOT EXISTS idx_violations_severity ON violations (severity);
CREATE INDEX IF NOT EXISTS idx_violations_resolved ON violations (is_resolved);

-- ---------------------------------------------------------------------------
-- feedback_records  (replaces 003 version — now linked to reviews)
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS feedback_records CASCADE;

CREATE TABLE IF NOT EXISTS feedback_records (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feedback_id    TEXT UNIQUE NOT NULL,
    review_id      UUID REFERENCES reviews(id) ON DELETE SET NULL,
    firm_id        UUID REFERENCES firms(id)   ON DELETE SET NULL,
    ahj_name       TEXT NOT NULL,
    reviewer_id    TEXT,
    feedback_type  TEXT NOT NULL
                   CHECK (feedback_type IN (
                       'waiver_prediction','violation_detection',
                       'severity_scoring','rule_accuracy','ai_comment_quality'
                   )),
    data           JSONB NOT NULL,
    is_processed   BOOLEAN NOT NULL DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fb_ahj       ON feedback_records (ahj_name);
CREATE INDEX IF NOT EXISTS idx_fb_type      ON feedback_records (feedback_type);
CREATE INDEX IF NOT EXISTS idx_fb_created   ON feedback_records (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fb_unproc    ON feedback_records (is_processed) WHERE is_processed = false;

-- ---------------------------------------------------------------------------
-- model_versions  (unchanged from 003, kept for continuity)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS model_versions (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version                TEXT UNIQUE NOT NULL,
    model_type             TEXT NOT NULL CHECK (model_type IN ('waiver','violation','severity','bundle')),
    model_path             TEXT NOT NULL,
    metrics                JSONB,
    trained_on_date        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active              BOOLEAN NOT NULL DEFAULT false,
    training_data_count    INTEGER,
    improvement_percentage FLOAT,
    retrain_reason         TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_model
    ON model_versions (model_type) WHERE is_active = true;

-- ---------------------------------------------------------------------------
-- performance_metrics
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS performance_metrics (
    id            UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_date   DATE  NOT NULL,
    metric_type   TEXT  NOT NULL CHECK (metric_type IN (
                      'precision','recall','f1','accuracy','auc','calibration_error')),
    value         FLOAT NOT NULL,
    model_version TEXT,
    sample_size   INTEGER,
    UNIQUE (metric_date, metric_type)
);

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------
-- Firms can only see their own data. Service-role key bypasses RLS.

ALTER TABLE firms     ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects  ENABLE ROW LEVEL SECURITY;
ALTER TABLE reviews   ENABLE ROW LEVEL SECURITY;
ALTER TABLE violations ENABLE ROW LEVEL SECURITY;

CREATE POLICY firms_own_data     ON firms     USING (user_id = auth.uid());
CREATE POLICY projects_own_data  ON projects  USING (firm_id IN (SELECT id FROM firms WHERE user_id = auth.uid()));
CREATE POLICY reviews_own_data   ON reviews   USING (project_id IN (SELECT p.id FROM projects p JOIN firms f ON p.firm_id = f.id WHERE f.user_id = auth.uid()));
CREATE POLICY violations_own_data ON violations USING (review_id IN (SELECT r.id FROM reviews r JOIN projects p ON r.project_id = p.id JOIN firms f ON p.firm_id = f.id WHERE f.user_id = auth.uid()));

-- rules, jurisdictions, rule_packs are public read
ALTER TABLE rules        ENABLE ROW LEVEL SECURITY;
ALTER TABLE rule_packs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE jurisdictions ENABLE ROW LEVEL SECURITY;

CREATE POLICY rules_public_read        ON rules        FOR SELECT USING (true);
CREATE POLICY rule_packs_public_read   ON rule_packs   FOR SELECT USING (true);
CREATE POLICY jurisdictions_public_read ON jurisdictions FOR SELECT USING (true);

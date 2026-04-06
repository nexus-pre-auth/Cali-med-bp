-- migrations/003_feedback_tables.sql
--
-- Schema for the AHJ feedback loop and ML model registry.
-- Apply with any PostgreSQL-compatible client:
--
--   psql $DATABASE_URL -f migrations/003_feedback_tables.sql
--
-- Requires: pgcrypto extension (gen_random_uuid).

-- ---------------------------------------------------------------------------
-- Prerequisites
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- feedback_records
-- ---------------------------------------------------------------------------
-- One row per AHJ feedback submission.  The full payload is stored in JSONB
-- so schema evolution doesn't require additional migrations.

CREATE TABLE IF NOT EXISTS feedback_records (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    feedback_id     UUID        UNIQUE NOT NULL,
    job_id          UUID        REFERENCES jobs(id) ON DELETE SET NULL,
    ahj_name        TEXT        NOT NULL,
    reviewer_id     TEXT,                          -- hashed / anonymised
    feedback_type   TEXT        NOT NULL
                    CHECK (feedback_type IN (
                        'waiver_prediction',
                        'violation_detection',
                        'severity_scoring',
                        'rule_accuracy',
                        'ai_comment_quality'
                    )),
    data            JSONB       NOT NULL,           -- full AHJFeedback payload
    is_processed    BOOLEAN     NOT NULL DEFAULT false,
    processing_date TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_ahj       ON feedback_records (ahj_name);
CREATE INDEX IF NOT EXISTS idx_feedback_type      ON feedback_records (feedback_type);
CREATE INDEX IF NOT EXISTS idx_feedback_created   ON feedback_records (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_processed ON feedback_records (is_processed)
    WHERE is_processed = false;   -- partial index speeds up unprocessed queue scans

-- ---------------------------------------------------------------------------
-- model_versions
-- ---------------------------------------------------------------------------
-- Registry of every trained model artifact.

CREATE TABLE IF NOT EXISTS model_versions (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    version               TEXT        UNIQUE NOT NULL,        -- e.g. 'v1.2.0'
    model_type            TEXT        NOT NULL
                          CHECK (model_type IN ('waiver', 'violation', 'severity', 'bundle')),
    model_path            TEXT        NOT NULL,               -- path under data/models/
    metrics               JSONB,                             -- precision, recall, F1, AUC
    trained_on_date       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active             BOOLEAN     NOT NULL DEFAULT false,
    training_data_count   INTEGER,
    improvement_percentage FLOAT,
    retrain_reason        TEXT                               -- e.g. 'daily_schedule'
);

CREATE INDEX IF NOT EXISTS idx_model_type   ON model_versions (model_type);
CREATE INDEX IF NOT EXISTS idx_model_active ON model_versions (is_active) WHERE is_active = true;

-- Only one active model per type at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_model
    ON model_versions (model_type) WHERE is_active = true;

-- ---------------------------------------------------------------------------
-- performance_metrics
-- ---------------------------------------------------------------------------
-- Daily/hourly aggregated metrics for trend dashboards.

CREATE TABLE IF NOT EXISTS performance_metrics (
    id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_date  DATE    NOT NULL,
    metric_type  TEXT    NOT NULL
                 CHECK (metric_type IN ('precision', 'recall', 'f1', 'accuracy', 'auc', 'calibration_error')),
    value        FLOAT   NOT NULL,
    model_version TEXT,
    sample_size  INTEGER,
    UNIQUE (metric_date, metric_type)
);

CREATE INDEX IF NOT EXISTS idx_perf_date ON performance_metrics (metric_date DESC);

-- ---------------------------------------------------------------------------
-- rule_accuracy_log
-- ---------------------------------------------------------------------------
-- Historical per-rule accuracy, enabling trend analysis for individual rules.

CREATE TABLE IF NOT EXISTS rule_accuracy_log (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id         TEXT        NOT NULL,   -- e.g. 'RULE-001'
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    false_positives INTEGER     NOT NULL DEFAULT 0,
    false_negatives INTEGER     NOT NULL DEFAULT 0,
    total_reviews   INTEGER     NOT NULL DEFAULT 0,
    accuracy        FLOAT       NOT NULL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_rule_accuracy_rule_id ON rule_accuracy_log (rule_id);
CREATE INDEX IF NOT EXISTS idx_rule_accuracy_date    ON rule_accuracy_log (recorded_at DESC);

-- ---------------------------------------------------------------------------
-- audit_log
-- ---------------------------------------------------------------------------
-- Immutable record of every significant system event (feedback received,
-- retraining triggered, model promoted, alerts fired).

CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  TEXT        NOT NULL,   -- 'feedback_received', 'retrain_triggered', etc.
    entity_id   TEXT,                   -- feedback_id, model version, etc.
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_date  ON audit_log (created_at DESC);

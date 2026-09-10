-- ---------------------------------------------------------------------------
-- 005_security_hardening.sql
--
-- Audit finding (RED): `feedback_records`, `model_versions`, and
-- `performance_metrics` were created in 004_supabase_platform.sql without
-- Row Level Security enabled. Because the backend connects with the
-- Supabase *service role* key (which bypasses RLS entirely), the app itself
-- was unaffected, but any future use of the `anon`/`authenticated` key
-- (e.g. a browser client querying Supabase directly) would have had
-- unrestricted read/write access to AHJ feedback data, model artifacts
-- metadata, and performance metrics for every tenant.
--
-- This migration is idempotent and safe to run multiple times.
-- ---------------------------------------------------------------------------

-- feedback_records: tenant-scoped like violations/reviews/projects.
-- Rows without a firm_id (legacy/unlinked feedback) are visible to no one
-- except the service role, which bypasses RLS.
ALTER TABLE feedback_records ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS feedback_records_own_data ON feedback_records;
CREATE POLICY feedback_records_own_data ON feedback_records
    USING (firm_id IN (SELECT id FROM firms WHERE user_id = auth.uid()));

-- model_versions and performance_metrics are internal ML operational data,
-- not tenant data. There is no legitimate end-user (anon/authenticated)
-- access pattern for them: they must only be read/written by the backend
-- service role. Enabling RLS with no policies denies all access to
-- non-service-role callers while leaving the service role unaffected.
ALTER TABLE model_versions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE performance_metrics ENABLE ROW LEVEL SECURITY;

-- Explicitly revoke any default grants that may have been issued to the
-- anon/authenticated roles on these operational tables.
REVOKE ALL ON model_versions      FROM anon, authenticated;
REVOKE ALL ON performance_metrics FROM anon, authenticated;

-- migrations/006_saas_tenant_model.sql
--
-- Phase 3: Production SaaS API and tenant architecture.
--
-- This migration ADDS a multi-user organization/membership/role model and
-- the project → documents → analyses → findings → reports pipeline tables
-- required by the versioned /api/v1 API. It does NOT remove or rename any
-- existing table — `firms`, `reviews`, and `violations` (from
-- 004_supabase_platform.sql) are preserved for backward compatibility with
-- the existing CLI/legacy review flow.
--
-- Design notes:
--   * `organizations` is the new multi-user tenant root. Where the legacy
--     `firms` table modeled "one user owns one firm", `organizations` +
--     `memberships` model "many users belong to one organization with a
--     role", per the Phase 3 requirements.
--   * `projects.organization_id` is added (nullable) so existing rows
--     created under the legacy `firm_id`-only model keep working, while new
--     SaaS-API-created projects populate `organization_id`.
--   * Every tenant-owned table added here reaches its `organization_id`
--     either directly or via `project_id -> projects.organization_id`, so
--     RLS can be expressed consistently.
--   * Service-role key (used by the backend) bypasses RLS entirely, exactly
--     as with the existing tables. RLS here protects any direct
--     anon/authenticated-key access (e.g. a future browser client talking
--     to Supabase directly), and documents/enforces the intended tenant
--     isolation model in Postgres itself, not just in application code.
--
-- Run via:
--   psql $SUPABASE_DB_URL -f migrations/006_saas_tenant_model.sql

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- organizations
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS organizations (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    slug         TEXT UNIQUE,
    created_by   UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    is_active    BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- memberships  (user <-> organization, with a role)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS memberships (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id          UUID NOT NULL REFERENCES auth.users(id)   ON DELETE CASCADE,
    role             TEXT NOT NULL DEFAULT 'MEMBER'
                     CHECK (role IN ('OWNER','ADMIN','REVIEWER','MEMBER','VIEWER')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_memberships_user ON memberships (user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_org  ON memberships (organization_id);

-- ---------------------------------------------------------------------------
-- projects: extend existing table with organization_id (additive, nullable)
-- ---------------------------------------------------------------------------

ALTER TABLE projects ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
-- Loosen the legacy NOT NULL on firm_id: SaaS-API projects may have an
-- organization_id instead of (or in addition to) a legacy firm_id.
ALTER TABLE projects ALTER COLUMN firm_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_projects_org ON projects (organization_id);

-- ---------------------------------------------------------------------------
-- project_members  (per-project role override within an organization)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS project_members (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'MEMBER'
                CHECK (role IN ('OWNER','ADMIN','REVIEWER','MEMBER','VIEWER')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_project_members_project ON project_members (project_id);
CREATE INDEX IF NOT EXISTS idx_project_members_user    ON project_members (user_id);

-- ---------------------------------------------------------------------------
-- documents / document_versions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS documents (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    storage_path      TEXT NOT NULL,   -- Supabase Storage object path or local safe path
    content_type      TEXT,
    size_bytes        BIGINT,
    checksum_sha256   TEXT,
    status            TEXT NOT NULL DEFAULT 'uploaded'
                      CHECK (status IN ('uploaded','rejected','processed','deleted')),
    uploaded_by       UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_project ON documents (project_id);

CREATE TABLE IF NOT EXISTS document_versions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id    UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL DEFAULT 1,
    storage_path   TEXT NOT NULL,
    checksum_sha256 TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_number)
);

-- ---------------------------------------------------------------------------
-- analyses / analysis_runs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analyses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_id     UUID REFERENCES documents(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'QUEUED'
                    CHECK (status IN ('QUEUED','PROCESSING','COMPLETED','FAILED')),
    engine_version  TEXT,
    error_message   TEXT,
    requested_by    UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analyses_project ON analyses (project_id);
CREATE INDEX IF NOT EXISTS idx_analyses_status  ON analyses (status);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id   UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    step          TEXT NOT NULL,   -- 'parse','extract','evaluate','rag','report'
    status        TEXT NOT NULL DEFAULT 'PENDING'
                  CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED')),
    detail        JSONB,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_analysis ON analysis_runs (analysis_id);

-- ---------------------------------------------------------------------------
-- findings / finding_evidence
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS findings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id         UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    rule_id             TEXT NOT NULL,
    discipline          TEXT,
    severity            TEXT NOT NULL CHECK (severity IN ('Critical','High','Medium','Low')),
    title               TEXT,
    requirement         TEXT,
    project_evidence    TEXT,
    required_condition  TEXT,
    jurisdiction        TEXT NOT NULL DEFAULT 'California (HCAI)',
    code_family         TEXT,
    code_edition        TEXT,
    section             TEXT,
    subsection          TEXT,
    source_document     TEXT,
    source_reference    JSONB NOT NULL DEFAULT '[]',
    citation_verified   BOOLEAN NOT NULL DEFAULT false,
    confidence          TEXT,
    recommended_action  TEXT,
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','acknowledged','resolved','disputed')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_findings_analysis ON findings (analysis_id);
CREATE INDEX IF NOT EXISTS idx_findings_severity  ON findings (severity);

CREATE TABLE IF NOT EXISTS finding_evidence (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id   UUID NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL DEFAULT 'extracted_condition',
    excerpt      TEXT,
    detail       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_finding_evidence_finding ON finding_evidence (finding_id);

-- ---------------------------------------------------------------------------
-- reports / report_versions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reports (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    analysis_id   UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    format        TEXT NOT NULL CHECK (format IN ('json','html','pdf','text')),
    storage_path  TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reports_project  ON reports (project_id);
CREATE INDEX IF NOT EXISTS idx_reports_analysis ON reports (analysis_id);

CREATE TABLE IF NOT EXISTS report_versions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id    UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    version      INTEGER NOT NULL DEFAULT 1,
    storage_path TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (report_id, version)
);

-- ---------------------------------------------------------------------------
-- audit_logs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    project_id      UUID REFERENCES projects(id) ON DELETE SET NULL,
    actor_user_id   UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,
    detail          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_org     ON audit_logs (organization_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_project ON audit_logs (project_id);

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------
-- `is_org_member(org_id)` is a SECURITY DEFINER helper that checks
-- membership while bypassing RLS on `memberships` itself. This is required
-- (not just a style choice): a plain correlated subquery against
-- `memberships` from *within a policy on `memberships`* causes Postgres to
-- report "infinite recursion detected in policy for relation
-- 'memberships'", because evaluating the policy re-triggers RLS on the same
-- table. Wrapping the membership check in a SECURITY DEFINER function
-- (owned by a role that bypasses RLS, e.g. the migration-running role)
-- breaks that cycle. This is the same pattern Supabase's own documentation
-- recommends for self-referential membership tables.

CREATE OR REPLACE FUNCTION is_org_member(target_org UUID)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM memberships
        WHERE organization_id = target_org AND user_id = auth.uid()
    );
$$;

CREATE OR REPLACE FUNCTION current_user_org_ids()
RETURNS SETOF UUID
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
    SELECT organization_id FROM memberships WHERE user_id = auth.uid();
$$;

ALTER TABLE organizations     ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships       ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members   ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents         ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses          ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_runs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE findings          ENABLE ROW LEVEL SECURITY;
ALTER TABLE finding_evidence  ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports           ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_versions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs        ENABLE ROW LEVEL SECURITY;

-- organizations: visible only to members
DROP POLICY IF EXISTS organizations_member_read ON organizations;
CREATE POLICY organizations_member_read ON organizations
    FOR SELECT USING (is_org_member(id));

-- memberships: a user can always see their own row; is_org_member() (via
-- SECURITY DEFINER) lets them also see fellow members without recursion.
DROP POLICY IF EXISTS memberships_member_read ON memberships;
CREATE POLICY memberships_member_read ON memberships
    FOR SELECT USING (
        user_id = auth.uid() OR is_org_member(organization_id)
    );

-- project_members: visible to members of the project's organization
DROP POLICY IF EXISTS project_members_read ON project_members;
CREATE POLICY project_members_read ON project_members
    FOR SELECT USING (
        project_id IN (
            SELECT p.id FROM projects p WHERE is_org_member(p.organization_id)
        )
    );

-- documents: visible to members of the owning project's organization
DROP POLICY IF EXISTS documents_tenant_read ON documents;
CREATE POLICY documents_tenant_read ON documents
    FOR SELECT USING (
        project_id IN (
            SELECT p.id FROM projects p WHERE is_org_member(p.organization_id)
        )
    );

DROP POLICY IF EXISTS document_versions_tenant_read ON document_versions;
CREATE POLICY document_versions_tenant_read ON document_versions
    FOR SELECT USING (
        document_id IN (
            SELECT d.id FROM documents d
            JOIN projects p ON p.id = d.project_id
            WHERE is_org_member(p.organization_id)
        )
    );

-- analyses / analysis_runs
DROP POLICY IF EXISTS analyses_tenant_read ON analyses;
CREATE POLICY analyses_tenant_read ON analyses
    FOR SELECT USING (
        project_id IN (
            SELECT p.id FROM projects p WHERE is_org_member(p.organization_id)
        )
    );

DROP POLICY IF EXISTS analysis_runs_tenant_read ON analysis_runs;
CREATE POLICY analysis_runs_tenant_read ON analysis_runs
    FOR SELECT USING (
        analysis_id IN (
            SELECT a.id FROM analyses a
            JOIN projects p ON p.id = a.project_id
            WHERE is_org_member(p.organization_id)
        )
    );

-- findings / finding_evidence
DROP POLICY IF EXISTS findings_tenant_read ON findings;
CREATE POLICY findings_tenant_read ON findings
    FOR SELECT USING (
        analysis_id IN (
            SELECT a.id FROM analyses a
            JOIN projects p ON p.id = a.project_id
            WHERE is_org_member(p.organization_id)
        )
    );

DROP POLICY IF EXISTS finding_evidence_tenant_read ON finding_evidence;
CREATE POLICY finding_evidence_tenant_read ON finding_evidence
    FOR SELECT USING (
        finding_id IN (
            SELECT f.id FROM findings f
            JOIN analyses a ON a.id = f.analysis_id
            JOIN projects p ON p.id = a.project_id
            WHERE is_org_member(p.organization_id)
        )
    );

-- reports / report_versions
DROP POLICY IF EXISTS reports_tenant_read ON reports;
CREATE POLICY reports_tenant_read ON reports
    FOR SELECT USING (
        project_id IN (
            SELECT p.id FROM projects p WHERE is_org_member(p.organization_id)
        )
    );

DROP POLICY IF EXISTS report_versions_tenant_read ON report_versions;
CREATE POLICY report_versions_tenant_read ON report_versions
    FOR SELECT USING (
        report_id IN (
            SELECT r.id FROM reports r
            JOIN projects p ON p.id = r.project_id
            WHERE is_org_member(p.organization_id)
        )
    );

-- audit_logs: members of the organization can read (append-only; no user UPDATE/DELETE policy)
DROP POLICY IF EXISTS audit_logs_tenant_read ON audit_logs;
CREATE POLICY audit_logs_tenant_read ON audit_logs
    FOR SELECT USING (
        organization_id IS NOT NULL AND is_org_member(organization_id)
    );

-- Extend the existing `projects_own_data` policy (firm-based) so
-- organization-based projects are ALSO visible to their members. Postgres
-- RLS combines multiple permissive policies on the same table with OR, so
-- this adds organization-based access without removing the legacy
-- firm-based policy from 004_supabase_platform.sql.
DROP POLICY IF EXISTS projects_org_member_read ON projects;
CREATE POLICY projects_org_member_read ON projects
    FOR SELECT USING (
        organization_id IS NOT NULL AND is_org_member(organization_id)
    );

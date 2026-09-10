# Autonomous HCAI Compliance Engine

> Streamlining California Healthcare Construction Plan Reviews

An AI-assisted compliance engine that helps simulate HCAI (Healthcare Construction Analysis and Inspection) plan reviews for California healthcare construction projects. It combines a deterministic, rule-based HCAI compliance dataset, intelligent condition matching, and a RAG (Retrieval-Augmented Generation) layer grounded in Title 24 codes, PINs, and CANs to draft AHJ-style comments with citations.

**Compliance findings are produced by the deterministic rule engine, not the AI model.** The Claude/RAG layer is used only to *explain, cite, and phrase* findings that the rule engine already determined — it never decides on its own whether something is a violation.

> **Accuracy disclaimer:** This project does not currently have a validated measurement of real-world AHJ match rate. See [Validation & Accuracy](#validation--accuracy) below for what is actually measured today.


---

## How It Works

```
Raw Project Drawings & Specs (PDF/DWG)
          │
          ▼
┌─────────────────────────────────────┐
│  Step 1: Automated Data Extraction  │
│  • Occupancy / facility type        │
│  • MEP systems (HVAC, electrical,   │
│    plumbing, medical gas)           │
│  • Room types and adjacencies       │
│  • Seismic design data (zone, SDS)  │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│  Step 2: Intelligent Decision       │
│          Mapping                    │
│  • Matches conditions against       │
│    the HCAI-specific rules dataset  │
│    (data/hcai_rules.json)           │
│  • Severity scoring:                │
│    Critical / High / Medium / Low   │
└─────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────┐
│  Step 3: RAG-Backed Reporting       │
│  • Retrieves Title 24, PIN, CAN     │
│    passages relevant to each issue  │
│  • Claude API generates AHJ-style   │
│    plan review comments             │
│  • Step-by-step compliance fixes    │
└─────────────────────────────────────┘
          │
          ▼
    HCAI-Style Report
    (Text / JSON / HTML)
```

---

## Features

- **PDF Parser** — extracts text, tables, and metadata from project drawings and specifications
- **Condition Extractor** — identifies occupancy type, MEP systems, room types, seismic data, and location
- **Decision Engine** — matches conditions against a structured HCAI rules dataset with 15+ rule categories
- **Severity Scoring** — prioritizes issues as Critical, High, Medium, or Low based on life-safety impact
- **RAG Knowledge Base** — ChromaDB vector store of Title 24 Part 2/3/4/5, PINs, and CANs
- **AHJ Comment Generator** — Claude-powered generation of accurate plan review comments with citations
- **Report Generator** — outputs Text, JSON, and HTML reports with prioritized violations and fixes
- **Validation Checklist** — benchmarks engine accuracy against known AHJ review findings

---

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd Cali-med-bp

# Install dependencies
pip install -r requirements.txt

# Set your Anthropic API key (optional — fallback mode available without it)
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Usage

### Run a compliance review on a PDF

```bash
python main.py review --input project_drawings.pdf --name "Valley Hospital" --format html
```

### Run the built-in demo

```bash
python main.py demo
```

### Index the regulatory knowledge base

```bash
python main.py index-kb
```

### Run validation against known violations

```bash
python main.py validate --input project.pdf --ground-truth data/sample_violations.json
```

### Available options

```
review [OPTIONS]
  -i, --input PATH          PDF or text file to review
  -t, --text TEXT           Inline project description text
  -n, --name TEXT           Project name for report
  -f, --format [text|json|html|all]   Output format (default: all)
  -o, --output-dir PATH     Output directory
  --no-rag                  Skip RAG/Claude enrichment (faster)
  --validate                Run validation checklist after review
  --ground-truth PATH       Ground truth JSON for validation
```

---

## Project Structure

```
Cali-med-bp/
├── main.py                        # CLI entrypoint
├── config.py                      # Configuration settings
├── requirements.txt
├── data/
│   ├── hcai_rules.json            # HCAI-specific compliance rules
│   ├── title24_references.json    # Title 24 regulatory passages
│   ├── pins_cans.json             # HCAI Policy Intent Notices & CANs
│   ├── sample_violations.json     # Ground truth for validation
│   └── saas/                      # Local JSON fallback store for /api/v1 (dev/test only, gitignored)
├── src/
│   ├── parser/
│   │   ├── pdf_parser.py          # PDF/text document parser
│   │   └── condition_extractor.py # Extracts structured project conditions
│   ├── engine/
│   │   ├── decision_engine.py     # Main compliance decision orchestrator (deterministic, authoritative)
│   │   ├── rule_matcher.py        # Matches conditions to HCAI rules
│   │   └── severity_scorer.py     # Assigns Critical/High/Medium/Low
│   ├── rag/
│   │   ├── knowledge_base.py      # ChromaDB vector store for regulations
│   │   └── generator.py           # Claude-powered AHJ comment generation (explanatory only)
│   ├── reports/
│   │   └── report_generator.py    # Text / JSON / HTML / PDF report output
│   ├── validation/
│   │   └── checklist.py           # Accuracy measurement checklist
│   ├── auth/
│   │   ├── jwt_auth.py            # Supabase JWT verification, get_current_user
│   │   ├── roles.py               # OWNER/ADMIN/REVIEWER/MEMBER/VIEWER role model
│   │   └── deps.py                # Org/project membership FastAPI dependencies
│   ├── analysis/
│   │   └── pipeline.py            # Async analysis job: parse -> extract -> evaluate -> RAG -> report
│   ├── database/
│   │   ├── client.py              # Supabase client singleton
│   │   ├── repositories.py        # Legacy CLI repositories (firms/reviews/violations/feedback)
│   │   ├── repositories_v1.py     # /api/v1 SaaS repositories (Supabase-or-local-store)
│   │   └── local_store.py         # JSON-file-backed fallback store (dev/test only)
│   └── api/
│       ├── security.py            # Legacy static-token auth for /feedback, /query
│       ├── uploads.py              # Secure document upload validation
│       ├── feedback_endpoints.py
│       ├── query_endpoints.py
│       └── v1/                    # Versioned SaaS API (see "API — /api/v1" below)
│           ├── organizations.py
│           ├── projects.py
│           ├── documents.py
│           ├── analyses.py
│           ├── findings.py
│           ├── reports.py
│           ├── revisions.py
│           └── router.py
└── tests/
    ├── test_parser.py
    ├── test_engine.py
    ├── test_rag.py
    ├── test_api_security.py       # Legacy token-auth tests
    ├── test_api_v1_auth.py        # Supabase JWT auth tests
    ├── test_api_v1_tenancy.py     # Tenant isolation + full analysis workflow
    └── test_api_v1_uploads.py     # Upload validation edge cases
```

---

## API — `/api/v1` (multi-tenant SaaS layer)

In addition to the legacy `/feedback/*` and `/query/*` endpoints (still available, unchanged), the server now exposes a versioned, multi-tenant REST API:

```
GET    /health
GET    /ready

POST   /api/v1/organizations
GET    /api/v1/organizations

POST   /api/v1/projects
GET    /api/v1/projects?organization_id=...
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}
DELETE /api/v1/projects/{project_id}

POST   /api/v1/projects/{project_id}/documents        (multipart file upload)
GET    /api/v1/projects/{project_id}/documents
GET    /api/v1/projects/{project_id}/documents/{document_id}
DELETE /api/v1/projects/{project_id}/documents/{document_id}

POST   /api/v1/projects/{project_id}/analyses         (returns 202 + analysis id; runs async)
GET    /api/v1/projects/{project_id}/analyses
GET    /api/v1/projects/{project_id}/analyses/{analysis_id}

GET    /api/v1/projects/{project_id}/findings
GET    /api/v1/projects/{project_id}/reports

POST   /api/v1/projects/{project_id}/revisions        (re-analysis of an updated document)
GET    /api/v1/projects/{project_id}/revisions
```

**Data model (see `migrations/006_saas_tenant_model.sql`):** `organizations` -> `memberships` (role) -> `projects` -> `project_members` (optional per-project role override) -> `documents` -> `analyses`/`analysis_runs` -> `findings`/`finding_evidence` -> `reports`/`report_versions`, plus `audit_logs` for every mutating action. This extends the existing legacy schema (`firms`, `projects`, `reviews`, `violations` from `migrations/004_supabase_platform.sql`) additively — `projects.organization_id` was added as a nullable column alongside the existing `firm_id`, so the legacy single-owner CLI/`firms` flow keeps working unchanged.

**Analysis pipeline (`src/analysis/pipeline.py`):** `POST .../analyses` immediately returns `202 Accepted` with `status: "QUEUED"` and runs the job via a FastAPI `BackgroundTask` (single-process MVP): PDF parser -> condition extractor -> **deterministic decision engine (authoritative)** -> RAG enrichment (explanatory only — never changes a finding's severity or trigger condition) -> report writer (JSON/HTML/PDF), transitioning `QUEUED -> PROCESSING -> COMPLETED|FAILED`. For multi-worker/horizontally-scaled deployments, replace the `BackgroundTasks.add_task(run_analysis, analysis_id)` call with an enqueue onto Celery/RQ + Redis; `run_analysis(analysis_id)` takes only the analysis id, so it can be handed to any worker without modification.

**Findings provenance:** every finding returned by `GET .../findings` carries `rule_id`, `discipline`, `severity`, `requirement`, `project_evidence`, `jurisdiction`, `code_family`, `source_reference`, `citation_verified`, `confidence`, and `recommended_action` — derived directly from `MatchedViolation.provenance()` (see "Regulatory Provenance" below). No citation is fabricated; unverifiable citations are marked `citation_verified: false`.

**Local-first, Supabase-ready:** all `/api/v1` repositories (`src/database/repositories_v1.py`) use Supabase when `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` are configured (with Postgres RLS enforcing tenant isolation), and otherwise fall back to a JSON-file-backed local store (`src/database/local_store.py`, under `data/saas/`, gitignored) so the full API is runnable and testable without any cloud dependency. The local-store fallback is a development/test convenience only — it enforces tenant isolation in Python (every repository call is scoped by organization/project id) but does not have Postgres RLS, and is not safe for multi-instance production use.

---

## Compliance Coverage

| Discipline | Example Rules | Severity |
|---|---|---|
| Infection Control | Isolation room negative pressure, OR positive pressure, HEPA filtration | Critical |
| Structural / Seismic | OSHPD anchorage (Zone D/E, Ip=1.5), seismic ceiling systems | Critical |
| Essential Electrical System | EES branch separation, NFPA 99, transfer time | Critical |
| Medical Gas | NFPA 99 compliance, zone valves, alarm panels | Critical |
| Fire Protection | Smoke compartmentalization, smoke barriers | Critical |
| Ventilation | ICU/OR/SPD ACH rates, pressure differentials | High |
| Plumbing | ASSE 1070 mixing valves, scrub sinks, Legionella control | High |
| Electrical | Patient care circuits, isolated ground receptacles | High |
| Accessibility | CBC Chapter 11B, turning radii, grab bars | Medium |

---

## Regulatory References

- **Title 24 Part 2** — California Building Code (CBC)
- **Title 24 Part 3** — California Electrical Code (CEC / NFPA 70 Article 517)
- **Title 24 Part 4** — ASHRAE Standard 170 (Ventilation in Healthcare)
- **Title 24 Part 5** — California Plumbing Code (CPC)
- **NFPA 99** — Health Care Facilities Code
- **NFPA 101** — Life Safety Code
- **HCAI PINs** — Policy Intent Notices (18-01 through 25-04)
- **HCAI CANs** — Construction Advisory Notices
- **FGI Guidelines 2018** — Facility Guidelines Institute

---

## Validation & Accuracy

`python main.py validate` and `python main.py demo --validate` run `src.validation.checklist.ComplianceChecklist`, which measures:

- **extraction** — whether occupancy/seismic/room data was parsed at all
- **detection** — whether any violations were found, and how many
- **severity** — whether severities are valid and correctly sorted
- **citation** — whether generated comments include *a* code citation (not whether that citation is authoritative)
- **ground_truth** — token/keyword overlap against `data/sample_violations.json`, a small hand-authored **synthetic** fixture, not a real AHJ plan-check record

**What this does *not* measure:** precision, recall, F1, false-positive rate, false-negative rate, or agreement with an actual HCAI/AHJ reviewer on a real project. There is currently no real-world benchmark dataset in this repository, and the previously published **"85%+ match with real AHJ review comments"** claim was not backed by any such benchmark — it has been removed. The `data/hcai_rules.json` dataset currently contains 15 rules, not "10,000+" as an earlier draft of this README claimed.

If/when a real AHJ benchmark dataset is available, `ComplianceChecklist` should be extended to compute precision/recall/F1, critical-finding recall, and citation/provenance completeness against it, and that result should be reported separately from the synthetic/demo checklist score.

## Regulatory Provenance

Every violation returned by the engine now carries a structured `provenance` block (see `MatchedViolation.provenance()` in `src/engine/rule_matcher.py`) so a user can answer "why was this flagged?":

```json
"provenance": {
  "rule_id": "RULE-001",
  "jurisdiction": "California (HCAI)",
  "code_family": "Title 24",
  "source_reference": ["Title 24 Part 4 ASHRAE 170 Table 7.1", "HCAI PIN 25-04"],
  "citation_verified": true,
  "trigger_condition": "Occupied Hospital",
  "requirement": "...",
  "project_evidence": "Occupied Hospital",
  "recommended_action": "...",
  "confidence": "rule_override"
}
```

`code_family` and `citation_verified` are derived directly from the rule's own `code_references` — the engine never invents a citation. If a rule has no code reference, `citation_verified` is `false` and `code_family` is `null` rather than a fabricated value.

## Security Model

**Legacy service API (`/feedback/*`, `/query/*`):**
- Requires a bearer token for every `/feedback/*` and `/query/*` endpoint once `API_AUTH_TOKENS` is set. `/feedback/retrain`, `/feedback/dashboard`, `/feedback/metrics`, and `/feedback/model/version` additionally require a token from `API_ADMIN_TOKENS` — production model retraining cannot be triggered by a standard API caller. `/health` and `/ready` are always public (required for platform health checks).
- **Fail-closed in production:** if `ENVIRONMENT=production` and no tokens are configured, the server refuses to start rather than running unauthenticated.
- This is a shared service-level API key scheme, not per-user authentication — see `/api/v1` below for the real per-user model.

**SaaS API (`/api/v1/*`):**
- **Authentication:** real per-user identity via Supabase-issued JWTs, verified with `SUPABASE_JWT_SECRET` (HS256, `src/auth/jwt_auth.py`). Unlike the legacy scheme, there is **no dev bypass** — if `SUPABASE_JWT_SECRET` is not configured, every `/api/v1` request is rejected with `503` rather than silently accepting unverified tokens.
- **Authorization:** every project-scoped endpoint resolves the caller's role via `src/auth/deps.py` — either direct project membership (`project_members`) or organization membership (`memberships`), whichever is more privileged. Roles are `OWNER > ADMIN > REVIEWER > MEMBER > VIEWER`. A caller with no membership record gets `404` (not `403`), so the API never confirms or denies that a given organization/project id exists to an unauthorized caller.
- **Tenant isolation:** enforced in two layers — Postgres Row Level Security (`migrations/006_saas_tenant_model.sql`) when Supabase is configured, and application-level scoping in every repository method (`repositories_v1.py`) regardless of backend. This was verified against a real local Postgres instance: a user in Organization A cannot read Organization B's `organizations`/`projects` rows (see test `test_cross_org_project_access_is_denied`).
- **Audit logging:** every project/document/analysis mutation writes an `audit_logs` row (`organization_id`, `project_id`, `actor_user_id`, `action`, `detail`).

**Uploads (`POST /api/v1/projects/{project_id}/documents`, `src/api/uploads.py`):**
- Extension allow-list (`.pdf`, `.txt`) and MIME-type allow-list, rejecting anything else with `400`.
- Filename validated against null bytes, path separators, `.`/`..`, and unsafe characters; the file is **never** written to disk using the caller-supplied filename — a new random UUID is generated for on-disk storage, with the original filename retained only as display metadata.
- File size capped at `MAX_UPLOAD_BYTES` (default 50 MB).
- PDF uploads are checked for a valid `%PDF-` magic-byte header, rejecting files that merely claim to be PDFs.
- Stored files are `chmod 640` (not executable).
- **Not implemented:** dedicated malware/antivirus scanning (e.g. ClamAV) of uploaded content — this is a real gap for production deployments accepting untrusted uploads at scale and should be added before opening uploads to the public internet.

**AI/RAG input handling:** uploaded document text is treated as untrusted data, not instructions. `src/rag/generator.py`'s system prompt is fixed and separate from any document-derived content passed as user-turn context; the deterministic `DecisionEngine`/`RuleMatcher` — not Claude — decides which findings exist, so a prompt-injection attempt embedded in a PDF cannot fabricate or suppress a compliance finding, only (at most) degrade the quality of the AI-generated explanatory text for a finding that was already deterministically triggered.

**General:**
- **No raw exception leakage:** unhandled exceptions are logged server-side and return a generic `Internal server error` message to the client instead of exception internals.
- **Rate limiting:** a per-IP/per-path in-memory sliding-window limiter (`RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`) protects `/feedback/*`, `/query/*`, and `POST /api/v1/.../analyses`. This is single-process only; a multi-instance deployment should replace it with a shared store (e.g. Redis) before scaling horizontally — there is currently no per-user/per-organization rate limit tier, only per-IP.
- **CORS:** disabled by default; set `CORS_ALLOWED_ORIGINS` (comma-separated) to allow specific frontend origins.
- **API docs:** `/docs`, `/redoc`, and `/openapi.json` are disabled automatically when `ENVIRONMENT=production`.
- **Database RLS:** Supabase Row Level Security is enabled on all tenant-scoped tables — both the legacy tables (`firms`, `projects`, `reviews`, `violations`, `feedback_records`) and the new SaaS tables (`organizations`, `memberships`, `project_members`, `documents`, `analyses`, `findings`, `reports`, `audit_logs`, etc.) — plus internal ML tables (`model_versions`, `performance_metrics`) with no end-user access policy at all. See `migrations/005_security_hardening.sql` and `migrations/006_saas_tenant_model.sql`.
- **Feedback → model safety:** submitted AHJ feedback is stored as candidate training data only. `ModelTrainer._is_improvement()` gates whether a retrained model ever replaces the active production model (requires ≥0.02 F1 improvement), and manual retraining is admin-token-protected.

**Known gaps (not yet implemented):** there is no member-invitation flow (inviting another user to an organization by email, or changing another member's role) beyond direct repository insertion; a user currently becomes `OWNER` of any organization they create via `POST /api/v1/organizations` with no approval step. There is no dedicated malware scanning of uploads. The `/api/v1` rate limit is per-IP, not per-user/per-organization.

## Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API for AHJ comment generation | No (template fallback used if unset) |
| `CLAUDE_MODEL` | Claude model name | No |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_ANON_KEY` | Supabase database/auth/storage | No (local file/JSON fallback if unset) |
| `SUPABASE_JWT_SECRET` | HS256 shared secret used to verify `/api/v1` Supabase-issued access tokens | **Yes**, to use `/api/v1` at all (fails closed with 503 otherwise) |
| `SUPABASE_JWT_AUDIENCE` | Expected JWT `aud` claim | No (defaults to `authenticated`) |
| `API_AUTH_TOKENS` | Comma-separated bearer tokens for legacy `/feedback/*`, `/query/*` access | Yes, in production |
| `API_ADMIN_TOKENS` | Comma-separated bearer tokens for legacy admin endpoints (`/feedback/retrain`, `/feedback/dashboard`, `/feedback/metrics`, `/feedback/model/version`) | Yes, in production |
| `ENVIRONMENT` | Set to `production` to enforce fail-closed auth and disable API docs | Recommended in production |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed origins for browser clients | No |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | Rate limiter tuning | No |
| `UPLOAD_DIR` | Local filesystem root for `/api/v1` document uploads | No (defaults to `./uploads`) |
| `MAX_UPLOAD_BYTES` | Max accepted upload size in bytes | No (defaults to 50 MB) |
| `ALERT_WEBHOOK_URL`, `ALERT_EMAIL_*` | Monitoring alerts | No |
| `BATCH_MAX_WORKERS`, `BATCH_CHUNK_SIZE` | Batch PDF processing | No |

## Deployment

- **Backend (Railway):** `railway.toml` runs `python main.py serve --host 0.0.0.0 --port $PORT`. Set `ENVIRONMENT=production`, `API_AUTH_TOKENS`, `API_ADMIN_TOKENS`, `SUPABASE_JWT_SECRET` (to enable `/api/v1`), and the Supabase/Anthropic variables above in the Railway dashboard. `/health` and `/ready` are available for Railway's health checks.
- **Frontend (Netlify):** `netlify.toml` deploys the static `public/` site and proxies `/feedback/*`, `/query/*`, `/api/v1/*`, `/docs`, and `/openapi.json` to the Railway backend.
- **Database/Auth/Storage (Supabase):** apply migrations **in order**: `migrations/003_feedback_tables.sql`, `migrations/004_supabase_platform.sql`, `migrations/005_security_hardening.sql`, `migrations/006_saas_tenant_model.sql`. Migration 006 was validated against a real local Postgres instance (schema apply + seeded-data RLS isolation test), not just reviewed for syntax.
- **Local development without Supabase:** `/api/v1` works end-to-end with no external services — set only `SUPABASE_JWT_SECRET` to any value, mint a matching test JWT, and the API persists to `data/saas/*.json` via the local-store fallback. This is documented as dev/test-only (no RLS, single-process).

## Limitations

- The engine analyzes **extracted text and regex-derived structured data** from PDFs — it does not currently perform sheet/drawing classification, geometry extraction, or CAD/BIM (DWG/Revit/IFC) analysis. Compliance findings are only as good as what the parser/condition-extractor can detect from text. `/api/v1` document uploads currently only support `.pdf` and `.txt` for this reason.
- **No real-world AHJ benchmark validation exists yet.** The synthetic/demo validation checklist (`src/validation/checklist.py`) measures extraction/detection/severity/citation-presence against a small hand-authored fixture (`data/sample_violations.json`), not agreement with an actual HCAI/AHJ reviewer on a real project. Precision/recall/F1/critical-finding-recall against real AHJ-reviewed plans have not been measured. Do not advertise any accuracy percentage until this benchmark exists.
- The async analysis job runs via FastAPI `BackgroundTasks` in-process — reliable for a single-worker MVP deployment, but it does not survive a process restart mid-analysis and does not scale across multiple worker processes. A durable queue (Celery/RQ + Redis) is the documented upgrade path; `run_analysis(analysis_id)` in `src/analysis/pipeline.py` is already queue-agnostic.
- The `/api/v1` rate limiter is per-IP/in-memory, not per-user/per-organization, and does not enforce a global limit across multiple server instances.
- There is no member-invitation flow for organizations — a user becomes `OWNER` of any organization they create, with no approval step, and there is no way to invite/remove another user's membership via the API yet (only via direct repository/database access).
- No dedicated malware/antivirus scanning of uploaded documents.
- Do not treat any generated comment as a substitute for a licensed HCAI/AHJ plan reviewer's determination.

---

## License

MIT License — Copyright 2026 Mason

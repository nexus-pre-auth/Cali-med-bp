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
│   └── sample_violations.json     # Ground truth for validation
├── src/
│   ├── parser/
│   │   ├── pdf_parser.py          # PDF/text document parser
│   │   └── condition_extractor.py # Extracts structured project conditions
│   ├── engine/
│   │   ├── decision_engine.py     # Main compliance decision orchestrator
│   │   ├── rule_matcher.py        # Matches conditions to HCAI rules
│   │   └── severity_scorer.py     # Assigns Critical/High/Medium/Low
│   ├── rag/
│   │   ├── knowledge_base.py      # ChromaDB vector store for regulations
│   │   └── generator.py           # Claude-powered AHJ comment generation
│   ├── reports/
│   │   └── report_generator.py    # Text / JSON / HTML report output
│   └── validation/
│       └── checklist.py           # Accuracy measurement checklist
└── tests/
    ├── test_parser.py
    ├── test_engine.py
    └── test_rag.py
```

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

- **API authentication:** The FastAPI server (`python main.py serve`) requires a bearer token for every `/feedback/*` and `/query/*` endpoint once `API_AUTH_TOKENS` is set. `/feedback/retrain` additionally requires a token from `API_ADMIN_TOKENS` — production model retraining cannot be triggered by a standard API caller. `/health` and `/ready` are always public (required for platform health checks).
- **Fail-closed in production:** if `ENVIRONMENT=production` and no tokens are configured, the server refuses to start rather than running unauthenticated.
- **No raw exception leakage:** unhandled exceptions are logged server-side and return a generic `Internal server error` message to the client instead of exception internals.
- **Rate limiting:** a per-IP/per-path in-memory sliding-window limiter (`RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`) protects `/feedback/*` and `/query/*`. This is single-process only; a multi-instance deployment should replace it with a shared store (e.g. Redis) before scaling horizontally.
- **CORS:** disabled by default; set `CORS_ALLOWED_ORIGINS` (comma-separated) to allow specific frontend origins.
- **API docs:** `/docs`, `/redoc`, and `/openapi.json` are disabled automatically when `ENVIRONMENT=production`.
- **Database RLS:** Supabase Row Level Security is enabled on all tenant-scoped tables (`firms`, `projects`, `reviews`, `violations`, `feedback_records`) and on internal ML tables (`model_versions`, `performance_metrics`), which have no end-user access policy at all — see `migrations/005_security_hardening.sql`.
- **Feedback → model safety:** submitted AHJ feedback is stored as candidate training data only. `ModelTrainer._is_improvement()` gates whether a retrained model ever replaces the active production model (requires ≥0.02 F1 improvement), and manual retraining is admin-token-protected.

**Known gaps (not yet implemented):** there is no end-user login/session system, no organization/membership CRUD API, and no per-request tenant-scoping middleware on the FastAPI layer — the token scheme above is a service-level API key, not a Supabase-JWT-based per-user auth flow.

## Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API for AHJ comment generation | No (template fallback used if unset) |
| `CLAUDE_MODEL` | Claude model name | No |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_ANON_KEY` | Supabase database/auth | No (file-based fallback if unset) |
| `API_AUTH_TOKENS` | Comma-separated bearer tokens for standard API access | Yes, in production |
| `API_ADMIN_TOKENS` | Comma-separated bearer tokens for admin endpoints (`/feedback/retrain`) | Yes, in production |
| `ENVIRONMENT` | Set to `production` to enforce fail-closed auth and disable API docs | Recommended in production |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed origins for browser clients | No |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | Rate limiter tuning | No |
| `ALERT_WEBHOOK_URL`, `ALERT_EMAIL_*` | Monitoring alerts | No |
| `BATCH_MAX_WORKERS`, `BATCH_CHUNK_SIZE` | Batch PDF processing | No |

## Deployment

- **Backend (Railway):** `railway.toml` runs `python main.py serve --host 0.0.0.0 --port $PORT`. Set `ENVIRONMENT=production`, `API_AUTH_TOKENS`, `API_ADMIN_TOKENS`, and the Supabase/Anthropic variables above in the Railway dashboard. `/health` and `/ready` are available for Railway's health checks.
- **Frontend (Netlify):** `netlify.toml` deploys the static `public/` site and proxies `/feedback/*`, `/query/*`, `/docs`, and `/openapi.json` to the Railway backend.
- **Database/Auth/Storage (Supabase):** apply `migrations/003_feedback_tables.sql`, `migrations/004_supabase_platform.sql`, and `migrations/005_security_hardening.sql` in order.

## Limitations

- The engine analyzes **extracted text and regex-derived structured data** from PDFs — it does not currently perform sheet/drawing classification, geometry extraction, or CAD/BIM (DWG/Revit/IFC) analysis. Compliance findings are only as good as what the parser/condition-extractor can detect from text.
- There is no versioned `/api/v1` project/document/analysis REST API (projects, documents, analyses, findings, reports as first-class resources with background job IDs) in this repository yet — the current API surface is limited to `/feedback/*`, `/query/*`, `/health`, and `/ready`. This is the single largest remaining gap toward the full SaaS architecture described in the product vision.
- There is no browser-based login/session flow; API access is currently a shared bearer token, not per-user Supabase Auth.
- The rate limiter is in-memory and per-process; it will not enforce a global limit across multiple server instances.
- Do not treat any generated comment as a substitute for a licensed HCAI/AHJ plan reviewer's determination.

---

## License

MIT License — Copyright 2026 Mason

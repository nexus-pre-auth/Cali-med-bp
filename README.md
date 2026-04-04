<img src="https://img.shields.io/badge/BlueprintIQ-California%20HCAI%20Compliance-1A365D?style=for-the-badge" alt="BlueprintIQ"/>

# BlueprintIQ — HCAI Compliance Engine

> **California healthcare construction plan reviews, automated.**
> Upload your project drawings and get AHJ-style violations with Title 24 citations in minutes — before you submit to HCAI.

[![Tests](https://img.shields.io/badge/tests-278%20passing-38A169?style=flat-square)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat-square)](https://fastapi.tiangolo.com)
[![Claude](https://img.shields.io/badge/Powered%20by-Claude%20Sonnet-orange?style=flat-square)](https://anthropic.com)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

---

## What It Does

BlueprintIQ reads your project specs or PDF drawings, extracts structured project conditions, runs them against a curated set of California HCAI compliance rules, and generates AHJ-style plan review comments — complete with code citations and step-by-step fix instructions.

**Current as of March 2026:** CBC 2025, NFPA 99-2024, CALGreen 2025, HCAI PIN 26-01.

---

## How It Works

```
PDF / Text Input
      │
      ▼
┌─────────────────────────────────────────┐
│  Step 1 · Document Parsing              │
│  PDFPlumber extracts text from drawings │
│  and specifications. Handles multi-page │
│  sets up to 500 pages.                  │
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│  Step 2 · Condition Extraction          │
│  Identifies: occupancy type, licensed   │
│  beds, construction type, seismic zone, │
│  MEP systems, room types, WUI/FHSZ flag,│
│  county, city, sprinkler status.        │
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│  Step 3 · Rule Matching                 │
│  27 HCAI rules across 12 disciplines.   │
│  Filters by occupancy, systems, rooms,  │
│  seismic zone, construction type, beds, │
│  county, WUI zone, and more.            │
│  Severity: Critical / High / Medium /   │
│  Low — based on life-safety impact.     │
└─────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────┐
│  Step 4 · RAG Enrichment                │
│  ChromaDB semantic search retrieves     │
│  relevant passages from Title 24, HCAI  │
│  PINs, and CANs. Claude generates       │
│  AHJ-style comments with citations.     │
└─────────────────────────────────────────┘
      │
      ▼
 Report (PDF · HTML · JSON · TXT)
 + Email delivery to customer
```

---

## Live Product — [blueprintiq.net](https://blueprintiq.net)

| Tier | Price | Reports |
|---|---|---|
| **Single Report** | $49 | One-time, any project |
| **Professional** | $99/mo | 10 reports/month |
| **Agency** | $299/mo | Unlimited + API access |

Payments via Stripe. PDF delivered by email within 2–4 minutes.

---

## Compliance Coverage (27 Rules · March 2026)

| # | Discipline | Key Requirements | Severity |
|---|---|---|---|
| RULE-001 | Infection Control | AII room negative pressure (−0.01 in. w.g.), monitoring, visual indicators | Critical |
| RULE-002 | Structural / Seismic | OSHPD nonstructural anchorage, Ip = 1.5, CBC Ch. 13 | Critical |
| RULE-003 | Life Safety / Egress | Corridor widths (8 ft patient care), exit separation, egress capacity | Critical |
| RULE-004 | Essential Electrical | EES 3-branch separation, NFPA 99 Ch. 6, ≤10s transfer time | Critical |
| RULE-005 | Medical Gas | NFPA 99 Ch. 5, ZVB locations, MAP / area alarm panels on drawings | Critical |
| RULE-006 | Plumbing | ASSE 1070 TMVs, 140°F supply / 110°F delivery, Legionella control | High |
| RULE-007 | Ventilation | ICU 6 ACH OA, positive pressure, 100% exhaust, ASHRAE 170 | High |
| RULE-008–023 | Fire, Accessibility, SPD, Pharmacy, Electrical, Seismic … | Various CBC/NFPA requirements | High/Med |
| RULE-024 | Medical Gas | ZVB 36-inch clearance + 50-ft proximity (NFPA 99-2021 §5.1.14.2.1) | High |
| **RULE-025** | **Telehealth** *(PIN 26-01 · April 2026)* | Dedicated 20A circuit, STC-45 isolation, 50 fc lighting, HIPAA privacy | Medium |
| **RULE-026** | **Medical Gas** *(NFPA 99-2024 · Jan 2026)* | ZVB BAS integration, IoT pressure monitoring, nursing station alarm | High |
| **RULE-027** | **Wildfire / WUI** *(CBC 2025 · Jan 2026)* | Class A roofing, ember vents, 1-hr exterior walls, 100-ft defensible space | **Critical** |

---

## Quick Start

```bash
git clone https://github.com/your-org/blueprintiq.git
cd blueprintiq

pip install -r requirements.txt
cp .env.example .env
# → add your ANTHROPIC_API_KEY

# Seed rules database
python main.py migrate-db

# Index regulatory knowledge base
python main.py index-kb

# Run a compliance review
python main.py review --input hospital_drawings.pdf --name "Valley Medical Center"
```

### Start the API server

```bash
python serve.py
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### Docker (with optional PostgreSQL)

```bash
# API only (SQLite persistence)
docker compose up hcai-api

# API + PostgreSQL + pgvector
docker compose --profile postgres up
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/checkout/create` | Upload PDF + email → Stripe Checkout ($49) |
| `POST` | `/checkout/webhook` | Stripe webhook — triggers processing after payment |
| `GET` | `/checkout/status` | Resolve Stripe session to job_id |
| `POST` | `/review` | Submit text review (API key required) |
| `POST` | `/review/upload` | Submit PDF review (API key required) |
| `GET` | `/review/{job_id}` | Poll job status and retrieve results |
| `GET` | `/review/{job_id}/report/{fmt}` | Download report (txt/json/html/pdf) |
| `GET` | `/reviews` | List recent jobs |
| `GET` | `/rules` | List all compliance rules |
| `PATCH` | `/rules/{rule_id}/active` | Enable / disable a rule |
| `GET` | `/health` | Liveness check |
| `GET` | `/audit` | Audit trail |

Full interactive docs at `/docs`.

---

## Adding a New Rule

Rules live in `data/hcai_rules.json`. The full schema:

```json
{
  "id": "RULE-028",
  "discipline": "Medical Gas",
  "description": "One-line description of the requirement.",
  "effective_date": "2026-07-01",
  "trigger_occupancies": ["Occupied Hospital", "Acute Care Hospital"],
  "trigger_systems": ["zone valve"],
  "trigger_rooms": [],
  "trigger_seismic_zones": [],
  "trigger_construction_types": [],
  "trigger_counties": [],
  "trigger_cities": [],
  "trigger_wui": null,
  "min_licensed_beds": null,
  "trigger_sprinklered": null,
  "min_building_height_ft": null,
  "min_stories": null,
  "violation_template": "{occupancy} project must comply with ...",
  "fix_template": "1. Do X.\n2. Do Y.",
  "code_references": ["NFPA 99-2024 §5.x.x", "Title 24 Part 2 §1226.6"],
  "severity_override": "High"
}
```

Then add regulatory text to `data/title24_references.json` or `data/pins_cans.json`, seed, and rebuild:

```bash
python main.py migrate-db
python main.py index-kb
```

See [`tests/test_medgas_zvb.py`](tests/test_medgas_zvb.py) for a complete test template.

---

## Project Structure

```
blueprintiq/
├── main.py                          CLI (review, demo, migrate-db, index-kb)
├── serve.py                         FastAPI server launcher
├── config.py                        Global configuration
├── requirements.txt
├── docker-compose.yml               API + optional PostgreSQL service
├── static/
│   └── index.html                   SPA frontend (landing + upload + results)
├── data/
│   ├── hcai_rules.json              27 HCAI compliance rules
│   ├── title24_references.json      16 Title 24 / NFPA regulatory passages
│   ├── pins_cans.json               14 HCAI PINs and CANs
│   └── sample_violations.json       Ground truth for validation
└── src/
    ├── api/
    │   ├── app.py                   FastAPI routes + static serving
    │   ├── billing.py               Stripe Checkout + webhook
    │   ├── email_delivery.py        SMTP PDF report delivery
    │   ├── models.py                Pydantic schemas
    │   ├── runner.py                Async compliance pipeline
    │   ├── auth.py                  API key authentication
    │   └── jobs.py                  In-memory + SQLite job store
    ├── database/                    PostgreSQL layer (optional)
    │   ├── connection.py            SQLAlchemy async engine
    │   ├── models.py                ORM models + pgvector embedding column
    │   └── pg_job_store.py          Async drop-in job store
    ├── engine/
    │   ├── decision_engine.py       Orchestrates rule matching
    │   ├── rule_matcher.py          27-rule filter with 10 trigger types
    │   └── severity_scorer.py       Critical/High/Medium/Low scoring
    ├── parser/
    │   ├── pdf_parser.py            PDFPlumber extraction
    │   └── condition_extractor.py   Structured condition extraction
    ├── rag/
    │   ├── knowledge_base.py        ChromaDB vector store (30 docs)
    │   └── generator.py             Claude AHJ comment generation
    ├── reports/
    │   ├── report_generator.py      Text / JSON / HTML output
    │   └── pdf_report_generator.py  ReportLab PDF output
    └── db/
        ├── migrations.py            7 SQLite schema migrations
        ├── rules_store.py           SQLite rule persistence
        └── job_store.py             SQLite job persistence
```

---

## Regulatory Coverage

| Code | Edition | Status |
|---|---|---|
| CBC (Title 24 Part 2) | **2025** | ✅ Current |
| CEC (Title 24 Part 3) | **2025** | ✅ Current |
| ASHRAE 170 (Title 24 Part 4) | 2021 | ✅ Current |
| CPC (Title 24 Part 5) | **2025** | ✅ Current |
| NFPA 99 | **2024** | ✅ Current |
| CALGreen (Title 24 Part 11) | **2025** | ✅ Current |
| NFPA 101 | 2021 | ✅ Current |
| FGI Guidelines | 2018 | ✅ Current |
| HCAI PINs | Through **26-01** (Apr 2026) | ✅ Current |
| HCAI CANs | Through **2-2024** | ✅ Current |
| CBC Chapter 7A (WUI) | **2025** | ✅ Current |

---

## Environment Variables

Copy `.env.example` → `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Claude API key for AHJ comment generation |
| `STRIPE_SECRET_KEY` | Billing | Stripe secret key (`sk_live_...`) |
| `STRIPE_WEBHOOK_SECRET` | Billing | Stripe webhook signing secret |
| `APP_BASE_URL` | Billing | Public URL (e.g. `https://blueprintiq.net`) |
| `SMTP_USER` | Email | Gmail address for report delivery |
| `SMTP_PASSWORD` | Email | Gmail app password |
| `DB_HOST` | Postgres | Enable PostgreSQL (omit for SQLite) |
| `API_KEYS` | Auth | Comma-separated API keys for `/review` endpoint |

---

## Development

```bash
# Run tests
python -m pytest tests/ -q

# Lint
ruff check .

# Add a rule, re-seed, and test
python main.py migrate-db
python main.py index-kb
python -m pytest tests/test_2026_rules.py -v
```

---

## Disclaimer

BlueprintIQ is an automated screening tool. Reports are generated by AI and are intended for preliminary review only. They do not constitute a licensed engineering or architectural review. Consult a California-licensed professional before submitting to HCAI.

---

**MIT License** · Copyright 2026 BlueprintIQ
[hello@blueprintiq.net](mailto:hello@blueprintiq.net) · [blueprintiq.net](https://blueprintiq.net)

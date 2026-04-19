# CLAUDE.md — AI Assistant Guide for Cali-med-bp

## Project Overview

**Autonomous HCAI Compliance Engine** — A Python CLI tool (with optional FastAPI server) that analyzes California healthcare construction documents (PDFs, text) and generates professional plan review comments in the style of the California Department of Health Care Access and Information (HCAI). It combines rule-based matching, AI-powered text generation (Claude), RAG retrieval over regulatory documents, and a **real-time AHJ feedback loop** that continuously retrains ML models from plan checker corrections.

---

## Repository Structure

```
/
├── main.py                          # CLI entry point (review, demo, batch, serve, …)
├── config.py                        # Centralized configuration (paths, model, RAG, alerts)
├── requirements.txt                 # Python dependencies
├── README.md                        # User-facing documentation
├── scripts/
│   ├── setup_monitoring.py         # Interactive wizard: webhook + email alert setup
│   └── weekly_retrain.py           # Standalone cron script for weekly model retraining
├── data/                            # Regulatory knowledge datasets + runtime data
│   ├── hcai_rules.json             # 15+ structured compliance rules
│   ├── title24_references.json     # Title 24 regulatory passages for RAG
│   ├── pins_cans.json              # HCAI Policy Intent Notices / CANs
│   ├── sample_violations.json      # Ground-truth for validation tests
│   ├── feedback/                   # AHJ feedback JSON files (one per submission)
│   ├── metrics/                    # Aggregated accuracy metrics (JSON)
│   │   ├── violation_accuracy.json
│   │   ├── waiver_accuracy.json
│   │   ├── comment_quality.json
│   │   ├── rule_accuracy.json
│   │   └── audit_log.json
│   └── models/                     # Versioned ML model artifacts (joblib)
│       ├── version.txt             # Active model version pointer
│       ├── feature_importance.json
│       ├── model_metrics.json      # Training history
│       └── v1.0.0/                 # Model directory per version
│           ├── waiver_model.pkl
│           ├── violation_model.pkl
│           └── severity_model.pkl
├── src/
│   ├── parser/
│   │   ├── pdf_parser.py           # PDF/text extraction (pdfplumber)
│   │   └── condition_extractor.py  # Regex-based structured data extraction
│   ├── engine/
│   │   ├── decision_engine.py      # Main orchestrator: loads rules, runs evaluation
│   │   ├── rule_matcher.py         # Rule matching logic + MatchedViolation dataclass
│   │   ├── severity_scorer.py      # Severity enum + keyword-based scoring
│   │   └── batch_processor.py      # Concurrent batch PDF review (ThreadPoolExecutor)
│   ├── rag/
│   │   ├── knowledge_base.py       # ChromaDB vector store for regulatory docs
│   │   ├── generator.py            # Claude API + fallback template comment generation
│   │   └── nl_query.py             # Natural-language compliance query (RAG + Claude)
│   ├── reports/
│   │   └── report_generator.py     # Text, JSON, and HTML report writers
│   ├── validation/
│   │   └── checklist.py            # Accuracy measurement vs. ground truth
│   ├── feedback/
│   │   ├── __init__.py
│   │   ├── models.py               # AHJFeedback + FeedbackBatch Pydantic models
│   │   └── processor.py            # Storage, metric update, retraining gate
│   ├── api/
│   │   ├── __init__.py
│   │   ├── feedback_endpoints.py   # /feedback/* REST endpoints
│   │   └── query_endpoints.py      # /query/* natural-language REST endpoints
│   └── ml/
│       ├── __init__.py
│       ├── trainer.py              # RandomForest/GBM/LogReg model training
│       ├── continuous_learning.py  # APScheduler-driven retraining + digest jobs
│       └── alerting.py             # Webhook (Slack/Teams) + email alert delivery
├── templates/
│   ├── feedback_dashboard.html     # Real-time metrics dashboard (Chart.js)
│   └── feedback_widget.html        # Embeddable reviewer feedback widget
└── migrations/
│   └── 003_feedback_tables.sql     # PostgreSQL schema for feedback + model registry
└── tests/
    ├── test_parser.py
    ├── test_engine.py
    └── test_rag.py
```

---

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.9+ |
| CLI | Click + Rich |
| PDF parsing | pdfplumber |
| AI generation | Anthropic Claude (`claude-sonnet-4-6`) |
| Vector DB (RAG) | ChromaDB + sentence-transformers |
| Data validation | Pydantic v2 |
| HTML templates | Jinja2 |
| Testing | pytest |
| **API server** | **FastAPI + Uvicorn** |
| **ML models** | **scikit-learn (RandomForest, GBM, LogisticRegression)** |
| **Scheduler** | **APScheduler 3.x** |
| **Model persistence** | **joblib** |

---

## Data Flow Pipeline

### Compliance Review (CLI)

```
INPUT (PDF or text string)
    ↓
[PDFParser]              — Extract raw text and tables per page
    ↓
[ConditionExtractor]     — Regex patterns → ProjectConditions dataclass
    ↓
[DecisionEngine]         — Load hcai_rules.json, apply RuleMatcher
    ↓
[SeverityScorer]         — Assign Critical / High / Medium / Low
    ↓
[HCAIKnowledgeBase]      — Semantic search for relevant regulatory passages
    ↓
[AHJCommentGenerator]    — Claude API (or template fallback) → AHJ-style text
    ↓
[ReportWriter]           — Emit .txt, .json, .html to output/
    ↓
[ComplianceChecklist]    — Optional: score accuracy vs. sample_violations.json
```

### Continuous Learning Loop (API server)

```
AHJ Reviewer submits feedback  (POST /feedback/submit)
    ↓
[FeedbackProcessor.store_feedback]   — JSON file written to data/feedback/
    ↓
[FeedbackProcessor.process_feedback_batch]  — Metric files updated
    ↓
[should_retrain?]   — True when ≥ 50 submissions in last 24 h
    ↓ (yes)
[ModelTrainer.trigger_retraining]   — Load metrics → train → evaluate
    ↓
[_is_improvement?]  — New F1 must beat current by ≥ 0.02
    ↓ (yes)
[_save_models]      — Persist to data/models/<version>/
    ↓
[ContinuousLearningPipeline]  — APScheduler also fires:
    • Daily at 02:00  (if ≥ 25 new feedback entries)
    • Weekly Sunday 03:00 (full retrain)
    • Hourly metric roll-up (emergency retrain if avg F1 < 0.70)
```

---

## Configuration (`config.py`)

```python
CLAUDE_MODEL = "claude-sonnet-4-6"   # Change to update AI model
RAG_TOP_K = 5                         # Regulatory passages retrieved per violation
RAG_COLLECTION_NAME = "hcai_compliance_kb"
CHROMA_DB_DIR = BASE_DIR / "chroma_db"
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
```

Environment variables (loaded via `.env`):
- `ANTHROPIC_API_KEY` — Required for Claude-powered comments; omit for template fallback.
- `ALERT_WEBHOOK_URL` — Slack/Teams incoming webhook for performance alerts.
- `ALERT_EMAIL_FROM/TO` + `ALERT_SMTP_*` — SMTP settings for daily email digest.
- `BATCH_MAX_WORKERS` — Parallel threads for batch reviews (default: 4).
- `BATCH_CHUNK_SIZE` — Files per async chunk (default: 10).

Run `python scripts/setup_monitoring.py` to configure alert settings interactively.

---

## CLI Commands

```bash
# Full compliance review from PDF or text
python main.py review --input project.pdf --format html
python main.py review --text "Occupied hospital, seismic zone D..." --name "Sample Project"

# Batch review — all PDFs in a directory (parallel)
python main.py batch --input-dir /drawings --output-dir /reports --workers 8

# Demo run with synthetic hospital data (no input needed)
python main.py demo

# Index regulatory documents into ChromaDB for RAG
python main.py index-kb

# Validate output accuracy against ground truth
python main.py validate --input project.pdf

# Start FastAPI server with real-time feedback loop
python main.py serve
python main.py serve --host 127.0.0.1 --port 9000 --no-learning

# Configure monitoring alerts (interactive wizard)
python scripts/setup_monitoring.py
python scripts/setup_monitoring.py --check   # test existing config

# Standalone weekly retrain (for cron use)
python scripts/weekly_retrain.py
```

**`serve` endpoints:**

| Method | Path | Purpose |
|---|---|---|
| POST | `/feedback/submit` | Submit single AHJ feedback |
| POST | `/feedback/batch` | Submit multiple feedback entries |
| GET | `/feedback/metrics?days=30` | Aggregated accuracy metrics |
| GET | `/feedback/dashboard` | Dashboard JSON data |
| GET | `/feedback/dashboard/ui` | Browser dashboard (HTML) |
| POST | `/feedback/retrain` | Manually trigger retraining |
| GET | `/feedback/model/version` | Active model version |
| POST | `/query/ask` | Natural-language compliance question |
| POST | `/query/checklist` | Generate back-check prevention checklist |
| POST | `/query/violations/summarise` | Filter/summarise violation list |
| GET | `/docs` | Swagger UI |

---

## Key Conventions

### Rule Schema (`data/hcai_rules.json`)
Each rule object must have:
```json
{
  "id": "RULE-NNN",
  "discipline": "Infection Control",
  "description": "Short description",
  "trigger_occupancies": ["Occupied Hospital"],
  "trigger_systems": [],
  "trigger_rooms": ["isolation room"],
  "trigger_seismic_zones": [],
  "violation_template": "Text with {occupancy} placeholders",
  "fix_template": "Remediation steps with {county} placeholders",
  "code_references": ["Title 24 Part 4 ASHRAE 170 Table 7.1"],
  "severity_override": "Critical"
}
```
Supported template variables: `{occupancy}`, `{construction_type}`, `{seismic_zone}`, `{county}`, `{city}`.

### Feedback Schema (`src/feedback/models.py`)
Key fields on `AHJFeedback`:
- `feedback_type` — one of `FeedbackType` enum values
- `false_positives` / `false_negatives` — lists of `rule_id` strings
- `ahj_actual_violations` — what the real AHJ cited (list of dicts)
- `waiver_predicted_probability` / `waiver_actual_outcome` — for waiver feedback

### Severity Levels
Ordered: `CRITICAL > HIGH > MEDIUM > LOW`

Keyword triggers (in `severity_scorer.py`):
- **Critical:** life safety, fire protection, emergency power, seismic, isolation, infection control
- **High:** HVAC, ventilation, operating room, electrical, ICU
- **Medium:** plumbing, accessibility, ADA

### ML Model Versioning
- Models live under `data/models/<vX.Y.Z>/`
- `data/models/version.txt` holds the active version string
- `ModelTrainer._increment_version()` bumps the patch number
- A new model only replaces the current one if F1 improves by ≥ 0.02 on at least one model type
- Minimum 100 training samples required before retraining runs

### Adding New Rules
1. Add a JSON object to `data/hcai_rules.json` following the schema above.
2. Add supporting regulatory passages to `data/title24_references.json` or `data/pins_cans.json`.
3. Re-run `python main.py index-kb` to rebuild the ChromaDB collection.
4. Add a ground-truth entry in `data/sample_violations.json` for validation.

### Adding New Occupancy/System/Room Keywords
Edit the regex patterns in `src/parser/condition_extractor.py`:
- `OCCUPANCY_PATTERNS` — list of (regex, occupancy_string) tuples
- `MEP_KEYWORDS` — dict of system category → keyword list
- `ROOM_KEYWORDS` — list of room type strings

---

## Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_engine.py
```

Tests use pytest fixtures and do **not** require an `ANTHROPIC_API_KEY` (RAG tests use template fallback mode).

**Target accuracy:** 85%+ match with real HCAI review comments (measured by `ComplianceChecklist`).

---

## Output Files

Reports are written to `output/` (created at runtime):
- `hcai_report.txt` — Plain-text AHJ comment sheet
- `hcai_report.json` — Machine-readable structured report
- `hcai_report.html` — Styled interactive HTML with severity badges

Runtime data directories (created automatically, excluded from git):
- `data/feedback/` — One JSON file per AHJ feedback submission
- `data/metrics/` — Rolling accuracy metric files
- `data/models/` — Versioned ML model artifacts
- `chroma_db/` — ChromaDB vector store

---

## Important Notes for AI Assistants

1. **Optional web server** — FastAPI is only active when `python main.py serve` is used. The `review`, `demo`, `index-kb`, and `validate` commands remain pure CLI and have no web dependency.
2. **Fallback mode** — All Claude API calls in `generator.py` have a template-based fallback. Preserve this pattern when modifying AI integration.
3. **`--no-rag` behavior** — The `--no-rag` flag disables ChromaDB retrieval context only; the Claude API is still called when `ANTHROPIC_API_KEY` is set. To get fully template-based output (no API calls), omit `ANTHROPIC_API_KEY` as well.
4. **Pydantic v2** — The project uses Pydantic v2 syntax throughout (`model_dump()`, `model_validate()`, `@field_validator`). Do not revert to v1 patterns.
5. **Data files are source of truth** — Business logic lives in `data/*.json`, not hardcoded in Python. Prefer editing JSON rules over adding Python conditionals.
6. **No database migrations required** — The feedback/metrics/models pipeline uses JSON files by default. `migrations/003_feedback_tables.sql` is provided for teams that want PostgreSQL persistence; it is not required to run the system.
7. **ChromaDB collection** — If changing `RAG_COLLECTION_NAME` in `config.py`, delete `chroma_db/` and re-run `index-kb`.
8. **Regex-heavy extraction** — `condition_extractor.py` uses case-insensitive regex. Test new patterns against varied capitalization.
9. **Template variables** — `violation_template` and `fix_template` strings use `{key}` placeholders replaced in `rule_matcher.py`. Adding new placeholders requires updating the substitution dict in that file.
10. **ML retraining gate** — `ModelTrainer._is_improvement()` must return `True` for a new model to be saved. The threshold is 0.02 absolute F1. When writing tests, mock `_is_improvement` to `True` to force saves.
11. **Scheduler graceful degradation** — `ContinuousLearningPipeline` checks `HAS_SCHEDULER` at import time; if APScheduler is missing the pipeline silently disables itself — it does not crash the server.

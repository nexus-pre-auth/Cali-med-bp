# CLAUDE.md — AI Assistant Guide for Cali-med-bp

## Project Overview

**Autonomous HCAI Compliance Engine** — A Python CLI tool that analyzes California healthcare construction documents (PDFs, text) and generates professional plan review comments in the style of the California Department of Health Care Access and Information (HCAI). It combines rule-based matching, AI-powered text generation (Claude), and RAG retrieval over regulatory documents.

---

## Repository Structure

```
/
├── main.py                        # CLI entry point (Click commands)
├── config.py                      # Centralized configuration (paths, model, RAG settings)
├── requirements.txt               # Python dependencies
├── README.md                      # User-facing documentation
├── data/                          # Regulatory knowledge datasets (JSON)
│   ├── hcai_rules.json           # 15+ structured compliance rules
│   ├── title24_references.json   # Title 24 regulatory passages for RAG
│   ├── pins_cans.json            # HCAI Policy Intent Notices / CANs
│   └── sample_violations.json    # Ground-truth for validation tests
├── src/
│   ├── parser/
│   │   ├── pdf_parser.py         # PDF/text extraction (pdfplumber)
│   │   └── condition_extractor.py# Regex-based structured data extraction
│   ├── engine/
│   │   ├── decision_engine.py    # Main orchestrator: loads rules, runs evaluation
│   │   ├── rule_matcher.py       # Rule matching logic + MatchedViolation dataclass
│   │   └── severity_scorer.py    # Severity enum + keyword-based scoring
│   ├── rag/
│   │   ├── knowledge_base.py     # ChromaDB vector store for regulatory docs
│   │   └── generator.py          # Claude API + fallback template comment generation
│   ├── reports/
│   │   └── report_generator.py   # Text, JSON, and HTML report writers
│   └── validation/
│       └── checklist.py          # Accuracy measurement vs. ground truth
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

---

## Data Flow Pipeline

```
INPUT (PDF or text string)
    ↓
[PDFParser]              — Extract raw text and tables per page
    ↓
[ConditionExtractor]     — Regex patterns → ProjectConditions dataclass
                           (occupancy, seismic, systems, room types, location)
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

---

## Configuration (`config.py`)

Key settings to be aware of when modifying behavior:

```python
CLAUDE_MODEL = "claude-sonnet-4-6"   # Change to update AI model
RAG_TOP_K = 5                         # Regulatory passages retrieved per violation
RAG_COLLECTION_NAME = "hcai_compliance_kb"
CHROMA_DB_DIR = BASE_DIR / "chroma_db"  # Vector DB persisted here
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
```

Environment variables (loaded via `.env`):
- `ANTHROPIC_API_KEY` — Required for Claude-powered comments; omit to use template fallback mode.

---

## CLI Commands

```bash
# Full compliance review from PDF or text
python main.py review --input project.pdf --format html
python main.py review --text "Occupied hospital, seismic zone D..." --name "Sample Project"

# Demo run with synthetic hospital data (no input needed)
python main.py demo

# Index regulatory documents into ChromaDB for RAG
python main.py index-kb

# Validate output accuracy against ground truth
python main.py validate --input project.pdf
```

Options: `--no-rag` skips Claude enrichment; `--format [text|json|html|all]` controls output.

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

### Severity Levels
Ordered: `CRITICAL > HIGH > MEDIUM > LOW`

Keyword triggers (in `severity_scorer.py`):
- **Critical:** life safety, fire protection, emergency power, seismic, isolation, infection control
- **High:** HVAC, ventilation, operating room, electrical, ICU
- **Medium:** plumbing, accessibility, ADA

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

---

## Important Notes for AI Assistants

1. **No web framework** — This is a CLI-only tool. Do not introduce Flask/FastAPI unless explicitly requested.
2. **Fallback mode** — All Claude API calls in `generator.py` have a template-based fallback. Preserve this pattern when modifying AI integration.
3. **Pydantic v2** — The project uses Pydantic v2 syntax. Do not revert to v1 patterns (`@validator` → use `@field_validator`, `model.dict()` → `model.model_dump()`).
4. **Data files are source of truth** — Business logic lives in `data/*.json`, not hardcoded in Python. Prefer editing JSON rules over adding Python conditionals.
5. **No database migrations** — The only persistent state is the ChromaDB directory (`chroma_db/`). Deleting it requires re-running `index-kb`.
6. **Regex-heavy extraction** — `condition_extractor.py` uses case-insensitive regex. When adding patterns, test against varied capitalization and phrasing.
7. **Template variables** — `violation_template` and `fix_template` strings use `{key}` placeholders replaced in `rule_matcher.py`. Adding new placeholders requires updating the substitution dict in that file.
8. **ChromaDB collection** — If changing `RAG_COLLECTION_NAME` in `config.py`, the existing collection is orphaned; delete `chroma_db/` and re-index.

#!/usr/bin/env python3
"""
Autonomous HCAI Compliance Engine — CLI entrypoint.

Streamlines California healthcare construction plan reviews by:
  1. Parsing project PDFs/specs to extract conditions
  2. Matching conditions against an HCAI-specific rules dataset
  3. Generating AHJ-style comments with Title 24/PIN/CAN citations (RAG)
  4. Producing prioritized compliance reports (Text / JSON / HTML)

Usage:
  python main.py review --input project.pdf --name "Valley Hospital" --format html
  python main.py validate --input project.pdf --ground-truth data/sample_violations.json
  python main.py demo
  python main.py index-kb
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console() if HAS_RICH else None


def _print(msg: str, style: str = "") -> None:
    if HAS_RICH:
        console.print(msg, style=style)
    else:
        print(msg)


def _banner() -> None:
    banner = (
        "\n[bold blue]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold blue]\n"
        "[bold white]  Autonomous HCAI Compliance Engine[/bold white]\n"
        "[dim]  Streamlining California Healthcare Construction Reviews[/dim]\n"
        "[bold blue]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold blue]\n"
    ) if HAS_RICH else (
        "\n" + "=" * 60 + "\n"
        "  Autonomous HCAI Compliance Engine\n"
        "  Streamlining California Healthcare Construction Reviews\n"
        + "=" * 60 + "\n"
    )
    _print(banner)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Autonomous HCAI Compliance Engine for California healthcare construction."""
    pass


# ---------------------------------------------------------------------------
# review command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--input", "-i", "input_path", required=False, help="Path to PDF or text file to review.")
@click.option("--text", "-t", "raw_text", default=None, help="Inline project description text (alternative to file).")
@click.option("--name", "-n", "project_name", default="Healthcare Project", help="Project name for report.")
@click.option("--format", "-f", "fmt", type=click.Choice(["text", "json", "html", "pdf", "all"]), default="all", help="Output format.")
@click.option("--output-dir", "-o", default=None, help="Directory for output files.")
@click.option("--no-rag", is_flag=True, default=False, help="Skip RAG/Claude enrichment (faster, template-based).")
@click.option("--validate", "run_validation", is_flag=True, default=False, help="Run validation checklist after review.")
@click.option("--ground-truth", default=None, help="Path to ground truth JSON for validation.")
def review(
    input_path: str | None,
    raw_text: str | None,
    project_name: str,
    fmt: str,
    output_dir: str | None,
    no_rag: bool,
    run_validation: bool,
    ground_truth: str | None,
) -> None:
    """Run a full HCAI compliance review on a project document."""
    _banner()

    import config
    from src.parser.pdf_parser import PDFParser
    from src.parser.condition_extractor import ConditionExtractor
    from src.engine.decision_engine import DecisionEngine
    from src.engine.confidence_scorer import ConfidenceScorer
    from src.rag.generator import AHJCommentGenerator
    from src.reports.report_generator import ReportWriter
    from src.reports.pdf_report_generator import render_pdf_report
    from src.monitoring.metrics import SessionMetrics
    from src.notifications.webhook import WebhookNotifier
    from src.monitoring.logger import get_logger

    log = get_logger("main")
    metrics = SessionMetrics()
    scorer = ConfidenceScorer()

    # Validate inputs before any processing output
    if not input_path and not raw_text:
        _print("[red]Error: Provide --input or --text[/red]" if HAS_RICH else "Error: Provide --input or --text")
        sys.exit(1)

    if input_path:
        path = Path(input_path)
        if not path.exists():
            _print(f"[red]Error: File not found: {input_path}[/red]" if HAS_RICH else f"Error: File not found: {input_path}")
            sys.exit(1)

    # Step 1 — Parse
    _print("[bold]Step 1:[/bold] Automated Data Extraction..." if HAS_RICH else "Step 1: Automated Data Extraction...")
    parser = PDFParser()
    extractor = ConditionExtractor()

    if input_path:
        with metrics.timer("pdf_parse"):
            doc = parser.parse(path)
        metrics.pages_processed = doc.total_pages
        _print(f"  Parsed {doc.total_pages} page(s) from [cyan]{path.name}[/cyan]" if HAS_RICH else f"  Parsed {doc.total_pages} pages from {path.name}")
    else:
        with metrics.timer("pdf_parse"):
            doc = parser.parse_text_input(raw_text, source_name=project_name)
        _print("  Using inline text input.")

    with metrics.timer("condition_extraction"):
        conditions = extractor.extract(doc)

    extraction_confidence = scorer.score_extraction(conditions)
    _print(f"  Occupancy : [green]{conditions.occupancy_type or 'Not detected'}[/green]" if HAS_RICH else f"  Occupancy : {conditions.occupancy_type or 'Not detected'}")
    _print(f"  Seismic   : Zone {conditions.seismic.seismic_zone or 'N/A'}, SDS={conditions.seismic.sds}")
    _print(f"  Rooms     : {len(conditions.room_types)} types identified")
    _print(f"  Systems   : HVAC({len(conditions.hvac_systems)}) Elec({len(conditions.electrical_systems)}) Plumb({len(conditions.plumbing_systems)}) MedGas({len(conditions.medical_gas_systems)})")
    _print(f"  Extraction confidence: [bold]{extraction_confidence * 100:.0f}%[/bold]" if HAS_RICH else f"  Extraction confidence: {extraction_confidence * 100:.0f}%")

    # Step 2 — Decision Engine
    _print("\n[bold]Step 2:[/bold] Intelligent Decision Mapping..." if HAS_RICH else "\nStep 2: Intelligent Decision Mapping...")
    engine = DecisionEngine()
    with metrics.timer("decision_engine"):
        violations = engine.evaluate(conditions)
    summary = engine.summary(violations)
    _print(f"  Found [bold]{summary['total']}[/bold] violations: " +
           f"Critical={summary['by_severity']['Critical']} "
           f"High={summary['by_severity']['High']} "
           f"Medium={summary['by_severity']['Medium']} "
           f"Low={summary['by_severity']['Low']}")

    # Step 3 — RAG / AHJ generation
    _print("\n[bold]Step 3:[/bold] RAG-Backed Report Generation..." if HAS_RICH else "\nStep 3: RAG-Backed Report Generation...")

    kb = None
    if not no_rag:
        try:
            from src.rag.knowledge_base import HCAIKnowledgeBase
            kb = HCAIKnowledgeBase()
            if kb.count() == 0:
                added = kb.load_from_files()
                _print(f"  Indexed {added} regulatory documents into knowledge base.")
            else:
                _print(f"  Knowledge base: {kb.count()} documents loaded.")
        except Exception as e:
            _print(f"  [yellow]Warning: RAG KB unavailable ({e}). Using fallback.[/yellow]" if HAS_RICH else f"  Warning: RAG KB unavailable ({e}). Using fallback.")

    generator = AHJCommentGenerator(knowledge_base=kb)
    with metrics.timer("ahj_generation"):
        enriched = generator.enrich(violations)
    metrics.record_violations(enriched)
    _print(f"  Generated AHJ comments for {len(enriched)} violations.")

    # Output
    _print("\n[bold]Output:[/bold] Writing reports..." if HAS_RICH else "\nOutput: Writing reports...")
    writer = ReportWriter(output_dir=output_dir)
    with metrics.timer("report_writing"):
        paths = writer.write_all(enriched, conditions, project_name=project_name, formats=fmt)

    # PDF report — only when fmt is "pdf" or "all"
    if fmt in ("pdf", "all"):
        try:
            out_dir = Path(output_dir) if output_dir else config.OUTPUT_DIR
            pdf_path = render_pdf_report(enriched, conditions, project_name=project_name,
                                         output_path=out_dir / "hcai_report.pdf")
            paths["pdf"] = pdf_path
        except ImportError:
            pass  # reportlab optional

    for ftype, fpath in paths.items():
        _print(f"  [{ftype.upper()}] → {fpath}")

    # Webhook notifications
    notifier = WebhookNotifier()
    notifier.send_review_alert(enriched, project_name, report_paths=paths)

    # Metrics summary
    metrics.log_summary()
    m = metrics.summary()
    _print(f"\n  [dim]Elapsed: {m['total_elapsed_ms']:.0f} ms | "
           f"API calls: {m['api_calls']} | "
           f"Est. cost: ${m['estimated_cost_usd']:.4f}[/dim]" if HAS_RICH
           else f"\n  Elapsed: {m['total_elapsed_ms']:.0f} ms | API calls: {m['api_calls']}")

    # Validation
    if run_validation:
        _run_validation_report(enriched, conditions, ground_truth)

    _print("\n[bold green]✓ Review complete.[/bold green]\n" if HAS_RICH else "\n✓ Review complete.\n")


# ---------------------------------------------------------------------------
# migrate-db command
# ---------------------------------------------------------------------------

@cli.command("migrate-db")
@click.option("--seed/--no-seed", default=True, show_default=True,
              help="Seed rules from JSON after migrating.")
def migrate_db(seed: bool) -> None:
    """Run database migrations and optionally seed rules from JSON."""
    _banner()
    from src.db.rules_store import RulesStore
    _print("Running database migrations...")
    store = RulesStore()
    total = store.count(active_only=False)
    _print(f"  Schema up to date. {total} rules in database.")
    if seed:
        added = store.seed_from_json()
        if added:
            _print(f"  Seeded {added} new rules from hcai_rules.json.")
        else:
            _print("  No new rules to seed (all already present).")
    _print(f"\n  Active rules: {store.count()}")
    _print(f"  Disciplines : {', '.join(store.list_disciplines())}")
    _print("\n[bold green]✓ Database ready.[/bold green]\n" if HAS_RICH else "\n✓ Database ready.\n")


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--input", "-i", "input_path", required=False)
@click.option("--text", "-t", "raw_text", default=None)
@click.option("--ground-truth", "-g", default=None, help="Path to ground truth JSON.")
def validate(input_path: str | None, raw_text: str | None, ground_truth: str | None) -> None:
    """Run validation checklist to measure engine accuracy."""
    _banner()

    from src.parser.pdf_parser import PDFParser
    from src.parser.condition_extractor import ConditionExtractor
    from src.engine.decision_engine import DecisionEngine
    from src.rag.generator import AHJCommentGenerator
    from src.validation.checklist import ComplianceChecklist

    parser = PDFParser()
    extractor = ConditionExtractor()

    if input_path:
        doc = parser.parse(input_path)
    elif raw_text:
        doc = parser.parse_text_input(raw_text, "validation_input")
    else:
        _print("Error: Provide --input or --text")
        sys.exit(1)

    conditions = extractor.extract(doc)
    engine = DecisionEngine()
    violations = engine.evaluate(conditions)
    generator = AHJCommentGenerator()
    enriched = generator.enrich(violations)

    _run_validation_report(enriched, conditions, ground_truth)


# ---------------------------------------------------------------------------
# index-kb command
# ---------------------------------------------------------------------------

@cli.command("index-kb")
def index_kb() -> None:
    """Index Title 24 and PIN/CAN documents into the RAG knowledge base."""
    _banner()
    try:
        from src.rag.knowledge_base import HCAIKnowledgeBase
    except ImportError as e:
        _print(f"Error: {e}")
        sys.exit(1)

    _print("Indexing regulatory documents into ChromaDB...")
    kb = HCAIKnowledgeBase()
    added = kb.load_from_files()
    _print(f"Done. Added {added} documents. Total in KB: {kb.count()}")


# ---------------------------------------------------------------------------
# cleanup command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--jobs-days", default=90, show_default=True,
              help="Remove completed/failed jobs older than this many days.")
@click.option("--audit-days", default=90, show_default=True,
              help="Remove audit log entries older than this many days.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Report what would be deleted without making any changes.")
def cleanup(jobs_days: int, audit_days: int, dry_run: bool) -> None:
    """Remove old jobs and trim the audit log to control disk usage."""
    _banner()
    if dry_run:
        _print("[yellow]Dry-run mode — no data will be deleted.[/yellow]\n" if HAS_RICH
               else "Dry-run mode — no data will be deleted.\n")

    # Jobs cleanup
    try:
        from src.db.job_store import get_sqlite_job_store
        store = get_sqlite_job_store()
        if dry_run:
            from datetime import timedelta, datetime, timezone
            cutoff = (datetime.now(timezone.utc) - timedelta(days=jobs_days)).isoformat()
            import sqlite3
            conn = sqlite3.connect(str(store._db_path))
            count = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('complete','failed') AND created_at < ?",
                (cutoff,),
            ).fetchone()[0]
            conn.close()
            _print(f"Would remove {count} job(s) older than {jobs_days} day(s).")
        else:
            removed = store.cleanup_old_jobs(keep_days=jobs_days)
            _print(f"Removed {removed} job(s) older than {jobs_days} day(s).")
    except Exception as e:
        _print(f"Job cleanup skipped (in-memory store or error): {e}")

    # Audit log trim
    from src.monitoring.audit import trim_audit_log, _AUDIT_PATH
    if not _AUDIT_PATH.exists():
        _print("Audit log does not exist — nothing to trim.")
    elif dry_run:
        from datetime import timedelta, datetime, timezone
        import json as _json
        cutoff_ts = (datetime.now(timezone.utc)).timestamp() - audit_days * 86_400
        old_count = 0
        with open(_AUDIT_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = _json.loads(line.strip())
                    from datetime import datetime as _dt
                    if _dt.fromisoformat(rec["ts"]).timestamp() < cutoff_ts:
                        old_count += 1
                except Exception:
                    pass
        _print(f"Would remove {old_count} audit entry/entries older than {audit_days} day(s).")
    else:
        removed = trim_audit_log(keep_days=audit_days)
        _print(f"Removed {removed} audit log entry/entries older than {audit_days} day(s).")


# ---------------------------------------------------------------------------
# demo command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--format", "-f", "fmt", type=click.Choice(["text", "json", "html", "pdf", "all"]), default="text")
def demo(fmt: str) -> None:
    """Run a demo review on a synthetic occupied hospital project."""
    _banner()
    _print("[dim]Running demo with synthetic Occupied Hospital project data...[/dim]\n" if HAS_RICH else "Running demo with synthetic Occupied Hospital project data...\n")

    demo_text = """
    PROJECT: Valley General Hospital — New Patient Tower
    Location: City of Sacramento, Sacramento County, California

    FACILITY TYPE: Occupied Hospital (Acute Care) — Group I-2 Condition 2
    Licensed Beds: 120
    Construction Type: Type I-A, Fully Sprinklered (NFPA 13)
    Building Height: 75 feet, 5 Stories Above Grade

    SEISMIC DESIGN CATEGORY: D
    SDS: 1.2, SD1: 0.6, Importance Factor Ip: 1.5
    Site Class: D

    MECHANICAL SYSTEMS:
    - AHU air handling unit supply system
    - VAV variable air volume boxes
    - Dedicated outdoor air system (DOAS)
    - Exhaust fans — HEPA filtered return
    - Negative pressure isolation room design required
    - MERV-16 filtration throughout

    ROOMS: operating room, OR, ICU, intensive care, NICU, PACU,
    patient room, isolation room, pharmacy, laboratory, sterile processing,
    soiled utility, clean utility, medication room, nurse station,
    emergency room, radiology, MRI

    ELECTRICAL SYSTEMS:
    - Essential electrical system (EES)
    - Critical branch and life safety branch
    - Emergency power generator
    - Transfer switch (ATS)
    - Panelboard distribution

    MEDICAL GAS SYSTEMS:
    - Oxygen manifold and liquid oxygen system
    - Medical vacuum pump
    - Medical air compressor
    - WAGD waste anesthesia gas disposal
    - Zone valve boxes throughout
    - Medical gas outlets at all patient care areas

    PLUMBING:
    - Domestic hot water system
    - ASSE 1070 thermostatic mixing valves
    - Backflow preventer on domestic water
    - Emergency eye wash stations
    - Scrub sinks adjacent to ORs (sensor-actuated)
    """

    ctx = click.get_current_context()
    ctx.invoke(
        review,
        input_path=None,
        raw_text=demo_text,
        project_name="Valley General Hospital — New Patient Tower",
        fmt=fmt,
        output_dir=None,
        no_rag=False,
        run_validation=True,
        ground_truth="data/sample_violations.json",
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_validation_report(enriched, conditions, ground_truth_path: str | None) -> None:
    from src.validation.checklist import ComplianceChecklist

    conditions_summary = {
        "occupancy_type": conditions.occupancy_type,
        "seismic_zone": conditions.seismic.seismic_zone,
        "sds": conditions.seismic.sds,
        "hvac_count": len(conditions.hvac_systems),
        "electrical_count": len(conditions.electrical_systems),
        "plumbing_count": len(conditions.plumbing_systems),
        "room_count": len(conditions.room_types),
    }

    checker = ComplianceChecklist(ground_truth_file=ground_truth_path)
    result = checker.run(enriched, conditions_summary)

    _print("\n" + ("━" * 60 if HAS_RICH else "=" * 60))
    _print("VALIDATION CHECKLIST")
    _print("━" * 60 if HAS_RICH else "-" * 60)

    if HAS_RICH:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Category", style="dim", width=16)
        table.add_column("Check", width=44)
        table.add_column("Score", justify="right", width=8)
        table.add_column("Pass", justify="center", width=6)

        for item in result.items:
            status = "[green]✓[/green]" if item.passed else "[red]✗[/red]"
            score_str = f"{item.score * 100:.0f}%"
            table.add_row(item.category, item.description, score_str, status)

        console.print(table)
    else:
        for item in result.items:
            status = "PASS" if item.passed else "FAIL"
            print(f"  [{status}] [{item.category}] {item.description} ({item.score*100:.0f}%)")
            if item.detail:
                print(f"         {item.detail}")

    _print(f"\n[bold]{result.summary()}[/bold]" if HAS_RICH else f"\n{result.summary()}")
    by_cat = result.by_category()
    for cat, score in by_cat.items():
        _print(f"  {cat:<20} {score*100:5.1f}%")
    _print("")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()

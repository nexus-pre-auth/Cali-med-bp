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
@click.option("--format", "-f", "fmt", type=click.Choice(["text", "json", "html", "all"]), default="all", help="Output format.")
@click.option("--output-dir", "-o", default=None, help="Directory for output files.")
@click.option("--no-rag", is_flag=True, default=False, help="Disable RAG retrieval context. Claude API is still called when ANTHROPIC_API_KEY is set; omit the key too for fully template-based output.")
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
    from src.rag.generator import AHJCommentGenerator
    from src.reports.report_generator import ReportWriter

    # Step 1 — Parse
    _print("[bold]Step 1:[/bold] Automated Data Extraction..." if HAS_RICH else "Step 1: Automated Data Extraction...")
    parser = PDFParser()
    extractor = ConditionExtractor()

    if input_path:
        path = Path(input_path)
        if not path.exists():
            _print(f"[red]Error: File not found: {input_path}[/red]" if HAS_RICH else f"Error: File not found: {input_path}")
            sys.exit(1)
        doc = parser.parse(path)
        _print(f"  Parsed {doc.total_pages} page(s) from [cyan]{path.name}[/cyan]" if HAS_RICH else f"  Parsed {doc.total_pages} pages from {path.name}")
    elif raw_text:
        doc = parser.parse_text_input(raw_text, source_name=project_name)
        _print("  Using inline text input.")
    else:
        _print("[red]Error: Provide --input or --text[/red]" if HAS_RICH else "Error: Provide --input or --text")
        sys.exit(1)

    conditions = extractor.extract(doc)
    _print(f"  Occupancy : [green]{conditions.occupancy_type or 'Not detected'}[/green]" if HAS_RICH else f"  Occupancy : {conditions.occupancy_type or 'Not detected'}")
    _print(f"  Seismic   : Zone {conditions.seismic.seismic_zone or 'N/A'}, SDS={conditions.seismic.sds}")
    _print(f"  Rooms     : {len(conditions.room_types)} types identified")
    _print(f"  Systems   : HVAC({len(conditions.hvac_systems)}) Elec({len(conditions.electrical_systems)}) Plumb({len(conditions.plumbing_systems)}) MedGas({len(conditions.medical_gas_systems)})")

    # Step 2 — Decision Engine
    _print("\n[bold]Step 2:[/bold] Intelligent Decision Mapping..." if HAS_RICH else "\nStep 2: Intelligent Decision Mapping...")
    engine = DecisionEngine()
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
    enriched = generator.enrich(violations)
    _print(f"  Generated AHJ comments for {len(enriched)} violations.")

    # Output
    _print("\n[bold]Output:[/bold] Writing reports..." if HAS_RICH else "\nOutput: Writing reports...")
    writer = ReportWriter(output_dir=output_dir)
    paths = writer.write_all(enriched, conditions, project_name=project_name, fmt=fmt)

    for ftype, fpath in paths.items():
        _print(f"  [{ftype.upper()}] → {fpath}")

    # Validation
    if run_validation:
        _run_validation_report(enriched, conditions, ground_truth)

    _print("\n[bold green]✓ Review complete.[/bold green]\n" if HAS_RICH else "\n✓ Review complete.\n")


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
# demo command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--format", "-f", "fmt", type=click.Choice(["text", "json", "html", "all"]), default="text")
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
# batch command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--input-dir", "-d", required=True, help="Directory containing PDF files to review.")
@click.option("--output-dir", "-o", default=None, help="Root directory for per-file report output.")
@click.option("--format", "-f", "fmt", type=click.Choice(["text", "json", "html", "all"]), default="all")
@click.option("--workers", "-w", default=4, show_default=True, help="Parallel worker threads.")
@click.option("--no-rag", is_flag=True, default=False, help="Skip RAG/Claude enrichment.")
def batch(input_dir: str, output_dir: str | None, fmt: str, workers: int, no_rag: bool) -> None:
    """
    Run compliance reviews on every PDF in a directory concurrently.

    Reports are written to --output-dir/<filename>/ for each input file.
    A batch_summary.json is written to --output-dir/ when complete.
    """
    import asyncio
    import json as _json
    _banner()

    from src.engine.batch_processor import BatchProcessor

    in_path  = Path(input_dir)
    out_path = Path(output_dir) if output_dir else in_path / "hcai_output"
    out_path.mkdir(parents=True, exist_ok=True)

    if not in_path.exists():
        _print(f"[red]Error: Directory not found: {input_dir}[/red]" if HAS_RICH
               else f"Error: Directory not found: {input_dir}")
        sys.exit(1)

    processor = BatchProcessor(max_workers=workers)

    async def _run():
        return await processor.run(in_path, fmt=fmt, output_dir=out_path, use_rag=not no_rag)

    summary = asyncio.run(_run())
    summary.print_summary()

    # Write aggregate summary JSON
    summary_path = out_path / "batch_summary.json"
    with open(summary_path, "w") as f:
        _json.dump(summary.to_dict(), f, indent=2)
    _print(f"Batch summary written to {summary_path}")


# ---------------------------------------------------------------------------
# serve command  (FastAPI + feedback loop)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind address.")
@click.option("--port", default=8000, show_default=True, help="TCP port.")
@click.option("--no-learning", is_flag=True, default=False,
              help="Disable the continuous learning scheduler.")
def serve(host: str, port: int, no_learning: bool) -> None:
    """
    Start the FastAPI server with the real-time AHJ feedback loop.

    Exposes:
      POST /feedback/submit        — receive AHJ plan check feedback
      POST /feedback/batch         — bulk feedback submission
      GET  /feedback/metrics       — aggregated accuracy metrics
      GET  /feedback/dashboard     — real-time dashboard data (JSON)
      POST /feedback/retrain       — manually trigger model retraining
      GET  /feedback/model/version — active model version

    Open http://<host>:<port>/feedback/dashboard in a browser after starting.
    """
    try:
        import uvicorn
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError:
        _print(
            "[red]Error: fastapi and uvicorn are required for `serve`. "
            "Run: pip install fastapi uvicorn[standard][/red]"
            if HAS_RICH else
            "Error: fastapi and uvicorn are required. Run: pip install fastapi 'uvicorn[standard]'"
        )
        sys.exit(1)

    from src.api.feedback_endpoints import feedback_router
    from src.api.query_endpoints    import query_router

    app = FastAPI(
        title="HCAI Compliance Engine",
        description="Real-time AHJ feedback collection, continuous learning, and NL query.",
        version="2.0.0",
    )
    app.include_router(feedback_router)
    app.include_router(query_router)

    # Serve the dashboard HTML at /feedback/dashboard/ui
    templates_dir = Path(__file__).parent / "templates"

    @app.get("/feedback/dashboard/ui", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_ui():
        html_path = templates_dir / "feedback_dashboard.html"
        if not html_path.exists():
            return HTMLResponse("<h1>Dashboard template not found</h1>", status_code=404)
        return HTMLResponse(html_path.read_text())

    # Start continuous learning scheduler
    if not no_learning:
        try:
            from src.ml.continuous_learning import ContinuousLearningPipeline
            pipeline = ContinuousLearningPipeline()

            @app.on_event("startup")
            async def start_pipeline():
                pipeline.start()

            @app.on_event("shutdown")
            async def stop_pipeline():
                pipeline.stop()

        except ImportError:
            _print("Warning: APScheduler not installed; continuous learning disabled.")

    _print(f"\n[bold green]HCAI Feedback API[/bold green] listening on http://{host}:{port}" if HAS_RICH
           else f"\nHCAI Feedback API listening on http://{host}:{port}")
    _print(f"  Dashboard UI : http://{host}:{port}/feedback/dashboard/ui")
    _print(f"  API docs     : http://{host}:{port}/docs\n")

    uvicorn.run(app, host=host, port=port)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()

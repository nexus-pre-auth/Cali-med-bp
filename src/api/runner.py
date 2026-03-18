"""
Review runner — executes the full compliance pipeline for a background job.

Called from FastAPI's BackgroundTasks so it runs off the request thread.
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

import config
from src.api.jobs import JobStore
from src.api.models import (
    ExtractedConditions,
    JobStatus,
    ReviewResponse,
    ReviewSummary,
    SeismicInfo,
    SeveritySummary,
    ViolationResponse,
    SeverityEnum,
    OutputFormat,
)
from src.engine.confidence_scorer import ConfidenceScorer
from src.engine.decision_engine import DecisionEngine
from src.monitoring.logger import get_logger
from src.monitoring.metrics import SessionMetrics
from src.notifications.webhook import WebhookNotifier
from src.parser.condition_extractor import ConditionExtractor
from src.parser.pdf_parser import PDFParser
from src.rag.generator import AHJCommentGenerator
from src.reports.report_generator import ReportWriter

log = get_logger(__name__)


def _build_report_urls(paths: dict, job_id: UUID, base_url: str) -> dict[str, str]:
    """Convert local file paths to API download URLs."""
    fmt_map = {
        "text": "txt",
        "json": "json",
        "html": "html",
        "pdf":  "pdf",
    }
    urls = {}
    for fmt, path in paths.items():
        ext = fmt_map.get(fmt, fmt)
        urls[fmt] = f"{base_url}/review/{job_id}/report/{ext}"
    return urls


def run_review(
    job_id: UUID,
    store: JobStore,
    project_name: str,
    text: Optional[str],
    pdf_bytes: Optional[bytes],
    pdf_filename: Optional[str],
    no_rag: bool,
    fmt: OutputFormat,
    base_url: str,
) -> None:
    """
    Full pipeline execution. Mutates the job record in `store`.
    Designed to be run in a background thread.
    """
    job = store.get(job_id)
    if not job:
        return

    # Mark in-progress
    job.status = JobStatus.processing
    store.update(job)

    metrics = SessionMetrics(session_id=str(job_id))
    scorer = ConfidenceScorer()

    try:
        # --- Step 1: Parse ---
        parser = PDFParser()
        extractor = ConditionExtractor()

        with metrics.timer("pdf_parse"):
            if pdf_bytes:
                import tempfile, os
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(pdf_bytes)
                    tmp_path = tmp.name
                try:
                    doc = parser.parse(tmp_path)
                finally:
                    os.unlink(tmp_path)
                metrics.pages_processed = doc.total_pages
            elif text:
                doc = parser.parse_text_input(text, source_name=project_name)
            else:
                raise ValueError("No input provided — supply text or a PDF file.")

        with metrics.timer("condition_extraction"):
            conditions = extractor.extract(doc)

        extraction_conf = scorer.score_extraction(conditions)

        # --- Step 2: Decision Engine ---
        engine = DecisionEngine()
        with metrics.timer("decision_engine"):
            violations = engine.evaluate(conditions)

        # --- Step 3: RAG ---
        kb = None
        if not no_rag:
            try:
                from src.rag.knowledge_base import HCAIKnowledgeBase
                kb = HCAIKnowledgeBase()
                if kb.count() == 0:
                    kb.load_from_files()
            except Exception as e:
                log.warning("RAG KB unavailable: %s — using fallback", e)

        gen = AHJCommentGenerator(knowledge_base=kb)
        with metrics.timer("ahj_generation"):
            enriched = gen.enrich(violations)
        metrics.record_violations(enriched)

        # --- Confidence per violation ---
        conf_pairs = scorer.score_violations(violations, doc.full_text, conditions)
        conf_map = {v.rule_id: cr.overall for v, cr in conf_pairs}

        # --- Reports ---
        out_dir = config.OUTPUT_DIR / str(job_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        writer = ReportWriter(output_dir=out_dir)

        with metrics.timer("report_writing"):
            paths = writer.write_all(enriched, conditions, project_name=project_name, stem="report")

        # PDF report
        try:
            from src.reports.pdf_report_generator import render_pdf_report
            pdf_path = render_pdf_report(
                enriched, conditions,
                project_name=project_name,
                output_path=out_dir / "report.pdf",
            )
            paths["pdf"] = pdf_path
        except ImportError:
            pass

        # --- Build response ---
        sev_counts = SeveritySummary(
            **{k: v for k, v in metrics.violations_by_severity.items()}
        )

        violation_responses = [
            ViolationResponse(
                rule_id=ev.violation.rule_id,
                discipline=ev.violation.discipline,
                severity=SeverityEnum(ev.violation.severity.value),
                trigger_condition=ev.violation.trigger_condition,
                ahj_comment=ev.ahj_comment,
                fix_instructions=ev.fix_instructions,
                citations=ev.citations,
                confidence=round(conf_map.get(ev.violation.rule_id, 0.0), 3),
            )
            for ev in enriched
        ]

        job.conditions = ExtractedConditions(
            occupancy_type=conditions.occupancy_type,
            construction_type=conditions.construction_type,
            sprinklered=conditions.sprinklered,
            licensed_beds=conditions.licensed_beds,
            county=conditions.county,
            city=conditions.city,
            seismic=SeismicInfo(
                seismic_zone=conditions.seismic.seismic_zone,
                sds=conditions.seismic.sds,
                sd1=conditions.seismic.sd1,
                importance_factor=conditions.seismic.importance_factor,
                site_class=conditions.seismic.site_class,
            ),
            hvac_systems=conditions.hvac_systems,
            electrical_systems=conditions.electrical_systems,
            plumbing_systems=conditions.plumbing_systems,
            medical_gas_systems=conditions.medical_gas_systems,
            room_types=conditions.room_types,
            extraction_confidence=round(extraction_conf, 3),
        )
        job.summary    = ReviewSummary(total=len(enriched), by_severity=sev_counts)
        job.violations = violation_responses
        job.report_urls = _build_report_urls(paths, job_id, base_url)
        job.metrics     = metrics.summary()
        job.status      = JobStatus.complete
        job.completed_at = datetime.now(timezone.utc)

        # Webhooks
        WebhookNotifier().send_review_alert(enriched, project_name, report_paths=paths)
        metrics.log_summary()

    except Exception as exc:
        log.error("Job %s failed: %s\n%s", job_id, exc, traceback.format_exc())
        job.status    = JobStatus.failed
        job.error     = str(exc)
        job.completed_at = datetime.now(timezone.utc)

    store.update(job)

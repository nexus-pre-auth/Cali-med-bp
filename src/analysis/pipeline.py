"""
Analysis pipeline orchestration — wires the existing deterministic engine
(parser -> condition extractor -> decision engine -> RAG enrichment ->
report generator) into the `/api/v1` analysis job lifecycle.

The deterministic `DecisionEngine`/`RuleMatcher` remain the sole authority
for compliance findings. RAG/Claude only enrich findings with explanatory
text and regulatory citations retrieved from the knowledge base — they
never add, remove, or change a finding's severity or trigger condition.

Lifecycle: QUEUED -> PROCESSING -> COMPLETED | FAILED. This MVP runs
synchronously inside a FastAPI `BackgroundTasks` callback (single process).
For multi-worker/horizontally-scaled deployments, replace the `run_analysis`
call site in `src/api/v1/analyses.py` with a durable queue (Celery/RQ +
Redis) invoking the same `run_analysis` function from a worker process —
the function signature intentionally takes only an `analysis_id` so it can
be handed to any task queue without change.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

import config as app_config
from src.database.repositories_v1 import (
    AnalysisRepository,
    DocumentRepository,
    FindingRepository,
    ProjectRepositoryV1,
    ReportRepository,
)

logger = logging.getLogger("hcai.analysis_pipeline")

ENGINE_VERSION = "hcai-decision-engine-2.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_analysis(analysis_id: str) -> None:
    """Execute the full deterministic compliance pipeline for one analysis.

    Safe to call from a FastAPI BackgroundTask or an external worker process.
    Never raises — all failures are captured and recorded on the analysis
    record itself so the API can report them to the caller.
    """
    analyses = AnalysisRepository()
    documents = DocumentRepository()
    findings_repo = FindingRepository()
    reports_repo = ReportRepository()
    projects = ProjectRepositoryV1()

    analysis = analyses.get(analysis_id)
    if analysis is None:
        logger.error("run_analysis: analysis %s not found", analysis_id)
        return

    analyses.update(analysis_id, {"status": "PROCESSING", "started_at": _now()})

    try:
        document = documents.get(analysis.get("document_id")) if analysis.get("document_id") else None
        if document is None:
            raise RuntimeError("Analysis has no associated document.")

        project = projects.get(analysis["project_id"]) or {}
        project_name = project.get("name", "Unnamed Project")

        # Step 1 — Parse
        from src.parser.pdf_parser import PDFParser
        from src.parser.condition_extractor import ConditionExtractor

        storage_path = document.get("storage_path")
        parser = PDFParser()
        if storage_path and str(storage_path).lower().endswith(".pdf"):
            parsed_doc = parser.parse(storage_path)
        else:
            # Non-PDF or text-only upload: read raw text safely from the
            # validated, server-generated storage path (never user input).
            try:
                text = open(storage_path, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                text = ""
            parsed_doc = parser.parse_text_input(text, source_name=document.get("original_filename", "document"))

        extractor = ConditionExtractor()
        conditions = extractor.extract(parsed_doc)

        # Step 2 — Deterministic decision engine (authoritative)
        from src.engine.decision_engine import DecisionEngine

        engine = DecisionEngine()
        violations = engine.evaluate(conditions)

        # Step 3 — RAG enrichment (explanatory only; never changes findings)
        from src.rag.generator import AHJCommentGenerator

        kb = None
        try:
            from src.rag.knowledge_base import HCAIKnowledgeBase
            kb = HCAIKnowledgeBase()
        except Exception as exc:
            logger.warning("RAG knowledge base unavailable, using template fallback: %s", exc)

        generator = AHJCommentGenerator(knowledge_base=kb)
        enriched = generator.enrich(violations)

        # Persist findings with full provenance
        finding_rows = []
        for item in enriched:
            v = item.violation
            prov = v.provenance()
            finding_rows.append(
                {
                    "analysis_id": analysis_id,
                    "rule_id": prov["rule_id"],
                    "discipline": prov["discipline"],
                    "severity": prov["severity"],
                    "title": prov["requirement"][:200] if prov.get("requirement") else None,
                    "requirement": prov["requirement"],
                    "project_evidence": prov["project_evidence"],
                    "required_condition": v.fix_text,
                    "jurisdiction": prov["jurisdiction"],
                    "code_family": prov["code_family"],
                    "source_reference": prov["source_reference"],
                    "citation_verified": prov["citation_verified"],
                    "confidence": prov["confidence"],
                    "recommended_action": prov["recommended_action"],
                    "status": "open",
                }
            )
        findings_repo.bulk_insert(finding_rows)

        # Step 4 — Reports (JSON + HTML always; PDF best-effort)
        from src.reports.report_generator import ReportWriter

        writer = ReportWriter(output_dir=str(app_config.OUTPUT_DIR / "analyses" / analysis_id))
        written = writer.write_all(enriched, conditions, project_name=project_name, fmt="all")

        for fmt, path in written.items():
            reports_repo.insert(
                {
                    "project_id": analysis["project_id"],
                    "analysis_id": analysis_id,
                    "format": fmt,
                    "storage_path": str(path),
                    "version": 1,
                }
            )

        analyses.update(
            analysis_id,
            {
                "status": "COMPLETED",
                "completed_at": _now(),
                "engine_version": ENGINE_VERSION,
                "error_message": None,
            },
        )
        documents.update(document["id"], {"status": "processed"})

    except Exception as exc:  # noqa: BLE001 - top-level job boundary, must not raise
        logger.exception("Analysis %s failed", analysis_id)
        analyses.update(
            analysis_id,
            {
                "status": "FAILED",
                "completed_at": _now(),
                "engine_version": ENGINE_VERSION,
                "error_message": f"{type(exc).__name__}: {exc}",
            },
        )
        logger.debug("Traceback: %s", traceback.format_exc())

"""
FastAPI application — Autonomous HCAI Compliance Engine REST API.

Endpoints
---------
POST   /review                 Submit text for compliance review (async)
POST   /review/upload          Submit PDF file for compliance review (async)
GET    /review/{job_id}        Poll job status / retrieve results
GET    /review/{job_id}/report/{fmt}  Download report file
GET    /reviews                List recent review jobs
POST   /validate               Run validation checklist on inline text
GET    /health                 Liveness + engine status check
"""

from __future__ import annotations

import mimetypes
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import config
from src.api.auth import require_api_key
from src.api.jobs import get_job_store, JobStore
from src.api.models import (
    HealthResponse,
    JobStatus,
    JobStatusResponse,
    OutputFormat,
    ReviewRequest,
    ReviewResponse,
    ValidationRequest,
    ValidationResponse,
    ChecklistItemResponse,
)
from src.api.runner import run_review
from src.monitoring.audit import log_review_submitted, read_audit_log
from src.monitoring.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Per-IP rate-limit middleware
# ---------------------------------------------------------------------------

_DEFAULT_RATE_LIMIT_RPM = 60
_DEFAULT_RATE_LIMIT_BURST = 10

# Paths exempt from rate limiting (health, docs)
_EXEMPT_PREFIXES = ("/health", "/docs", "/redoc", "/openapi")


class _RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Token-bucket rate limiter applied per client IP.

    Each IP gets RATE_LIMIT_RPM tokens/minute refilled continuously.
    RATE_LIMIT_BURST controls the maximum number of queued tokens so a
    single IP cannot bank up unlimited requests.
    """

    def __init__(self, app, calls_per_minute: int, burst: int) -> None:
        super().__init__(app)
        self._rpm = calls_per_minute
        self._burst = burst
        self._refill_rate = calls_per_minute / 60.0  # tokens/second
        # {ip: [tokens, last_refill_ts]}
        self._buckets: dict[str, list] = defaultdict(
            lambda: [float(burst), time.monotonic()]
        )
        import threading
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"

        with self._lock:
            bucket = self._buckets[ip]
            now = time.monotonic()
            elapsed = now - bucket[1]
            bucket[0] = min(self._burst, bucket[0] + elapsed * self._refill_rate)
            bucket[1] = now

            if bucket[0] < 1.0:
                retry_after = int((1.0 - bucket[0]) / self._refill_rate) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Try again shortly."},
                    headers={"Retry-After": str(retry_after)},
                )
            bucket[0] -= 1.0

        return await call_next(request)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="HCAI Compliance Engine API",
        description=(
            "Autonomous California healthcare construction plan review system. "
            "Submit project drawings or specifications and receive HCAI-style "
            "compliance violations with Title 24 / PIN / CAN citations and "
            "step-by-step remediation guidance."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Rate limiting — applied before auth so abusive clients are dropped early
    # Read at create_app() time so tests can override via env vars
    rate_limit_rpm = int(os.getenv("RATE_LIMIT_RPM", str(_DEFAULT_RATE_LIMIT_RPM)))
    rate_limit_burst = int(os.getenv("RATE_LIMIT_BURST", str(_DEFAULT_RATE_LIMIT_BURST)))
    if rate_limit_rpm > 0:
        app.add_middleware(
            _RateLimitMiddleware,
            calls_per_minute=rate_limit_rpm,
            burst=rate_limit_burst,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_routes(app)
    return app


def _base_url(request) -> str:
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _register_routes(app: FastAPI) -> None:

    # ------------------------------------------------------------------ health
    @app.get("/health", response_model=HealthResponse, tags=["System"])
    async def health() -> HealthResponse:
        """Liveness check — verifies the rules dataset and engine load correctly."""
        try:
            from src.engine.decision_engine import DecisionEngine
            engine = DecisionEngine()
            rules_loaded = len(engine._matcher._rules)
        except Exception:
            rules_loaded = 0

        kb_docs = 0
        try:
            from src.rag.knowledge_base import HCAIKnowledgeBase
            kb_docs = HCAIKnowledgeBase().count()
        except Exception:
            pass

        return HealthResponse(
            status="ok",
            rules_loaded=rules_loaded,
            kb_documents=kb_docs,
        )

    # -------------------------------------------------------- POST /review (text)
    @app.post(
        "/review",
        response_model=ReviewResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["Review"],
    )
    async def submit_review(
        request: Request,
        request_body: ReviewRequest,
        background_tasks: BackgroundTasks,
        store: JobStore = Depends(get_job_store),
        _api_key: str = Depends(require_api_key),
    ) -> ReviewResponse:
        """
        Submit a project description text for async compliance review.

        Returns immediately with a job_id. Poll `GET /review/{job_id}` for results.
        """
        if not request_body.text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'text' is required for this endpoint. Use /review/upload for PDF files.",
            )

        job = store.create(request_body.project_name)
        base_url = str(request.base_url).rstrip("/")

        background_tasks.add_task(
            run_review,
            job_id=job.job_id,
            store=store,
            project_name=request_body.project_name,
            text=request_body.text,
            pdf_bytes=None,
            pdf_filename=None,
            no_rag=request_body.no_rag,
            fmt=request_body.format,
            base_url=base_url,
        )

        log.info("Review job %s created for project '%s'", job.job_id, request_body.project_name)
        log_review_submitted(
            job_id=job.job_id,
            project_name=request_body.project_name,
            source="api_text",
            api_key_hint=(_api_key[:8] if _api_key and _api_key != "dev-mode" else "dev-mode"),
        )
        return job

    # -------------------------------------------------- POST /review/upload (PDF)
    @app.post(
        "/review/upload",
        response_model=ReviewResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["Review"],
    )
    async def submit_review_pdf(
        request: Request,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(..., description="PDF project drawing or specification"),
        project_name: str = Form(default="Healthcare Project"),
        no_rag: bool = Form(default=False),
        fmt: OutputFormat = Form(default=OutputFormat.all),
        store: JobStore = Depends(get_job_store),
        _api_key: str = Depends(require_api_key),
    ) -> ReviewResponse:
        """
        Submit a PDF project file for async compliance review.

        Returns immediately with a job_id. Poll `GET /review/{job_id}` for results.
        """
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only PDF files are supported.",
            )

        pdf_bytes = await file.read()
        if len(pdf_bytes) > 50 * 1024 * 1024:  # 50 MB cap
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="PDF file exceeds 50 MB limit.",
            )

        job = store.create(project_name)
        base_url = str(request.base_url).rstrip("/")

        background_tasks.add_task(
            run_review,
            job_id=job.job_id,
            store=store,
            project_name=project_name,
            text=None,
            pdf_bytes=pdf_bytes,
            pdf_filename=file.filename,
            no_rag=no_rag,
            fmt=fmt,
            base_url=base_url,
        )

        log.info("PDF review job %s created — file: %s", job.job_id, file.filename)
        log_review_submitted(
            job_id=job.job_id,
            project_name=project_name,
            source="api_pdf",
            api_key_hint=(_api_key[:8] if _api_key and _api_key != "dev-mode" else "dev-mode"),
            filename=file.filename,
        )
        return job

    # ----------------------------------------------- GET /review/{job_id}
    @app.get(
        "/review/{job_id}",
        response_model=ReviewResponse,
        tags=["Review"],
    )
    async def get_review(
        job_id: UUID,
        store: JobStore = Depends(get_job_store),
        _api_key: str = Depends(require_api_key),
    ) -> ReviewResponse:
        """
        Retrieve compliance review results by job ID.

        Poll this endpoint until `status` is `complete` or `failed`.
        """
        job = store.get(job_id)
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job {job_id} not found.",
            )
        return job

    # --------------------------------- GET /review/{job_id}/report/{fmt}
    @app.get(
        "/review/{job_id}/report/{fmt}",
        tags=["Review"],
        responses={
            200: {"description": "Report file download"},
            404: {"description": "Job or report not found"},
            425: {"description": "Job not yet complete"},
        },
    )
    async def download_report(
        job_id: UUID,
        fmt: str,
        store: JobStore = Depends(get_job_store),
        _api_key: str = Depends(require_api_key),
    ):
        """Download a generated report file (txt / json / html / pdf)."""
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

        if job.status != JobStatus.complete:
            raise HTTPException(
                status_code=425,
                detail=f"Job is not complete yet (status: {job.status}).",
            )

        ext_map = {"txt": "text", "json": "json", "html": "html", "pdf": "pdf"}
        fmt_key = ext_map.get(fmt, fmt)

        report_path = config.OUTPUT_DIR / str(job_id) / f"report.{fmt}"
        if not report_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Report format '{fmt}' not available for this job.",
            )

        media_type = {
            "txt":  "text/plain",
            "json": "application/json",
            "html": "text/html",
            "pdf":  "application/pdf",
        }.get(fmt, "application/octet-stream")

        return FileResponse(
            path=str(report_path),
            media_type=media_type,
            filename=f"hcai_report_{job_id}.{fmt}",
        )

    # ------------------------------------------------------- GET /reviews
    @app.get(
        "/reviews",
        response_model=list[JobStatusResponse],
        tags=["Review"],
    )
    async def list_reviews(
        limit: int = 20,
        store: JobStore = Depends(get_job_store),
        _api_key: str = Depends(require_api_key),
    ) -> list[JobStatusResponse]:
        """List recent compliance review jobs (newest first)."""
        jobs = store.list_recent(limit=min(limit, 100))
        return [
            JobStatusResponse(
                job_id=j.job_id,
                status=j.status,
                created_at=j.created_at,
                completed_at=j.completed_at,
                error=j.error,
            )
            for j in jobs
        ]

    # ------------------------------------------------------- POST /validate
    @app.post(
        "/validate",
        response_model=ValidationResponse,
        tags=["Validation"],
    )
    async def validate_text(
        body: ValidationRequest,
        _api_key: str = Depends(require_api_key),
    ) -> ValidationResponse:
        """
        Synchronous validation checklist against inline text.

        Optionally provide a `ground_truth` list of known violations
        to benchmark engine accuracy.
        """
        import tempfile, json as _json, os

        from src.parser.pdf_parser import PDFParser
        from src.parser.condition_extractor import ConditionExtractor
        from src.engine.decision_engine import DecisionEngine
        from src.rag.generator import AHJCommentGenerator
        from src.validation.checklist import ComplianceChecklist

        parser = PDFParser()
        doc = parser.parse_text_input(body.text, "api_validation")
        extractor = ConditionExtractor()
        conditions = extractor.extract(doc)

        engine = DecisionEngine()
        violations = engine.evaluate(conditions)
        enriched = AHJCommentGenerator().enrich(violations)

        gt_file = None
        if body.ground_truth:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tf:
                _json.dump(body.ground_truth, tf)
                gt_file = tf.name

        try:
            checker = ComplianceChecklist(ground_truth_file=gt_file)
            result = checker.run(
                enriched,
                {
                    "occupancy_type": conditions.occupancy_type,
                    "seismic_zone": conditions.seismic.seismic_zone,
                    "sds": conditions.seismic.sds,
                    "hvac_count": len(conditions.hvac_systems),
                    "electrical_count": len(conditions.electrical_systems),
                    "plumbing_count": len(conditions.plumbing_systems),
                    "room_count": len(conditions.room_types),
                },
            )
        finally:
            if gt_file:
                os.unlink(gt_file)

        return ValidationResponse(
            overall_score=round(result.overall_score, 3),
            passed_count=result.passed_count,
            total_count=result.total_count,
            summary=result.summary(),
            by_category=result.by_category(),
            items=[
                ChecklistItemResponse(
                    category=i.category,
                    description=i.description,
                    passed=i.passed,
                    score=round(i.score, 3),
                    detail=i.detail,
                )
                for i in result.items
            ],
        )

    # ------------------------------------------------------- GET /rules
    @app.get(
        "/rules",
        tags=["Rules"],
        response_model=list[dict],
    )
    async def list_rules(
        discipline: Optional[str] = None,
        active_only: bool = True,
        _api_key: str = Depends(require_api_key),
    ) -> list[dict]:
        """List compliance rules from the persistent store."""
        from src.db.rules_store import get_rules_store
        store = get_rules_store()
        if discipline:
            return store.get_by_discipline(discipline, active_only=active_only)
        rules = store.get_all_active() if active_only else store.get_all_active()
        return rules

    @app.get("/rules/{rule_id}", tags=["Rules"])
    async def get_rule(
        rule_id: str,
        _api_key: str = Depends(require_api_key),
    ) -> dict:
        """Get a single rule by ID."""
        from src.db.rules_store import get_rules_store
        rule = get_rules_store().get_by_id(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found.")
        return rule

    @app.patch("/rules/{rule_id}/active", tags=["Rules"])
    async def set_rule_active(
        rule_id: str,
        active: bool,
        _api_key: str = Depends(require_api_key),
    ) -> dict:
        """Enable or disable a rule without deleting it."""
        from src.db.rules_store import get_rules_store
        found = get_rules_store().set_active(rule_id, active)
        if not found:
            raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found.")
        return {"rule_id": rule_id, "active": active}

    @app.post("/rules", status_code=status.HTTP_201_CREATED, tags=["Rules"])
    async def upsert_rule(
        rule: dict,
        _api_key: str = Depends(require_api_key),
    ) -> dict:
        """Insert or update a rule. Must include 'id', 'discipline', 'description'."""
        if not rule.get("id") or not rule.get("discipline") or not rule.get("description"):
            raise HTTPException(status_code=422, detail="Fields 'id', 'discipline', 'description' are required.")
        from src.db.rules_store import get_rules_store
        get_rules_store().upsert_rule(rule)
        return {"status": "ok", "rule_id": rule["id"]}

    # ------------------------------------------------------- GET /audit
    @app.get(
        "/audit",
        tags=["Audit"],
        response_model=list[dict],
    )
    async def get_audit_log(
        event: Optional[str] = None,
        job_id: Optional[str] = None,
        limit: int = 100,
        _api_key: str = Depends(require_api_key),
    ) -> list[dict]:
        """
        Read the compliance audit trail.

        Optionally filter by `event` type (e.g. REVIEW_SUBMITTED, VIOLATION_DETECTED)
        or by `job_id`. Returns most recent entries first.
        """
        return read_audit_log(
            event_filter=event,
            job_id_filter=job_id,
            limit=min(limit, 500),
        )


# ---------------------------------------------------------------------------
# Entry point (uvicorn)
# ---------------------------------------------------------------------------

app = create_app()

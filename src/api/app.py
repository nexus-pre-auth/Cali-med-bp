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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
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
    RuleResponse,
    RuleCreateRequest,
    ValidationRequest,
    ValidationResponse,
    ChecklistItemResponse,
)
from src.api.runner import run_review
from src.monitoring.audit import log_review_submitted, read_audit_log
from src.monitoring.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan — startup / shutdown
# ---------------------------------------------------------------------------

async def _on_startup() -> None:
    """Run once when the server starts: migrate DB, warm KB, init Postgres."""

    # 1. SQLite migrations + rule seeding (idempotent, ~100 ms)
    try:
        from src.db.rules_store import get_rules_store
        store = get_rules_store()
        log.info("Rules store ready: %d active rules.", store.count())
    except Exception as exc:
        log.warning("Rules store init failed: %s", exc)

    # 2. ChromaDB: rebuild if empty (cold start on a fresh volume)
    #    On normal deploys the KB is baked into the image (index-kb at build time)
    #    and this block is a fast no-op (count > 0).
    try:
        from src.rag.knowledge_base import HCAIKnowledgeBase
        kb = HCAIKnowledgeBase()
        n = kb.count()
        if n == 0:
            log.info("ChromaDB empty — indexing knowledge base (first run)…")
            kb.index_all_documents()
            log.info("Knowledge base ready: %d documents.", kb.count())
        else:
            log.info("Knowledge base ready: %d documents.", n)
    except Exception as exc:
        log.warning("Knowledge base init failed: %s", exc)

    # 3. PostgreSQL: create tables when DATABASE_URL / DB_HOST is configured
    try:
        from src.database.connection import is_postgres_configured, create_tables
        if is_postgres_configured():
            await create_tables()
            log.info("PostgreSQL tables created / verified.")
    except Exception as exc:
        log.warning("PostgreSQL init failed: %s", exc)

    # 4. Runtime directories (ephemeral on Railway — recreated each start)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def _on_shutdown() -> None:
    """Clean up on shutdown."""
    try:
        from src.database.connection import is_postgres_configured, dispose
        if is_postgres_configured():
            await dispose()
    except Exception:
        pass


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await _on_startup()
    yield
    await _on_shutdown()


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
        title="BlueprintIQ — HCAI Compliance Engine",
        description=(
            "California healthcare construction plan review, automated. "
            "Submit project drawings or specifications and receive HCAI-style "
            "compliance violations with Title 24 / PIN / CAN citations and "
            "step-by-step remediation guidance."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
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

    # Serve the SPA frontend from static/ — must come AFTER API routes
    _static_dir = Path(__file__).parent.parent.parent / "static"
    if _static_dir.exists():
        app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")

    return app


def _base_url(request) -> str:
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# Email completion helper (runs in background thread)
# ---------------------------------------------------------------------------

def _send_completion_email_when_ready(
    job_id: str,
    customer_email: str,
    project_name: str,
    store,
    *,
    max_wait_seconds: int = 300,
    poll_interval: int = 5,
) -> None:
    """Poll until the job completes, then send the PDF report email."""
    import time
    from uuid import UUID
    from src.api.email_delivery import send_report_email

    uid = UUID(job_id)
    waited = 0
    while waited < max_wait_seconds:
        time.sleep(poll_interval)
        waited += poll_interval
        job = store.get(uid)
        if not job:
            return
        if job.status.value in ("complete", "failed"):
            break

    job = store.get(uid)
    if not job or job.status.value != "complete":
        return

    import config
    pdf_path = config.OUTPUT_DIR / job_id / "report.pdf"
    total    = job.summary.total if job.summary else 0
    critical = (job.summary.by_severity.Critical if job.summary else 0) or 0
    high     = (job.summary.by_severity.High     if job.summary else 0) or 0

    send_report_email(
        to_email=customer_email,
        project_name=project_name,
        job_id=job_id,
        pdf_path=pdf_path if pdf_path.exists() else None,
        total_violations=total,
        critical_count=critical,
        high_count=high,
    )


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
        response_model=list[RuleResponse],
        tags=["Rules"],
    )
    async def list_rules(
        discipline: Optional[str] = None,
        active_only: bool = True,
        _api_key: str = Depends(require_api_key),
    ) -> list[dict]:
        """
        List compliance rules from the persistent store.

        - `active_only=true` (default) — returns only enabled rules
        - `active_only=false` — returns all rules including disabled ones
        - `discipline` — filter by discipline name (e.g. `Infection Control`)
        """
        from src.db.rules_store import get_rules_store
        store = get_rules_store()
        if discipline:
            return store.get_by_discipline(discipline, active_only=active_only)
        return store.get_all_active() if active_only else store.get_all()

    # ------------------------------------------------- GET /rules/disciplines
    @app.get(
        "/rules/disciplines",
        response_model=list[str],
        tags=["Rules"],
    )
    async def list_disciplines(
        _api_key: str = Depends(require_api_key),
    ) -> list[str]:
        """Return the distinct discipline names present in the active rule set."""
        from src.db.rules_store import get_rules_store
        return get_rules_store().list_disciplines()

    @app.get(
        "/rules/{rule_id}",
        response_model=RuleResponse,
        tags=["Rules"],
    )
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

    @app.post(
        "/rules",
        status_code=status.HTTP_201_CREATED,
        response_model=RuleResponse,
        tags=["Rules"],
    )
    async def upsert_rule(
        rule: RuleCreateRequest,
        _api_key: str = Depends(require_api_key),
    ) -> dict:
        """
        Insert or update a rule.

        All trigger lists default to empty (applies to all). Set
        `trigger_construction_types`, `min_licensed_beds`, or
        `trigger_sprinklered` to scope the rule precisely.
        """
        from src.db.rules_store import get_rules_store
        store = get_rules_store()
        store.upsert_rule(rule.model_dump())
        return store.get_by_id(rule.id)

    # ------------------------------------------------------- GET /jobs/stats
    @app.get(
        "/jobs/stats",
        tags=["Review"],
    )
    async def job_stats(
        store: JobStore = Depends(get_job_store),
        _api_key: str = Depends(require_api_key),
    ) -> dict:
        """
        Return a summary of job counts grouped by status.

        Useful for monitoring dashboards and health checks.
        """
        jobs = store.list_recent(limit=10_000)
        counts: dict[str, int] = {}
        for job in jobs:
            key = job.status.value
            counts[key] = counts.get(key, 0) + 1
        return {
            "total": len(jobs),
            "by_status": counts,
        }

    # ---------------------------------------- POST /checkout/create (billing)
    @app.post("/checkout/create", tags=["Billing"])
    async def checkout_create(
        request: Request,
        background_tasks: BackgroundTasks,
        store: JobStore = Depends(get_job_store),
        project_name: str = Form(...),
        email: str = Form(...),
        file: Optional[UploadFile] = File(default=None),
        text: Optional[str] = Form(default=None),
    ) -> dict:
        """
        Create a Stripe Checkout session and (in dev mode) start a review job.

        Returns { checkout_url, job_id }. If Stripe is not configured,
        checkout_url is null and the job starts immediately.
        """
        from src.api.billing import create_checkout_session
        import uuid

        if not file and not (text and text.strip()):
            raise HTTPException(status_code=400, detail="Provide a file or text.")

        job_id = str(uuid.uuid4())

        # Save uploaded file to temp location
        temp_file_path: Optional[str] = None
        pasted_text: Optional[str] = None

        if file and file.filename:
            import tempfile, os as _os
            suffix = Path(file.filename).suffix or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(await file.read())
                temp_file_path = tmp.name
        elif text and text.strip():
            pasted_text = text.strip()

        # Try to create Stripe Checkout session
        checkout_url = create_checkout_session(
            job_id=job_id,
            project_name=project_name,
            customer_email=email,
            temp_file_path=temp_file_path,
            pasted_text=pasted_text,
        )

        if checkout_url:
            # Payment required — job starts after webhook fires
            return {"checkout_url": checkout_url, "job_id": job_id}

        # Dev mode — no Stripe configured, start job immediately
        job = store.create(project_name)
        # Override the auto-generated UUID so job_id matches what we advertised
        import config
        from uuid import UUID
        job.job_id = UUID(job_id)
        store.update(job)

        pdf_bytes: Optional[bytes] = None
        if temp_file_path:
            with open(temp_file_path, "rb") as f:
                pdf_bytes = f.read()
            import os as _os2
            _os2.unlink(temp_file_path)

        background_tasks.add_task(
            run_review,
            job_id=UUID(job_id),
            store=store,
            project_name=project_name,
            text=pasted_text,
            pdf_bytes=pdf_bytes,
            pdf_filename=None,
            no_rag=False,
            fmt=OutputFormat.pdf,
            base_url=_base_url(request),
        )

        return {"checkout_url": None, "job_id": job_id}

    # --------------------------------------- POST /checkout/webhook (Stripe)
    @app.post("/checkout/webhook", tags=["Billing"], include_in_schema=False)
    async def checkout_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        store: JobStore = Depends(get_job_store),
    ) -> dict:
        """Stripe webhook — fires after successful payment, starts the review job."""
        from src.api.billing import handle_webhook
        from uuid import UUID

        payload    = await request.body()
        sig_header = request.headers.get("stripe-signature", "")

        order = handle_webhook(payload, sig_header)
        if not order:
            # Not a payment event we care about, or already handled
            return {"received": True}

        # Retrieve or create job
        job = store.get(UUID(order.job_id))
        if not job:
            job = store.create(order.project_name)
            job.job_id = UUID(order.job_id)
            store.update(job)

        pdf_bytes: Optional[bytes] = None
        if order.temp_file_path:
            import os as _os3
            try:
                with open(order.temp_file_path, "rb") as f:
                    pdf_bytes = f.read()
            finally:
                _os3.unlink(order.temp_file_path)

        background_tasks.add_task(
            run_review,
            job_id=UUID(order.job_id),
            store=store,
            project_name=order.project_name,
            text=order.pasted_text,
            pdf_bytes=pdf_bytes,
            pdf_filename=None,
            no_rag=False,
            fmt=OutputFormat.pdf,
            base_url=str(request.base_url).rstrip("/"),
        )

        # Send email when complete — piggyback on a completion hook via background task
        background_tasks.add_task(
            _send_completion_email_when_ready,
            job_id=order.job_id,
            customer_email=order.customer_email,
            project_name=order.project_name,
            store=store,
        )

        return {"received": True}

    # --------------------------------------- GET /checkout/status
    @app.get("/checkout/status", tags=["Billing"])
    async def checkout_status(session_id: str) -> dict:
        """Look up the job_id for a completed Stripe Checkout session."""
        from src.api.billing import lookup_job_for_session
        job_id = lookup_job_for_session(session_id)
        return {"paid": job_id is not None, "job_id": job_id}

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

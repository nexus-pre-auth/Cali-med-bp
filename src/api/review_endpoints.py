"""
Review endpoint — runs the full compliance pipeline via HTTP.

POST /review/submit   Upload a PDF or submit text, run compliance check, return report
GET  /review/{id}     Fetch a past review by ID
GET  /review/list     List all reviews for the current firm
"""

from __future__ import annotations

import io
import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import config
from src.api.auth import CurrentFirm

log = logging.getLogger(__name__)

review_router = APIRouter(prefix="/review", tags=["review"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ViolationOut(BaseModel):
    rule_id: str
    discipline: str
    severity: str
    trigger_condition: str
    ahj_comment: str
    fix_instructions: str
    citations: list[str]


class ReviewResult(BaseModel):
    review_id: Optional[str]
    project_name: str
    state: str
    occupancy_type: Optional[str]
    total_violations: int
    critical: int
    high: int
    medium: int
    low: int
    violations: list[ViolationOut]
    report_html: str
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _supabase():
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _run_pipeline(text: str, project_name: str) -> dict:
    """Run the full compliance pipeline on extracted text. Returns result dict."""
    from src.parser.pdf_parser import PDFParser
    from src.parser.condition_extractor import ConditionExtractor
    from src.engine.decision_engine import DecisionEngine
    from src.rag.generator import AHJCommentGenerator
    from src.reports.report_generator import render_html_report, render_json_report

    parser    = PDFParser()
    extractor = ConditionExtractor()
    engine    = DecisionEngine()

    doc        = parser.parse_text_input(text, source_name=project_name)
    conditions = extractor.extract(doc)
    violations = engine.evaluate(conditions)

    generator  = AHJCommentGenerator(use_rag=bool(config.ANTHROPIC_API_KEY))
    enriched   = generator.enrich(violations, conditions)

    html = render_html_report(enriched, conditions, project_name)

    summary = engine.summary(violations)

    return {
        "conditions":  conditions,
        "enriched":    enriched,
        "summary":     summary,
        "html":        html,
        "report_json": render_json_report(enriched, conditions, project_name),
    }


def _store_review(firm_ctx, project_name: str, result: dict) -> str:
    """Persist project + review rows in Supabase. Returns review_id."""
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY) or not firm_ctx.firm:
        return "local"

    sb  = _supabase()
    conds = result["conditions"]
    summary = result["summary"]

    # Create project row
    proj = sb.table("projects").insert({
        "firm_id":       firm_ctx.firm_id,
        "name":          project_name,
        "occupancy_type": conds.occupancy_type,
        "status":        "complete",
        "product_slug":  "medblueprints",
    }).execute()
    project_id = proj.data[0]["id"] if proj.data else None

    if not project_id:
        return "local"

    # Create review row
    violations_json = json.loads(result["report_json"])
    rev = sb.table("reviews").insert({
        "project_id":      project_id,
        "total_violations": summary["total"],
        "critical_count":  summary["by_severity"]["Critical"],
        "high_count":      summary["by_severity"]["High"],
        "medium_count":    summary["by_severity"]["Medium"],
        "low_count":       summary["by_severity"]["Low"],
        "report_json":     violations_json,
        "conditions_json": {
            "occupancy_type":   conds.occupancy_type,
            "state":            conds.state,
            "state_code":       conds.state_code,
            "county":           conds.county,
            "construction_type": conds.construction_type,
        },
        "completed_at": datetime.now().isoformat(),
    }).execute()
    review_id = rev.data[0]["id"] if rev.data else "local"

    # Insert individual violation rows
    enriched = result["enriched"]
    if enriched and review_id != "local":
        sb.table("violations").insert([{
            "review_id":        review_id,
            "rule_key":         ev.violation.rule_id,
            "severity":         ev.violation.severity.value,
            "discipline":       ev.violation.discipline,
            "description":      ev.violation.description,
            "ahj_comment":      ev.ahj_comment,
            "fix_instructions": ev.fix_instructions,
            "citations":        ev.citations,
        } for ev in enriched]).execute()

    # Increment reviews_used on firm
    used = firm_ctx.firm.get("reviews_used", 0) + 1
    sb.table("firms").update({"reviews_used": used}).eq("id", firm_ctx.firm_id).execute()

    return review_id


# ---------------------------------------------------------------------------
# POST /review/submit
# ---------------------------------------------------------------------------

@review_router.post("/submit", response_model=ReviewResult)
async def submit_review(
    firm_ctx: CurrentFirm,
    project_name: str = Form("Healthcare Project"),
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
):
    """
    Run a full compliance review.
    Send either a PDF file (multipart) or raw text (form field).
    Requires a valid JWT and at least one review credit.
    """
    if not firm_ctx.can_review:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="No review credits remaining. Purchase a review or subscribe at /billing/checkout.",
        )

    if not file and not text:
        raise HTTPException(status_code=400, detail="Provide a PDF file or text input.")

    # Extract text from uploaded PDF
    if file:
        content = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            from src.parser.pdf_parser import PDFParser
            doc = PDFParser().parse(tmp_path)
            text = doc.full_text
        finally:
            tmp_path.unlink(missing_ok=True)

    try:
        result = _run_pipeline(text, project_name)
    except Exception as exc:
        log.exception("Pipeline error")
        raise HTTPException(status_code=500, detail=f"Review failed: {exc}") from exc

    review_id = _store_review(firm_ctx, project_name, result)

    # Send report email (best-effort)
    try:
        await _send_report_email(firm_ctx, project_name, result, review_id)
    except Exception:
        log.warning("Email delivery failed (non-fatal)")

    conds   = result["conditions"]
    summary = result["summary"]
    return ReviewResult(
        review_id=review_id,
        project_name=project_name,
        state=conds.state,
        occupancy_type=conds.occupancy_type,
        total_violations=summary["total"],
        critical=summary["by_severity"]["Critical"],
        high=summary["by_severity"]["High"],
        medium=summary["by_severity"]["Medium"],
        low=summary["by_severity"]["Low"],
        violations=[
            ViolationOut(
                rule_id=ev.violation.rule_id,
                discipline=ev.violation.discipline,
                severity=ev.violation.severity.value,
                trigger_condition=ev.violation.trigger_condition,
                ahj_comment=ev.ahj_comment,
                fix_instructions=ev.fix_instructions,
                citations=ev.citations,
            )
            for ev in result["enriched"]
        ],
        report_html=result["html"],
        created_at=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# GET /review/{review_id}/html  — download the HTML report
# ---------------------------------------------------------------------------

@review_router.get("/{review_id}/html", response_class=HTMLResponse)
async def get_report_html(review_id: str, firm_ctx: CurrentFirm):
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY):
        raise HTTPException(status_code=404, detail="Supabase not configured")

    sb = _supabase()
    row = sb.table("reviews").select("report_json, project_id").eq("id", review_id).single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail="Review not found")

    # Verify ownership
    proj = sb.table("projects").select("firm_id, name").eq("id", row.data["project_id"]).single().execute()
    if not proj.data or proj.data["firm_id"] != firm_ctx.firm_id:
        raise HTTPException(status_code=403, detail="Not your review")

    from src.reports.report_generator import render_html_report
    from src.parser.condition_extractor import ProjectConditions
    from src.rag.generator import EnrichedViolation
    from src.engine.rule_matcher import MatchedViolation
    from src.engine.severity_scorer import Severity

    data = row.data["report_json"]
    project_name = proj.data.get("name", "Project")

    # Reconstruct enriched list from stored JSON
    enriched = []
    for v in data.get("violations", []):
        mv = MatchedViolation(
            rule_id=v["rule_id"], discipline=v["discipline"],
            severity=Severity(v["severity"]), trigger_condition=v["trigger_condition"],
            description=v.get("trigger_condition", ""), violation_text="", fix_text="",
        )
        enriched.append(EnrichedViolation(
            violation=mv, ahj_comment=v["ahj_comment"],
            fix_instructions=v["fix_instructions"], citations=v["citations"],
            rag_passages_used=[],
        ))

    conds = ProjectConditions(
        occupancy_type=data.get("facility_type"),
        county=data.get("county"),
    )
    return HTMLResponse(render_html_report(enriched, conds, project_name))


# ---------------------------------------------------------------------------
# GET /review/list
# ---------------------------------------------------------------------------

@review_router.get("/list")
async def list_reviews(firm_ctx: CurrentFirm):
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY) or not firm_ctx.firm:
        return {"reviews": []}

    sb = _supabase()
    projects = sb.table("projects").select("id, name, created_at").eq("firm_id", firm_ctx.firm_id).execute()
    if not projects.data:
        return {"reviews": []}

    project_ids = [p["id"] for p in projects.data]
    project_map = {p["id"]: p["name"] for p in projects.data}

    reviews = sb.table("reviews").select(
        "id, project_id, total_violations, critical_count, high_count, medium_count, low_count, completed_at"
    ).in_("project_id", project_ids).order("completed_at", desc=True).execute()

    return {
        "reviews": [
            {
                "review_id":        r["id"],
                "project_name":     project_map.get(r["project_id"], ""),
                "total_violations": r["total_violations"],
                "critical":         r["critical_count"],
                "high":             r["high_count"],
                "medium":           r["medium_count"],
                "low":              r["low_count"],
                "completed_at":     r["completed_at"],
            }
            for r in (reviews.data or [])
        ]
    }


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------

async def _send_report_email(firm_ctx, project_name: str, result: dict, review_id: str):
    """Send the HTML report to the firm's contact email via Resend (or SMTP fallback)."""
    firm = firm_ctx.firm or {}
    to_email = firm.get("contact_email")
    if not to_email:
        return

    summary = result["summary"]
    subject = f"Your Medblueprints Report — {project_name} ({summary['total']} violations)"

    resend_key = config.__dict__.get("RESEND_API_KEY", "")
    if resend_key:
        import resend as resend_lib
        resend_lib.api_key = resend_key
        resend_lib.Emails.send({
            "from":    "reports@medblueprints.com",
            "to":      [to_email],
            "subject": subject,
            "html":    result["html"],
        })
        return

    # SMTP fallback using existing alert SMTP config
    if config.ALERT_SMTP_HOST and config.ALERT_SMTP_USER:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = config.ALERT_EMAIL_FROM or config.ALERT_SMTP_USER
        msg["To"]      = to_email
        msg.attach(MIMEText(result["html"], "html"))

        with smtplib.SMTP(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT) as server:
            server.starttls()
            server.login(config.ALERT_SMTP_USER, config.ALERT_SMTP_PASS)
            server.sendmail(msg["From"], [to_email], msg.as_string())

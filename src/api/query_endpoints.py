"""
FastAPI router for natural-language compliance queries.

Mounted in main.py's `serve` command as:
    app.include_router(query_router)

Endpoints:
    POST /query/ask          — ask any compliance question in plain English
    POST /query/checklist    — generate a back-check prevention checklist
    POST /query/violations   — summarise / filter a list of violations
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.rag.nl_query import NLQueryEngine

query_router = APIRouter(prefix="/query", tags=["natural-language query"])

# Shared engine instance (KB loaded lazily on first request)
_engine: Optional[NLQueryEngine] = None


def _get_engine() -> NLQueryEngine:
    global _engine
    if _engine is None:
        try:
            from src.rag.knowledge_base import HCAIKnowledgeBase
            kb = HCAIKnowledgeBase()
            if kb.count() == 0:
                kb.load_from_files()
        except Exception:
            kb = None
        _engine = NLQueryEngine(knowledge_base=kb)
    return _engine


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str = Field(..., min_length=5, description="Plain-English compliance question.")
    top_k: int    = Field(default=8, ge=1, le=20, description="Number of context passages to retrieve.")


class ChecklistRequest(BaseModel):
    occupancy:    str = Field(..., description='e.g. "Occupied Hospital", "Surgical Center"')
    project_type: str = Field(default="new", pattern="^(new|renovation)$")


class ViolationFilterRequest(BaseModel):
    violations:       List[Dict] = Field(..., description="List of violation dicts from the review API.")
    filter_severity:  Optional[str] = Field(None, description='e.g. "Critical", "High"')


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@query_router.post("/ask")
async def ask_compliance_question(req: AskRequest):
    """
    Answer a plain-English compliance question using RAG + Claude.

    Example:
        {"question": "What are the ASHRAE 170 ACH requirements for an isolation room?"}
    """
    try:
        result = await _get_engine().query(req.question, top_k=req.top_k)
        return result.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@query_router.post("/checklist")
async def generate_checklist(req: ChecklistRequest):
    """
    Generate a back-check prevention checklist for the given occupancy type.

    Example:
        {"occupancy": "Occupied Hospital", "project_type": "new"}
    """
    try:
        checklist = await _get_engine().generate_checklist(
            req.occupancy, req.project_type
        )
        return {"occupancy": req.occupancy, "project_type": req.project_type, "checklist": checklist}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@query_router.post("/violations/summarise")
async def summarise_violations(req: ViolationFilterRequest):
    """
    Summarise and optionally filter a list of violations from a review result.

    Pass the full JSON violations array from a /review response and optionally
    filter to a specific severity level.
    """
    try:
        summary = await _get_engine().query_violations(
            req.violations, req.filter_severity
        )
        return {
            "filter_severity": req.filter_severity,
            "total_input":     len(req.violations),
            "summary":         summary,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

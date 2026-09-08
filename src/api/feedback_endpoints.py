"""
FastAPI router for real-time AHJ feedback collection and dashboard.

Mount this router in the FastAPI app created by main.py's `serve` command:

    app.include_router(feedback_router)
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from src.api.security import rate_limit, require_admin_token, require_api_token
from src.feedback.models import AHJFeedback
from src.feedback.processor import FeedbackProcessor
from src.ml.trainer import ModelTrainer

logger = logging.getLogger("hcai.feedback_endpoints")

feedback_router = APIRouter(
    prefix="/feedback",
    tags=["feedback"],
    dependencies=[Depends(require_api_token), Depends(rate_limit)],
)

_processor = FeedbackProcessor()
_trainer   = ModelTrainer()

_GENERIC_ERROR = "Request could not be processed. Please check your input and try again."


# ---------------------------------------------------------------------------
# Submission endpoints
# ---------------------------------------------------------------------------

@feedback_router.post("/submit")
async def submit_ahj_feedback(
    feedback: AHJFeedback,
    background_tasks: BackgroundTasks,
):
    """
    Submit real-time feedback from an AHJ plan check.

    Stores the feedback asynchronously, then checks whether the accumulated
    batch is large enough to trigger model retraining. Feedback is stored as
    candidate training data only — it never updates the production model
    without going through `ModelTrainer`'s evaluation/improvement gate
    (see `/feedback/retrain`, which is admin-protected).
    """
    try:
        stored = await _processor.store_feedback(feedback)

        background_tasks.add_task(_processor.process_feedback_batch, stored)

        if await _processor.should_retrain():
            background_tasks.add_task(
                _trainer.trigger_retraining,
                "batch_threshold_reached",
            )

        return {
            "status": "success",
            "feedback_id": stored.feedback_id,
            "message": "Feedback recorded. Thank you for improving the system!",
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("submit_ahj_feedback failed")
        raise HTTPException(status_code=400, detail=_GENERIC_ERROR)


@feedback_router.post("/batch")
async def submit_batch_feedback(
    feedback_batch: List[AHJFeedback],
    background_tasks: BackgroundTasks,
):
    """Submit multiple feedback entries in one request."""
    try:
        stored_ids: List[str] = []
        for fb in feedback_batch:
            stored = await _processor.store_feedback(fb)
            stored_ids.append(stored.feedback_id)

        background_tasks.add_task(_processor.process_batch, stored_ids)

        return {
            "status": "success",
            "feedback_count": len(stored_ids),
            "feedback_ids": stored_ids,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("submit_batch_feedback failed")
        raise HTTPException(status_code=400, detail=_GENERIC_ERROR)


# ---------------------------------------------------------------------------
# Metrics & dashboard
# ---------------------------------------------------------------------------

@feedback_router.get("/metrics")
async def get_feedback_metrics(
    days: int = Query(default=30, ge=1, le=365),
    ahj_name: Optional[str] = Query(default=None, max_length=200),
):
    """Return aggregated accuracy metrics for the requested time window."""
    try:
        return await _processor.get_metrics(days=days, ahj_name=ahj_name)
    except Exception:
        logger.exception("get_feedback_metrics failed")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR)


@feedback_router.get("/dashboard")
async def get_feedback_dashboard():
    """Return all data needed to render the real-time feedback dashboard."""
    try:
        return await _processor.get_dashboard()
    except Exception:
        logger.exception("get_feedback_dashboard failed")
        raise HTTPException(status_code=500, detail=_GENERIC_ERROR)


# ---------------------------------------------------------------------------
# Model management (administrative — requires API_ADMIN_TOKENS)
# ---------------------------------------------------------------------------

@feedback_router.post("/retrain", dependencies=[Depends(require_admin_token)])
async def trigger_manual_retraining(background_tasks: BackgroundTasks):
    """
    Manually kick off model retraining (administrative endpoint).

    Retraining still goes through `ModelTrainer`'s improvement gate
    (`_is_improvement`, requires >= 0.02 F1 gain) before any new model
    artifact replaces the active production model.
    """
    background_tasks.add_task(_trainer.trigger_retraining, "manual_request")
    return {"status": "retraining_queued", "message": "Model retraining has been scheduled."}


@feedback_router.get("/model/version")
async def get_model_version():
    """Return the currently active model version."""
    return {
        "current_version": _trainer.current_model_version,
        "model_dir": str(_trainer.model_dir),
    }

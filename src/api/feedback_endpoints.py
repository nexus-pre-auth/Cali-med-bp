"""
FastAPI router for real-time AHJ feedback collection and dashboard.

Mount this router in the FastAPI app created by main.py's `serve` command:

    app.include_router(feedback_router)
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.feedback.models import AHJFeedback
from src.feedback.processor import FeedbackProcessor
from src.ml.trainer import ModelTrainer

feedback_router = APIRouter(prefix="/feedback", tags=["feedback"])

_processor = FeedbackProcessor()
_trainer   = ModelTrainer()


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
    batch is large enough to trigger model retraining.
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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Metrics & dashboard
# ---------------------------------------------------------------------------

@feedback_router.get("/metrics")
async def get_feedback_metrics(days: int = 30, ahj_name: Optional[str] = None):
    """Return aggregated accuracy metrics for the requested time window."""
    return await _processor.get_metrics(days=days, ahj_name=ahj_name)


@feedback_router.get("/dashboard")
async def get_feedback_dashboard():
    """Return all data needed to render the real-time feedback dashboard."""
    return await _processor.get_dashboard()


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------

@feedback_router.post("/retrain")
async def trigger_manual_retraining(background_tasks: BackgroundTasks):
    """Manually kick off model retraining (admin use)."""
    background_tasks.add_task(_trainer.trigger_retraining, "manual_request")
    return {"status": "retraining_queued", "message": "Model retraining has been scheduled."}


@feedback_router.get("/model/version")
async def get_model_version():
    """Return the currently active model version."""
    return {
        "current_version": _trainer.current_model_version,
        "model_dir": str(_trainer.model_dir),
    }

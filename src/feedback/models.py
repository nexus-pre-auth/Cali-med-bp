"""
Pydantic models for AHJ plan checker feedback data.

All models use Pydantic v2 syntax. Feedback is the primary input
for the continuous learning pipeline.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import uuid

from pydantic import BaseModel, Field


class FeedbackType(str, Enum):
    WAIVER_PREDICTION = "waiver_prediction"
    VIOLATION_DETECTION = "violation_detection"
    SEVERITY_SCORING = "severity_scoring"
    RULE_ACCURACY = "rule_accuracy"
    AI_COMMENT_QUALITY = "ai_comment_quality"


class AHJFeedback(BaseModel):
    """Real-time feedback from AHJ plan checkers."""

    # Core identifiers
    feedback_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    project_name: str
    ahj_name: str  # e.g. "HCAI Sacramento", "OSHPD", "DSA"
    reviewer_id: str  # Anonymous or hashed for privacy

    # Feedback type
    feedback_type: FeedbackType

    # Waiver prediction fields
    waiver_actual_outcome: Optional[str] = None  # "approved" | "rejected" | "conditional"
    waiver_predicted_probability: Optional[float] = None

    # Violation detection fields
    detected_violations: List[Dict] = Field(default_factory=list)   # What our system found
    ahj_actual_violations: List[Dict] = Field(default_factory=list) # What AHJ actually cited
    false_positives: List[str] = Field(default_factory=list)        # Rules flagged incorrectly
    false_negatives: List[str] = Field(default_factory=list)        # Rules missed

    # Severity scoring fields
    severity_accuracy: Dict[str, str] = Field(default_factory=dict)  # {rule_id: "our_score vs actual"}

    # AI comment quality fields
    ai_comment_rating: Optional[int] = None        # 1–5 stars
    ai_comment_used_as_is: bool = False
    ai_comment_modified: Optional[str] = None
    time_saved_minutes: Optional[int] = None

    # Metadata
    review_time_seconds: int = 0
    reviewer_confidence: int = 5  # 1–10
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

    # Privacy & compliance
    is_anonymized: bool = True
    data_use_consent: bool = True


class FeedbackBatch(BaseModel):
    """Batch of feedback identifiers associated with a training epoch."""

    feedback_ids: List[str]
    training_epoch: int
    model_version: str
    aggregated_metrics: Dict
    created_at: datetime = Field(default_factory=datetime.now)

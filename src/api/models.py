"""
Pydantic models for API request/response contracts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class SeverityEnum(str, Enum):
    critical = "Critical"
    high     = "High"
    medium   = "Medium"
    low      = "Low"


class JobStatus(str, Enum):
    pending    = "pending"
    processing = "processing"
    complete   = "complete"
    failed     = "failed"


class OutputFormat(str, Enum):
    text = "text"
    json = "json"
    html = "html"
    pdf  = "pdf"
    all  = "all"


# ---------------------------------------------------------------------------
# Review request / response
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    project_name: str = Field(default="Healthcare Project", description="Human-readable project name")
    text: Optional[str] = Field(default=None, description="Inline project description text")
    format: OutputFormat = Field(default=OutputFormat.all, description="Report output format")
    no_rag: bool = Field(default=False, description="Skip RAG enrichment for faster (template-based) results")


class SeismicInfo(BaseModel):
    seismic_zone: Optional[str] = None
    sds: Optional[float] = None
    sd1: Optional[float] = None
    importance_factor: Optional[float] = None
    site_class: Optional[str] = None


class ExtractedConditions(BaseModel):
    occupancy_type: Optional[str]
    construction_type: Optional[str]
    sprinklered: Optional[bool]
    licensed_beds: Optional[int]
    county: Optional[str]
    city: Optional[str]
    seismic: SeismicInfo
    hvac_systems: list[str]
    electrical_systems: list[str]
    plumbing_systems: list[str]
    medical_gas_systems: list[str]
    room_types: list[str]
    extraction_confidence: float


class ViolationResponse(BaseModel):
    rule_id: str
    discipline: str
    severity: SeverityEnum
    trigger_condition: str
    ahj_comment: str
    fix_instructions: str
    citations: list[str]
    confidence: Optional[float] = None


class SeveritySummary(BaseModel):
    Critical: int = 0
    High: int = 0
    Medium: int = 0
    Low: int = 0


class ReviewSummary(BaseModel):
    total: int
    by_severity: SeveritySummary


class ReviewResponse(BaseModel):
    job_id: UUID
    project_name: str
    status: JobStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    conditions: Optional[ExtractedConditions] = None
    summary: Optional[ReviewSummary] = None
    violations: list[ViolationResponse] = []
    report_urls: dict[str, str] = {}
    metrics: Optional[dict] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Job status response (lightweight polling)
# ---------------------------------------------------------------------------

class JobStatusResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    rules_loaded: int
    kb_documents: int
    version: str = "1.0.0"


# ---------------------------------------------------------------------------
# Rules request / response
# ---------------------------------------------------------------------------

class RuleResponse(BaseModel):
    """Full rule record returned by GET /rules and GET /rules/{id}."""
    id: str
    discipline: str
    description: str
    violation_template: str = ""
    fix_template: str = ""
    severity_override: Optional[str] = None
    min_licensed_beds: Optional[int] = None
    is_active: bool = True
    trigger_occupancies: list[str] = []
    trigger_systems: list[str] = []
    trigger_rooms: list[str] = []
    trigger_seismic_zones: list[str] = []
    trigger_construction_types: list[str] = []
    trigger_sprinklered: Optional[bool] = None
    code_references: list[str] = []


class RuleCreateRequest(BaseModel):
    """Payload for POST /rules (insert or update a rule)."""
    id: str = Field(..., description="Unique rule identifier, e.g. RULE-042")
    discipline: str = Field(..., description="Discipline category, e.g. 'Infection Control'")
    description: str = Field(..., description="Human-readable rule description")
    violation_template: str = Field(default="", description="Template text for the violation message")
    fix_template: str = Field(default="", description="Template text for remediation guidance")
    severity_override: Optional[SeverityEnum] = Field(default=None, description="Force severity level (null = auto-scored)")
    min_licensed_beds: Optional[int] = Field(default=None, ge=1, description="Minimum licensed beds for rule to apply")
    trigger_occupancies: list[str] = Field(default_factory=list)
    trigger_systems: list[str] = Field(default_factory=list)
    trigger_rooms: list[str] = Field(default_factory=list)
    trigger_seismic_zones: list[str] = Field(default_factory=list)
    trigger_construction_types: list[str] = Field(default_factory=list)
    trigger_sprinklered: Optional[bool] = Field(default=None, description="True=sprinklered only, False=non-sprinklered only, null=either")
    code_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation request / response
# ---------------------------------------------------------------------------

class ValidationRequest(BaseModel):
    text: str
    ground_truth: Optional[list[dict]] = None


class ChecklistItemResponse(BaseModel):
    category: str
    description: str
    passed: bool
    score: float
    detail: str = ""


class ValidationResponse(BaseModel):
    overall_score: float
    passed_count: int
    total_count: int
    summary: str
    by_category: dict[str, float]
    items: list[ChecklistItemResponse]

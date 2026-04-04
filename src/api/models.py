"""
Pydantic models for API request/response contracts.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class SeverityEnum(StrEnum):
    critical = "Critical"
    high     = "High"
    medium   = "Medium"
    low      = "Low"


class JobStatus(StrEnum):
    pending    = "pending"
    processing = "processing"
    complete   = "complete"
    failed     = "failed"


class OutputFormat(StrEnum):
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
    text: str | None = Field(default=None, description="Inline project description text")
    format: OutputFormat = Field(default=OutputFormat.all, description="Report output format")
    no_rag: bool = Field(default=False, description="Skip RAG enrichment for faster (template-based) results")


class SeismicInfo(BaseModel):
    seismic_zone: str | None = None
    sds: float | None = None
    sd1: float | None = None
    importance_factor: float | None = None
    site_class: str | None = None


class ExtractedConditions(BaseModel):
    occupancy_type: str | None
    construction_type: str | None
    sprinklered: bool | None
    licensed_beds: int | None
    county: str | None
    city: str | None
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
    confidence: float | None = None


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
    completed_at: datetime | None = None
    conditions: ExtractedConditions | None = None
    summary: ReviewSummary | None = None
    violations: list[ViolationResponse] = []
    report_urls: dict[str, str] = {}
    metrics: dict | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Job status response (lightweight polling)
# ---------------------------------------------------------------------------

class JobStatusResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    created_at: datetime
    completed_at: datetime | None = None
    error: str | None = None


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
    severity_override: str | None = None
    min_licensed_beds: int | None = None
    min_building_height_ft: float | None = None
    min_stories: int | None = None
    is_active: bool = True
    trigger_occupancies: list[str] = []
    trigger_systems: list[str] = []
    trigger_rooms: list[str] = []
    trigger_seismic_zones: list[str] = []
    trigger_construction_types: list[str] = []
    trigger_sprinklered: bool | None = None
    trigger_counties: list[str] = []
    trigger_cities: list[str] = []
    code_references: list[str] = []


class RuleCreateRequest(BaseModel):
    """Payload for POST /rules (insert or update a rule)."""
    id: str = Field(..., description="Unique rule identifier, e.g. RULE-042")
    discipline: str = Field(..., description="Discipline category, e.g. 'Infection Control'")
    description: str = Field(..., description="Human-readable rule description")
    violation_template: str = Field(default="", description="Template text for the violation message")
    fix_template: str = Field(default="", description="Template text for remediation guidance")
    severity_override: SeverityEnum | None = Field(default=None, description="Force severity level (null = auto-scored)")
    min_licensed_beds: int | None = Field(default=None, ge=1, description="Minimum licensed beds for rule to apply")
    min_building_height_ft: float | None = Field(default=None, gt=0, description="Minimum building height (ft) for rule to apply")
    min_stories: int | None = Field(default=None, ge=1, description="Minimum stories above grade for rule to apply")
    trigger_occupancies: list[str] = Field(default_factory=list)
    trigger_systems: list[str] = Field(default_factory=list)
    trigger_rooms: list[str] = Field(default_factory=list)
    trigger_seismic_zones: list[str] = Field(default_factory=list)
    trigger_construction_types: list[str] = Field(default_factory=list)
    trigger_sprinklered: bool | None = Field(default=None, description="True=sprinklered only, False=non-sprinklered only, null=either")
    trigger_counties: list[str] = Field(default_factory=list, description="County names for local amendment scoping")
    trigger_cities: list[str] = Field(default_factory=list, description="City names for local amendment scoping")
    code_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation request / response
# ---------------------------------------------------------------------------

class ValidationRequest(BaseModel):
    text: str
    ground_truth: list[dict] | None = None


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

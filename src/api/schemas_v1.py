"""Pydantic request/response models for the `/api/v1` SaaS API."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class OrganizationOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    is_active: bool = True
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    organization_id: str
    description: Optional[str] = Field(default=None, max_length=5000)
    occupancy_type: Optional[str] = Field(default=None, max_length=200)
    county: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"pending", "active", "archived", "completed"}:
            raise ValueError("invalid project status")
        return v


class ProjectOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    organization_id: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class DocumentOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    project_id: str
    original_filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    status: str = "uploaded"
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

class AnalysisCreate(BaseModel):
    document_id: str


class AnalysisOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    project_id: str
    document_id: Optional[str] = None
    status: str
    engine_version: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

class FindingOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    analysis_id: str
    rule_id: str
    discipline: Optional[str] = None
    severity: str
    title: Optional[str] = None
    requirement: Optional[str] = None
    project_evidence: Optional[str] = None
    required_condition: Optional[str] = None
    jurisdiction: str = "California (HCAI)"
    code_family: Optional[str] = None
    code_edition: Optional[str] = None
    section: Optional[str] = None
    subsection: Optional[str] = None
    source_document: Optional[str] = None
    source_reference: Optional[List[str]] = None
    citation_verified: bool = False
    confidence: Optional[str] = None
    recommended_action: Optional[str] = None
    status: str = "open"


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class ReportOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    project_id: str
    analysis_id: str
    format: str
    storage_path: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Revisions (re-analysis of a project against a new/updated document)
# ---------------------------------------------------------------------------

class RevisionCreate(BaseModel):
    document_id: str
    notes: Optional[str] = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Generic error envelope
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str

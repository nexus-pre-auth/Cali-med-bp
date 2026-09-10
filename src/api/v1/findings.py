"""`/api/v1/projects/{project_id}/findings` endpoints (read-only)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from src.auth.deps import ProjectContext, require_project_role
from src.auth.roles import Role
from src.api.schemas_v1 import FindingOut
from src.database.repositories_v1 import FindingRepository

router = APIRouter(prefix="/projects/{project_id}/findings", tags=["findings"])

_findings = FindingRepository()


@router.get("", response_model=List[FindingOut])
async def list_findings(ctx: ProjectContext = Depends(require_project_role(Role.VIEWER))):
    """List all findings across every analysis run for this project.

    Each finding carries full regulatory provenance (rule, severity,
    requirement, extracted project evidence, source reference, and whether
    that citation has been verified) so a user can answer "why was this
    flagged?" without the API fabricating authority it doesn't have.
    """
    rows = _findings.list_for_project(ctx.project_id)
    return [FindingOut.model_validate(r) for r in rows]

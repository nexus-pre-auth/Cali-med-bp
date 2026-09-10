"""`/api/v1/projects/{project_id}/reports` endpoints (read-only)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from src.auth.deps import ProjectContext, require_project_role
from src.auth.roles import Role
from src.api.schemas_v1 import ReportOut
from src.database.repositories_v1 import ReportRepository

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["reports"])

_reports = ReportRepository()


@router.get("", response_model=List[ReportOut])
async def list_reports(ctx: ProjectContext = Depends(require_project_role(Role.VIEWER))):
    rows = _reports.list_for_project(ctx.project_id)
    return [ReportOut.model_validate(r) for r in rows]

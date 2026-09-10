"""`/api/v1/projects/{project_id}/revisions` endpoints.

A "revision" is a re-analysis of a project against a new or updated
document — the same async analysis pipeline, tagged so the workflow
(upload -> analysis -> findings -> report -> revision -> re-analysis) is
explicit in the API rather than overloading `/analyses` semantics.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from src.analysis.pipeline import run_analysis
from src.auth.deps import ProjectContext, require_project_role
from src.auth.roles import Role
from src.api.schemas_v1 import AnalysisOut, RevisionCreate
from src.database.repositories_v1 import (
    AnalysisRepository,
    AuditLogRepository,
    DocumentRepository,
)

router = APIRouter(prefix="/projects/{project_id}/revisions", tags=["revisions"])

_analyses = AnalysisRepository()
_documents = DocumentRepository()
_audit = AuditLogRepository()


@router.post("", response_model=AnalysisOut, status_code=status.HTTP_202_ACCEPTED)
async def create_revision(
    payload: RevisionCreate,
    background_tasks: BackgroundTasks,
    ctx: ProjectContext = Depends(require_project_role(Role.MEMBER)),
):
    document = _documents.get(payload.document_id)
    if document is None or document.get("project_id") != ctx.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    row = _analyses.insert(
        {
            "project_id": ctx.project_id,
            "document_id": payload.document_id,
            "status": "QUEUED",
            "requested_by": ctx.user.user_id,
        }
    )
    _audit.log(
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user.user_id,
        action="revision.created",
        project_id=ctx.project_id,
        detail={"analysis_id": row["id"], "document_id": payload.document_id, "notes": payload.notes},
    )
    background_tasks.add_task(run_analysis, row["id"])
    return AnalysisOut.model_validate(row)


@router.get("", response_model=List[AnalysisOut])
async def list_revisions(ctx: ProjectContext = Depends(require_project_role(Role.VIEWER))):
    """Revisions are analyses requested after the project's first analysis."""
    rows = _analyses.list_for_project(ctx.project_id)
    rows_sorted = sorted(rows, key=lambda r: r.get("created_at") or "")
    return [AnalysisOut.model_validate(r) for r in rows_sorted[1:]]

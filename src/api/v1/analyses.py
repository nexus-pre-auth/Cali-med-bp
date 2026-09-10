"""`/api/v1/projects/{project_id}/analyses` endpoints — async analysis jobs."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from src.analysis.pipeline import run_analysis
from src.api.security import rate_limit
from src.auth.deps import ProjectContext, require_project_role
from src.auth.roles import Role
from src.api.schemas_v1 import AnalysisCreate, AnalysisOut
from src.database.repositories_v1 import (
    AnalysisRepository,
    AuditLogRepository,
    DocumentRepository,
)

router = APIRouter(prefix="/projects/{project_id}/analyses", tags=["analyses"])

_analyses = AnalysisRepository()
_documents = DocumentRepository()
_audit = AuditLogRepository()


@router.post("", response_model=AnalysisOut, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(rate_limit)])
async def create_analysis(
    payload: AnalysisCreate,
    background_tasks: BackgroundTasks,
    ctx: ProjectContext = Depends(require_project_role(Role.MEMBER)),
):
    document = _documents.get(payload.document_id)
    if document is None or document.get("project_id") != ctx.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if document.get("status") == "deleted":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document has been deleted.")

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
        action="analysis.created",
        project_id=ctx.project_id,
        detail={"analysis_id": row["id"], "document_id": payload.document_id},
    )

    # MVP async execution: FastAPI BackgroundTasks runs this after the
    # response is sent, in-process. For multi-worker/horizontal scaling,
    # replace this call with an enqueue onto Celery/RQ + Redis — the
    # `run_analysis(analysis_id)` function signature is queue-agnostic.
    background_tasks.add_task(run_analysis, row["id"])

    return AnalysisOut.model_validate(row)


@router.get("", response_model=List[AnalysisOut])
async def list_analyses(ctx: ProjectContext = Depends(require_project_role(Role.VIEWER))):
    rows = _analyses.list_for_project(ctx.project_id)
    return [AnalysisOut.model_validate(r) for r in rows]


@router.get("/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(
    analysis_id: str,
    ctx: ProjectContext = Depends(require_project_role(Role.VIEWER)),
):
    row = _analyses.get(analysis_id)
    if row is None or row.get("project_id") != ctx.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    return AnalysisOut.model_validate(row)

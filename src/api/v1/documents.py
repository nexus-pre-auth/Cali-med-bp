"""`/api/v1/projects/{project_id}/documents` endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from src.auth.deps import ProjectContext, require_project_role
from src.auth.roles import Role
from src.api.schemas_v1 import DocumentOut
from src.api.uploads import validate_and_store_upload
from src.database.repositories_v1 import AuditLogRepository, DocumentRepository

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])

_documents = DocumentRepository()
_audit = AuditLogRepository()


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    ctx: ProjectContext = Depends(require_project_role(Role.MEMBER)),
):
    validated = await validate_and_store_upload(ctx.project_id, file)
    row = _documents.insert(
        {
            "project_id": ctx.project_id,
            "original_filename": validated.original_filename,
            "storage_path": validated.storage_path,
            "content_type": validated.content_type,
            "size_bytes": validated.size_bytes,
            "status": "uploaded",
            "uploaded_by": ctx.user.user_id,
        }
    )
    _audit.log(
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user.user_id,
        action="document.uploaded",
        project_id=ctx.project_id,
        detail={"document_id": row["id"], "filename": validated.original_filename},
    )
    return DocumentOut.model_validate(row)


@router.get("", response_model=List[DocumentOut])
async def list_documents(ctx: ProjectContext = Depends(require_project_role(Role.VIEWER))):
    rows = _documents.list_for_project(ctx.project_id)
    return [DocumentOut.model_validate(r) for r in rows]


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: str,
    ctx: ProjectContext = Depends(require_project_role(Role.VIEWER)),
):
    row = _documents.get(document_id)
    if row is None or row.get("project_id") != ctx.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return DocumentOut.model_validate(row)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    ctx: ProjectContext = Depends(require_project_role(Role.ADMIN)),
):
    row = _documents.get(document_id)
    if row is None or row.get("project_id") != ctx.project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    _documents.update(document_id, {"status": "deleted"})
    _audit.log(
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user.user_id,
        action="document.deleted",
        project_id=ctx.project_id,
        detail={"document_id": document_id},
    )
    return None

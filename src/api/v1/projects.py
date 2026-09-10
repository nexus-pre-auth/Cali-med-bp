"""`/api/v1/projects` endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth.deps import ProjectContext, require_project_role, resolve_org_context
from src.auth.jwt_auth import AuthenticatedUser, get_current_user
from src.auth.roles import Role
from src.api.schemas_v1 import ProjectCreate, ProjectOut, ProjectUpdate
from src.database.repositories_v1 import AuditLogRepository, ProjectRepositoryV1

router = APIRouter(prefix="/projects", tags=["projects"])

_projects = ProjectRepositoryV1()
_audit = AuditLogRepository()


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    user: AuthenticatedUser = Depends(get_current_user),
):
    ctx = await resolve_org_context(payload.organization_id, user, Role.MEMBER)
    row = _projects.insert(
        {
            "name": payload.name,
            "organization_id": ctx.organization_id,
            "description": payload.description,
            "occupancy_type": payload.occupancy_type,
            "county": payload.county,
            "city": payload.city,
            "status": "pending",
            "created_by": ctx.user.user_id,
        }
    )
    _audit.log(
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user.user_id,
        action="project.created",
        project_id=row["id"],
    )
    return ProjectOut.model_validate(row)


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    organization_id: str = Query(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    ctx = await resolve_org_context(organization_id, user, Role.VIEWER)
    rows = _projects.list_for_org(ctx.organization_id)
    return [ProjectOut.model_validate(r) for r in rows]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(ctx: ProjectContext = Depends(require_project_role(Role.VIEWER))):
    return ProjectOut.model_validate(ctx.project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    payload: ProjectUpdate,
    ctx: ProjectContext = Depends(require_project_role(Role.ADMIN)),
):
    patch = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not patch:
        return ProjectOut.model_validate(ctx.project)
    updated = _projects.update(ctx.project_id, patch)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    _audit.log(
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user.user_id,
        action="project.updated",
        project_id=ctx.project_id,
        detail=patch,
    )
    return ProjectOut.model_validate(updated)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(ctx: ProjectContext = Depends(require_project_role(Role.OWNER))):
    _projects.delete(ctx.project_id)
    _audit.log(
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user.user_id,
        action="project.deleted",
        project_id=ctx.project_id,
    )
    return None

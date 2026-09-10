"""
FastAPI dependencies enforcing organization/project membership and
role-based access for the `/api/v1` SaaS API.

These dependencies resolve membership via the repository layer (Supabase or
local-store fallback — see `src/database/repositories_v1.py`), so tenant
isolation is enforced at the application layer in addition to Postgres Row
Level Security when Supabase is configured (defense in depth).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Path, status

from src.auth.jwt_auth import AuthenticatedUser, get_current_user
from src.auth.roles import Role, role_at_least
from src.database.repositories_v1 import (
    MembershipRepository,
    ProjectMemberRepository,
    ProjectRepositoryV1,
)

_membership_repo = MembershipRepository()
_project_member_repo = ProjectMemberRepository()
_project_repo = ProjectRepositoryV1()


class OrgContext:
    """The authenticated user's resolved role within an organization."""

    def __init__(self, user: AuthenticatedUser, organization_id: str, role: str) -> None:
        self.user = user
        self.organization_id = organization_id
        self.role = role


class ProjectContext:
    """The authenticated user's resolved role within a project."""

    def __init__(self, user: AuthenticatedUser, project: dict, role: str) -> None:
        self.user = user
        self.project = project
        self.project_id = project["id"]
        self.organization_id = project.get("organization_id")
        self.role = role


def require_org_role(minimum: Role):
    """Dependency factory: require membership in `organization_id` path param
    with at least `minimum` role."""

    async def _dep(
        organization_id: str = Path(...),
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> OrgContext:
        return await resolve_org_context(organization_id, user, minimum)

    return _dep


async def resolve_org_context(organization_id: str, user: AuthenticatedUser, minimum: Role) -> OrgContext:
    """Plain (non-path-bound) organization membership/role check.

    Used directly by endpoints where the organization id is supplied in the
    request body or as a query parameter rather than the URL path (e.g.
    `POST /projects`, which creates a project *within* an organization_id
    given in the request body).
    """
    role = _membership_repo.get_role(organization_id, user.user_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    if not role_at_least(role, minimum):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have sufficient permissions for this action.",
        )
    return OrgContext(user, organization_id, role)


def _resolve_project_role(user: AuthenticatedUser, project: dict) -> str | None:
    """A user's effective role on a project is the more privileged of their
    direct project membership (if any) and their organization membership."""
    from src.auth.roles import role_rank

    roles = []
    project_role = _project_member_repo.get_role(project["id"], user.user_id)
    if project_role:
        roles.append(project_role)
    org_id = project.get("organization_id")
    if org_id:
        org_role = _membership_repo.get_role(org_id, user.user_id)
        if org_role:
            roles.append(org_role)
    if not roles:
        return None
    return max(roles, key=role_rank)


def require_project_role(minimum: Role):
    """Dependency factory: require access to `project_id` path param with at
    least `minimum` role, via direct project membership or org membership."""

    async def _dep(
        project_id: str = Path(...),
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> ProjectContext:
        project = _project_repo.get(project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

        role = _resolve_project_role(user, project)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        if not role_at_least(role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have sufficient permissions for this action.",
            )
        return ProjectContext(user, project, role)

    return _dep

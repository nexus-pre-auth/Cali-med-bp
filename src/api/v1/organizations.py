"""`/api/v1/organizations` endpoints — minimal org/membership bootstrap.

The core Phase 3 SaaS resources (projects/documents/analyses/findings/
reports/revisions) are always accessed within an organization context.
This module provides the minimum viable organization lifecycle so a new
authenticated user can create an organization (becoming its OWNER) and
list the organizations they belong to. Full member-invitation workflows
(inviting other users by email, changing another user's role) are
intentionally out of scope for this MVP and are called out in the README
as a remaining gap.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status

from src.auth.jwt_auth import AuthenticatedUser, get_current_user
from src.api.schemas_v1 import OrganizationCreate, OrganizationOut
from src.database.repositories_v1 import MembershipRepository, OrganizationRepository

router = APIRouter(prefix="/organizations", tags=["organizations"])

_organizations = OrganizationRepository()
_memberships = MembershipRepository()


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    user: AuthenticatedUser = Depends(get_current_user),
):
    org = _organizations.insert({"name": payload.name, "created_by": user.user_id, "is_active": True})
    _memberships.insert({"organization_id": org["id"], "user_id": user.user_id, "role": "OWNER"})
    return OrganizationOut.model_validate(org)


@router.get("", response_model=List[OrganizationOut])
async def list_my_organizations(user: AuthenticatedUser = Depends(get_current_user)):
    my_memberships = _memberships.list_for_user(user.user_id)
    orgs = []
    for m in my_memberships:
        org = _organizations.get(m["organization_id"])
        if org:
            orgs.append(org)
    return [OrganizationOut.model_validate(o) for o in orgs]

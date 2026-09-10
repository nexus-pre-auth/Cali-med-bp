"""Role model for organization/project membership.

Roles are ordered from most to least privileged. `role_at_least` is used by
FastAPI dependencies to gate endpoints behind a minimum required role.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    REVIEWER = "REVIEWER"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


# Higher number == more privileged.
_ROLE_RANK = {
    Role.VIEWER: 0,
    Role.MEMBER: 1,
    Role.REVIEWER: 2,
    Role.ADMIN: 3,
    Role.OWNER: 4,
}


def role_rank(role: str) -> int:
    try:
        return _ROLE_RANK[Role(role)]
    except (ValueError, KeyError):
        return -1


def role_at_least(role: str, minimum: Role) -> bool:
    """Return True if `role` meets or exceeds `minimum` in privilege."""
    return role_rank(role) >= _ROLE_RANK[minimum]

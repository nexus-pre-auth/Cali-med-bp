"""
Auth middleware — validates Supabase JWT and returns the current firm.

Usage in an endpoint:
    from src.api.auth import require_auth, CurrentFirm
    @router.post("/review")
    async def run_review(firm: CurrentFirm = Depends(require_auth)):
        ...
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import config

_bearer = HTTPBearer(auto_error=False)


def _decode_jwt(token: str) -> dict:
    """Verify and decode a Supabase-issued JWT."""
    try:
        from jose import jwt, JWTError
        payload = jwt.decode(
            token,
            config.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def _get_supabase():
    """Return a Supabase client (service role — bypasses RLS for firm look-ups)."""
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


class FirmContext:
    """Resolved caller identity: Supabase user_id + firms row."""

    def __init__(self, user_id: str, firm: Optional[dict]):
        self.user_id = user_id
        self.firm = firm  # None if the user hasn't completed onboarding

    @property
    def firm_id(self) -> Optional[str]:
        return self.firm["id"] if self.firm else None

    @property
    def can_review(self) -> bool:
        """True when the firm has credits or an active subscription."""
        if not self.firm:
            return False
        limit = self.firm.get("reviews_limit", 0)
        if limit == -1:
            return True
        used = self.firm.get("reviews_used", 0)
        return used < limit

    @property
    def is_subscribed(self) -> bool:
        return bool(self.firm and self.firm.get("stripe_subscription_id"))


async def require_auth(
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)],
) -> FirmContext:
    """FastAPI dependency — raises 401 if no valid token, 403 if no firm record."""
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = _decode_jwt(creds.credentials)
    user_id: str = payload.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
        sb = _get_supabase()
        result = sb.table("firms").select("*").eq("user_id", user_id).maybe_single().execute()
        firm = result.data if result else None
    else:
        firm = None  # Dev/test: no Supabase configured

    return FirmContext(user_id=user_id, firm=firm)


async def optional_auth(
    creds: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)],
) -> Optional[FirmContext]:
    """Like require_auth but returns None instead of raising for unauthenticated requests."""
    if not creds:
        return None
    try:
        return await require_auth(creds)
    except HTTPException:
        return None


# Type alias for use in endpoint signatures
CurrentFirm = Annotated[FirmContext, Depends(require_auth)]
OptionalFirm = Annotated[Optional[FirmContext], Depends(optional_auth)]

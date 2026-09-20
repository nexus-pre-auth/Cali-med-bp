"""
Firms endpoints — onboarding and profile management.

POST /firms/onboard    Create or update the caller's firm profile
GET  /firms/me         Return current firm profile + billing status
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

import config
from src.api.auth import CurrentFirm

firms_router = APIRouter(prefix="/firms", tags=["firms"])


class OnboardRequest(BaseModel):
    name: str
    contact_email: Optional[str] = None
    state: Optional[str] = None          # 2-letter state code
    license_number: Optional[str] = None


class FirmProfile(BaseModel):
    id: str
    name: str
    contact_email: Optional[str]
    state: Optional[str]
    tier: str
    reviews_used: int
    reviews_limit: int
    can_review: bool
    is_subscribed: bool


def _supabase():
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


@firms_router.post("/onboard", response_model=FirmProfile, status_code=status.HTTP_201_CREATED)
async def onboard(body: OnboardRequest, firm_ctx: CurrentFirm):
    """
    Create or update the firm record for the authenticated user.
    Called once after Supabase Auth sign-up and before any review.
    """
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY):
        raise HTTPException(status_code=503, detail="Supabase not configured")

    sb = _supabase()

    if firm_ctx.firm:
        # Update existing firm
        result = sb.table("firms").update({
            "name": body.name,
            "contact_email": body.contact_email,
            "state": body.state,
            "license_number": body.license_number,
        }).eq("id", firm_ctx.firm_id).execute()
        firm = result.data[0] if result.data else firm_ctx.firm
    else:
        # Create new firm (free tier: 0 credits, user must purchase)
        result = sb.table("firms").insert({
            "user_id": firm_ctx.user_id,
            "name": body.name,
            "contact_email": body.contact_email,
            "state": body.state,
            "license_number": body.license_number,
            "tier": "single",
            "reviews_used": 0,
            "reviews_limit": 0,
        }).execute()
        firm = result.data[0] if result.data else {}

    return FirmProfile(
        id=firm.get("id", ""),
        name=firm.get("name", ""),
        contact_email=firm.get("contact_email"),
        state=firm.get("state"),
        tier=firm.get("tier", "single"),
        reviews_used=firm.get("reviews_used", 0),
        reviews_limit=firm.get("reviews_limit", 0),
        can_review=firm_ctx.can_review,
        is_subscribed=firm_ctx.is_subscribed,
    )


@firms_router.get("/me", response_model=FirmProfile)
async def get_me(firm_ctx: CurrentFirm):
    """Return the current user's firm profile."""
    if not firm_ctx.firm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No firm profile found. Call POST /firms/onboard first.",
        )
    firm = firm_ctx.firm
    return FirmProfile(
        id=firm.get("id", ""),
        name=firm.get("name", ""),
        contact_email=firm.get("contact_email"),
        state=firm.get("state"),
        tier=firm.get("tier", "single"),
        reviews_used=firm.get("reviews_used", 0),
        reviews_limit=firm.get("reviews_limit", 0),
        can_review=firm_ctx.can_review,
        is_subscribed=firm_ctx.is_subscribed,
    )

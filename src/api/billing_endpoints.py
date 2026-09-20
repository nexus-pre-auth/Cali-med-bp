"""
Billing endpoints — Stripe Checkout, Customer Portal, and webhook handler.

Endpoints
---------
POST /billing/checkout        Create a Stripe Checkout session (payment or subscription)
POST /billing/portal          Create a Stripe Customer Portal session
GET  /billing/status          Return current firm's subscription / credit status
POST /webhooks/stripe         Handle Stripe webhook events (HMAC-verified)

Environment variables required (set in Railway dashboard):
    STRIPE_SECRET_KEY      sk_live_... or sk_test_...
    STRIPE_WEBHOOK_SECRET  whsec_...
    STRIPE_PRICE_REVIEW    price_... (one-time $299)
    STRIPE_PRICE_MONTHLY   price_... (subscription $499/mo)
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

import config
from src.api.auth import CurrentFirm, OptionalFirm, require_auth

log = logging.getLogger(__name__)

billing_router = APIRouter(prefix="/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])

try:
    import stripe as _stripe
    _stripe.api_key = config.STRIPE_SECRET_KEY
    HAS_STRIPE = bool(config.STRIPE_SECRET_KEY)
except ImportError:
    HAS_STRIPE = False


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    mode: Literal["payment", "subscription"] = "payment"
    # Optionally override the price; defaults to config values
    price_id: Optional[str] = None


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalResponse(BaseModel):
    portal_url: str


class BillingStatus(BaseModel):
    is_subscribed: bool
    can_review: bool
    reviews_used: int
    reviews_limit: int          # -1 = unlimited
    tier: str
    stripe_subscription_id: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _supabase():
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _require_stripe():
    if not HAS_STRIPE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured on this server.",
        )


def _get_or_create_customer(firm: dict, user_email: str) -> str:
    """Return existing Stripe customer id, or create one."""
    if firm.get("stripe_customer_id"):
        return firm["stripe_customer_id"]

    customer = _stripe.Customer.create(
        email=user_email,
        metadata={"firm_id": firm["id"]},
    )
    _supabase().table("firms").update(
        {"stripe_customer_id": customer["id"]}
    ).eq("id", firm["id"]).execute()
    return customer["id"]


# ---------------------------------------------------------------------------
# POST /billing/checkout
# ---------------------------------------------------------------------------

@billing_router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutRequest,
    firm_ctx: CurrentFirm,
):
    """Create a Stripe Checkout session for a one-time review or monthly subscription."""
    _require_stripe()

    if not firm_ctx.firm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Complete your firm profile before purchasing.",
        )

    price_id = body.price_id or (
        config.STRIPE_PRICE_MONTHLY if body.mode == "subscription"
        else config.STRIPE_PRICE_REVIEW
    )
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe price configured for this mode.",
        )

    # Resolve customer email from Supabase Auth
    sb = _supabase()
    user_resp = sb.auth.admin.get_user_by_id(firm_ctx.user_id)
    email = user_resp.user.email if user_resp and user_resp.user else ""

    customer_id = _get_or_create_customer(firm_ctx.firm, email)

    session = _stripe.checkout.Session.create(
        customer=customer_id,
        mode=body.mode,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=config.STRIPE_SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=config.STRIPE_CANCEL_URL,
        metadata={"firm_id": firm_ctx.firm_id, "user_id": firm_ctx.user_id},
        allow_promotion_codes=True,
    )

    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


# ---------------------------------------------------------------------------
# POST /billing/portal
# ---------------------------------------------------------------------------

@billing_router.post("/portal", response_model=PortalResponse)
async def create_portal(firm_ctx: CurrentFirm):
    """Create a Stripe Customer Portal session for subscription management."""
    _require_stripe()

    customer_id = firm_ctx.firm and firm_ctx.firm.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe customer record found.",
        )

    session = _stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=config.STRIPE_SUCCESS_URL,
    )
    return PortalResponse(portal_url=session.url)


# ---------------------------------------------------------------------------
# GET /billing/status
# ---------------------------------------------------------------------------

@billing_router.get("/status", response_model=BillingStatus)
async def billing_status(firm_ctx: CurrentFirm):
    """Return the caller's current billing and credit status."""
    firm = firm_ctx.firm or {}
    return BillingStatus(
        is_subscribed=firm_ctx.is_subscribed,
        can_review=firm_ctx.can_review,
        reviews_used=firm.get("reviews_used", 0),
        reviews_limit=firm.get("reviews_limit", 0),
        tier=firm.get("tier", "single"),
        stripe_subscription_id=firm.get("stripe_subscription_id"),
    )


# ---------------------------------------------------------------------------
# POST /webhooks/stripe
# ---------------------------------------------------------------------------

@webhook_router.post("/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Handle Stripe webhook events.
    Verifies the HMAC signature before processing.
    """
    _require_stripe()

    payload = await request.body()
    try:
        event = _stripe.Webhook.construct_event(
            payload, stripe_signature, config.STRIPE_WEBHOOK_SECRET
        )
    except _stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    event_type = event["type"]
    data = event["data"]["object"]
    log.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data)

    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        await _handle_subscription_updated(data)

    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data)

    elif event_type == "invoice.payment_failed":
        log.warning("Payment failed for customer %s", data.get("customer"))

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Webhook event handlers
# ---------------------------------------------------------------------------

async def _handle_checkout_completed(session: dict) -> None:
    firm_id = session.get("metadata", {}).get("firm_id")
    mode = session.get("mode")

    if not firm_id:
        log.warning("checkout.session.completed missing firm_id in metadata")
        return

    sb = _supabase()

    if mode == "payment":
        # One-time review purchase — increment reviews_limit by 1
        result = sb.table("firms").select("reviews_limit").eq("id", firm_id).single().execute()
        current = result.data.get("reviews_limit", 0) if result.data else 0
        new_limit = current + 1 if current != -1 else -1
        sb.table("firms").update({
            "reviews_limit": new_limit,
            "stripe_customer_id": session.get("customer"),
        }).eq("id", firm_id).execute()
        log.info("Firm %s: +1 review credit (total %s)", firm_id, new_limit)

    elif mode == "subscription":
        # Subscription — unlimited reviews, set tier
        sb.table("firms").update({
            "stripe_subscription_id": session.get("subscription"),
            "stripe_customer_id": session.get("customer"),
            "tier": "studio",
            "reviews_limit": -1,
        }).eq("id", firm_id).execute()
        log.info("Firm %s: subscription activated", firm_id)


async def _handle_subscription_updated(subscription: dict) -> None:
    customer_id = subscription.get("customer")
    active = subscription.get("status") in ("active", "trialing")

    sb = _supabase()
    result = sb.table("firms").select("id").eq("stripe_customer_id", customer_id).maybe_single().execute()
    if not result or not result.data:
        return

    firm_id = result.data["id"]
    sb.table("firms").update({
        "stripe_subscription_id": subscription["id"] if active else None,
        "tier": "studio" if active else "single",
        "reviews_limit": -1 if active else 0,
        "is_active": active,
    }).eq("id", firm_id).execute()
    log.info("Firm %s: subscription %s → %s", firm_id, subscription["id"], subscription["status"])


async def _handle_subscription_deleted(subscription: dict) -> None:
    customer_id = subscription.get("customer")
    sb = _supabase()
    result = sb.table("firms").select("id").eq("stripe_customer_id", customer_id).maybe_single().execute()
    if not result or not result.data:
        return
    firm_id = result.data["id"]
    sb.table("firms").update({
        "stripe_subscription_id": None,
        "tier": "single",
        "reviews_limit": 0,
    }).eq("id", firm_id).execute()
    log.info("Firm %s: subscription cancelled", firm_id)

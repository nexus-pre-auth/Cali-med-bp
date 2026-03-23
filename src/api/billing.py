"""
Stripe billing integration for HCAI Compliance Reports.

Flow
----
1. POST /checkout/create  — user submits form
   - Saves uploaded file to temp dir
   - Creates Stripe Checkout session ($49)
   - Stores { stripe_session_id → PendingOrder } in memory
   - Returns { checkout_url, job_id }

2. POST /checkout/webhook  — Stripe fires after payment
   - Verifies Stripe signature
   - Retrieves PendingOrder by session_id
   - Creates and starts the background review job
   - Stores { session_id → job_id } for /checkout/status lookup

3. GET /checkout/status?session_id=X  — frontend polls after redirect
   - Returns { paid: bool, job_id: str | None }

Dev mode
--------
If STRIPE_SECRET_KEY is not set, /checkout/create skips payment,
creates the job immediately, and returns { checkout_url: null, job_id }.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import UUID

from src.monitoring.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config — read from environment
# ---------------------------------------------------------------------------

STRIPE_SECRET_KEY      = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID        = os.getenv("STRIPE_PRICE_ID", "")   # Recurring subscription
REPORT_PRICE_CENTS     = int(os.getenv("REPORT_PRICE_CENTS", "4900"))  # $49.00
REPORT_PRICE_NAME      = os.getenv("REPORT_PRICE_NAME", "BlueprintIQ Compliance Report")
SUCCESS_URL_BASE       = os.getenv("APP_BASE_URL", "http://localhost:8000")

_stripe_available = False
try:
    import stripe as _stripe
    _stripe_available = True
except ImportError:
    log.warning("stripe package not installed — billing disabled. Run: pip install stripe")


# ---------------------------------------------------------------------------
# In-memory order tracking  (survives for the life of the process)
# ---------------------------------------------------------------------------

@dataclass
class PendingOrder:
    job_id: str
    project_name: str
    customer_email: str
    temp_file_path: Optional[str]
    pasted_text: Optional[str]
    session_id: str

_pending: dict[str, PendingOrder] = {}     # session_id → PendingOrder
_completed: dict[str, str] = {}            # session_id → job_id
_lock = threading.Lock()


def _store_pending(order: PendingOrder) -> None:
    with _lock:
        _pending[order.session_id] = order


def _pop_pending(session_id: str) -> Optional[PendingOrder]:
    with _lock:
        return _pending.pop(session_id, None)


def _mark_completed(session_id: str, job_id: str) -> None:
    with _lock:
        _completed[session_id] = job_id


def lookup_job_for_session(session_id: str) -> Optional[str]:
    with _lock:
        return _completed.get(session_id)


# ---------------------------------------------------------------------------
# Checkout session creation
# ---------------------------------------------------------------------------

def create_checkout_session(
    job_id: str,
    project_name: str,
    customer_email: str,
    temp_file_path: Optional[str],
    pasted_text: Optional[str],
) -> Optional[str]:
    """
    Create a Stripe Checkout session for one $49 report.

    Returns the checkout URL, or None if Stripe is not configured
    (dev mode — caller should start job directly).
    """
    if not _stripe_available or not STRIPE_SECRET_KEY:
        log.info("Stripe not configured — running in dev mode (no payment required).")
        return None

    _stripe.api_key = STRIPE_SECRET_KEY

    success_url = f"{SUCCESS_URL_BASE}/?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url  = f"{SUCCESS_URL_BASE}/"

    # Build line items — use explicit price_id if provided, else ad-hoc price
    if STRIPE_PRICE_ID:
        line_items = [{"price": STRIPE_PRICE_ID, "quantity": 1}]
    else:
        line_items = [{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": REPORT_PRICE_NAME},
                "unit_amount": REPORT_PRICE_CENTS,
            },
            "quantity": 1,
        }]

    session = _stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        customer_email=customer_email,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"job_id": job_id, "project_name": project_name},
    )

    order = PendingOrder(
        job_id=job_id,
        project_name=project_name,
        customer_email=customer_email,
        temp_file_path=temp_file_path,
        pasted_text=pasted_text,
        session_id=session.id,
    )
    _store_pending(order)

    log.info("Stripe Checkout session %s created for job %s", session.id, job_id)
    return session.url


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------

def handle_webhook(payload: bytes, sig_header: str) -> Optional[PendingOrder]:
    """
    Validate and process a Stripe webhook event.

    Returns the PendingOrder if this is a successful checkout.session.completed
    event, so the caller can start the review job.  Returns None otherwise.
    """
    if not _stripe_available or not STRIPE_SECRET_KEY:
        return None

    _stripe.api_key = STRIPE_SECRET_KEY

    try:
        if STRIPE_WEBHOOK_SECRET:
            event = _stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        else:
            import json
            event = _stripe.Event.construct_from(json.loads(payload), _stripe.api_key)
    except Exception as e:
        log.warning("Webhook signature verification failed: %s", e)
        return None

    if event["type"] != "checkout.session.completed":
        return None

    session_id = event["data"]["object"]["id"]
    order = _pop_pending(session_id)
    if not order:
        log.warning("Webhook for unknown session %s — may have already been processed.", session_id)
        return None

    _mark_completed(session_id, order.job_id)
    log.info("Payment confirmed for job %s (session %s)", order.job_id, session_id)
    return order

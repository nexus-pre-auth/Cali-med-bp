"""
Auth routes — register, login, token refresh, user profile.

Endpoints:
  POST /auth/register  — create account, return JWT
  POST /auth/login     — verify credentials, return JWT
  GET  /auth/me        — return current user from JWT
  POST /auth/upgrade   — create Stripe subscription checkout session
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, field_validator

import config
from src.db.user_store import get_user_store
from src.monitoring.logger import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""
    company: str = ""

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UpgradeRequest(BaseModel):
    plan: str  # "pro" | "agency"
    success_url: str
    cancel_url: str


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _make_token(user: dict) -> str:
    expire = datetime.now(UTC) + timedelta(days=config.JWT_EXPIRE_DAYS)
    payload = {
        "sub":   user["id"],
        "email": user["email"],
        "plan":  user.get("plan", "free"),
        "exp":   expire,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# FastAPI dependency — optional auth (returns None if no token provided)
# ---------------------------------------------------------------------------

def optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict | None:
    """
    Dependency that returns the current user dict if a valid Bearer token is
    present, or None for anonymous / API-key requests.
    """
    if not credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        store = get_user_store()
        return store.get_by_id(payload["sub"])
    except HTTPException:
        return None


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Dependency that requires a valid Bearer token; raises 401 otherwise."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    store = get_user_store()
    user = store.get_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/register", response_model=TokenResponse, status_code=201)
def register(req: RegisterRequest) -> TokenResponse:
    """Create a new account. Returns a JWT on success."""
    store = get_user_store()
    try:
        user = store.create(
            email=req.email,
            password=req.password,
            full_name=req.full_name,
            company=req.company,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    token = _make_token(user)
    log.info("Registered new user: %s", req.email)
    return TokenResponse(access_token=token, user=user)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest) -> TokenResponse:
    """Authenticate and return a JWT."""
    store = get_user_store()
    user = store.verify_password(req.email, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = _make_token(user)
    log.info("User logged in: %s", req.email)
    return TokenResponse(access_token=token, user=user)


@router.get("/me")
def me(user: dict = Depends(require_user)) -> dict:
    """Return the authenticated user's profile."""
    return user


@router.post("/upgrade")
def upgrade(req: UpgradeRequest, user: dict = Depends(require_user)) -> dict:
    """
    Create a Stripe Checkout session for plan upgrade.
    Returns {checkout_url} for the frontend to redirect to.
    """
    plan = req.plan.lower()
    if plan not in ("pro", "agency"):
        raise HTTPException(status_code=400, detail="Plan must be 'pro' or 'agency'")

    price_id = config.STRIPE_PRO_PRICE_ID if plan == "pro" else config.STRIPE_AGENCY_PRICE_ID
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"Stripe price ID for '{plan}' plan not configured",
        )

    stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not stripe_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    import stripe
    stripe.api_key = stripe_key

    # Reuse existing Stripe customer if available
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        customer = stripe.Customer.create(
            email=user["email"],
            name=user.get("full_name") or user["email"],
            metadata={"user_id": user["id"], "plan": plan},
        )
        customer_id = customer.id
        get_user_store().set_plan(user["id"], user.get("plan", "free"), customer_id)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=req.success_url + "?upgraded={CHECKOUT_SESSION_ID}",
        cancel_url=req.cancel_url,
        metadata={"user_id": user["id"], "plan": plan},
    )
    return {"checkout_url": session.url, "session_id": session.id}

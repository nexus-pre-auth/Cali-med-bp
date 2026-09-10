"""
API security primitives: authentication, admin authorization, rate limiting,
and safe error handling for the FastAPI app.

Design:
  - Standard endpoints require a bearer token matching one of the tokens in
    the `API_AUTH_TOKENS` environment variable (comma-separated).
  - Administrative endpoints (e.g. model retraining) additionally require a
    token matching `API_ADMIN_TOKENS`.
  - If no tokens are configured at all, the API refuses to start in a
    "production" environment (ENVIRONMENT=production) to avoid accidentally
    deploying an unauthenticated instance. In local/dev mode (default),
    auth is enforced only if tokens are configured, to keep `main.py serve`
    usable out of the box for local development.

This is intentionally a lightweight token-based scheme rather than a full
Supabase-JWT verification layer, since no frontend session/login flow exists
yet in this repository. It is designed to be swapped for Supabase JWT
verification (validating the `Authorization` bearer token against Supabase's
JWKS) without changing call sites — see `verify_supabase_jwt` stub below.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("hcai.security")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"

_bearer_scheme = HTTPBearer(auto_error=False)


def _tokens_from_env(var_name: str) -> set[str]:
    raw = os.getenv(var_name, "")
    return {t.strip() for t in raw.split(",") if t.strip()}


def get_auth_tokens() -> set[str]:
    return _tokens_from_env("API_AUTH_TOKENS")


def get_admin_tokens() -> set[str]:
    return _tokens_from_env("API_ADMIN_TOKENS")


async def require_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """
    Require a valid bearer token for standard authenticated endpoints.

    Any token listed in API_AUTH_TOKENS or API_ADMIN_TOKENS is accepted
    (admin tokens are a superset of standard access).
    """
    valid_tokens = get_auth_tokens() | get_admin_tokens()

    if not valid_tokens:
        if IS_PRODUCTION:
            # Fail closed: never allow an unauthenticated production deployment.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API authentication is not configured on this server.",
            )
        # Local/dev convenience: no tokens configured, allow access but log it.
        logger.warning("No API_AUTH_TOKENS configured; allowing unauthenticated request (dev mode).")
        return "dev-mode-no-auth"

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials not in valid_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


async def require_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Require a bearer token present in API_ADMIN_TOKENS (administrative access)."""
    admin_tokens = get_admin_tokens()

    if not admin_tokens:
        if IS_PRODUCTION:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Administrative API authentication is not configured on this server.",
            )
        logger.warning("No API_ADMIN_TOKENS configured; allowing unauthenticated admin request (dev mode).")
        return "dev-mode-no-admin-auth"

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials not in admin_tokens:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires administrative privileges.",
        )

    return credentials.credentials


# ---------------------------------------------------------------------------
# Simple in-memory rate limiter (per-client-IP, sliding window).
#
# This is intentionally dependency-free (no Redis/slowapi) so it works in a
# single-process deployment. It is NOT sufficient for a multi-instance
# horizontally-scaled deployment — a shared store (Redis) should replace it
# before scaling beyond one process.
# ---------------------------------------------------------------------------

_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
_RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "30"))

_request_log: Dict[str, Deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{client_ip}:{request.url.path}"


async def rate_limit(request: Request) -> None:
    """FastAPI dependency enforcing a per-IP+path sliding window rate limit."""
    key = _client_key(request)
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS

    log = _request_log[key]
    while log and log[0] < window_start:
        log.popleft()

    if len(log) >= _RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down and try again shortly.",
        )

    log.append(now)

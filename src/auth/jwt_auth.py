"""
Supabase JWT verification.

Supabase issues HS256-signed JWTs (for the legacy JWT secret model) or
RS256/ES256-signed JWTs validated against a JWKS endpoint (for the newer
"asymmetric JWT" project setting). This module supports the widely-used
HS256 shared-secret model via `SUPABASE_JWT_SECRET`, which is what Supabase
exposes under Project Settings -> API -> JWT Settings for most projects.

Design (fail closed):
  - If `SUPABASE_JWT_SECRET` is not configured, the server cannot safely
    verify any bearer token, so every `/api/v1` request is rejected with
    503 (service misconfigured) regardless of environment. There is no
    "dev bypass" here — unlike the legacy static-token scheme in
    `src/api/security.py`, silently accepting unverified JWTs would be a
    real vulnerability (anyone could mint an unsigned token claiming to be
    any user).
  - If the secret *is* configured, tokens are fully verified: signature,
    expiry, and (optionally) audience/issuer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)


def _jwt_secret() -> str:
    return os.getenv("SUPABASE_JWT_SECRET", "")


def _expected_audience() -> Optional[str]:
    return os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated") or None


@dataclass(frozen=True)
class AuthenticatedUser:
    """The authenticated identity of the caller, derived from a verified JWT."""

    user_id: str
    email: Optional[str]
    role_claim: Optional[str]
    claims: Dict[str, Any]


def decode_supabase_jwt(token: str) -> Dict[str, Any]:
    """Verify and decode a Supabase-issued access token.

    Raises HTTPException(401) on any validation failure and
    HTTPException(503) if the server has no JWT secret configured.
    """
    secret = _jwt_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured on this server (SUPABASE_JWT_SECRET missing).",
        )

    try:
        options = {"require": ["exp", "sub"]}
        kwargs: Dict[str, Any] = {"algorithms": ["HS256"], "options": options}
        audience = _expected_audience()
        if audience:
            kwargs["audience"] = audience
        claims = jwt.decode(token, secret, **kwargs)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not claims.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token missing subject claim.",
        )

    return claims


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """FastAPI dependency: resolve the authenticated user from a bearer JWT."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = decode_supabase_jwt(credentials.credentials)
    return AuthenticatedUser(
        user_id=str(claims["sub"]),
        email=claims.get("email"),
        role_claim=claims.get("role"),
        claims=claims,
    )

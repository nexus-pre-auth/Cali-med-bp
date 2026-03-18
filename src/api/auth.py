"""
API Key authentication middleware.

Keys are configured via the API_KEYS environment variable as a
comma-separated list:

    API_KEYS=key-abc123,key-def456

If API_KEYS is empty/unset, authentication is disabled (development mode).
A warning is logged on startup.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from src.monitoring.logger import get_logger

log = get_logger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _load_keys() -> set[str]:
    raw = os.getenv("API_KEYS", "").strip()
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


_VALID_KEYS: set[str] = _load_keys()

if not _VALID_KEYS:
    log.warning(
        "API_KEYS not set — authentication is DISABLED. "
        "Set API_KEYS=key1,key2 in .env for production."
    )


async def require_api_key(api_key: Optional[str] = Security(_API_KEY_HEADER)) -> str:
    """
    FastAPI dependency. Validates X-API-Key header.
    Pass-through when no keys are configured (dev mode).
    """
    if not _VALID_KEYS:
        return "dev-mode"

    if not api_key or api_key not in _VALID_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide X-API-Key header.",
        )
    return api_key

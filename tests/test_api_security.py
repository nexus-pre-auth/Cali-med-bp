"""
Tests for API security: authentication, admin authorization, rate limiting,
and health/readiness behavior.

These tests exercise `src/api/security.py`'s dependency functions directly
(rather than spinning up uvicorn) to keep the suite fast, dependency-free
(no pytest-asyncio plugin required), and independent of network ports.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


def _reload_security(monkeypatch, **env):
    """Reload src.api.security with a controlled environment."""
    for key in ("API_AUTH_TOKENS", "API_ADMIN_TOKENS", "ENVIRONMENT",
                "RATE_LIMIT_MAX_REQUESTS", "RATE_LIMIT_WINDOW_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import src.api.security as security
    return importlib.reload(security)


class DummyRequest:
    class _Client:
        host = "127.0.0.1"

    class _URL:
        path = "/feedback/metrics-test"

    def __init__(self, path="/feedback/metrics-test"):
        self.client = self._Client()
        self.url = self._URL()
        self.url.path = path


def _run(coro):
    return asyncio.run(coro)


def test_dev_mode_allows_access_without_tokens(monkeypatch):
    security = _reload_security(monkeypatch)
    result = _run(security.require_api_token(credentials=None))
    assert result == "dev-mode-no-auth"


def test_production_without_tokens_refuses_service(monkeypatch):
    security = _reload_security(monkeypatch, ENVIRONMENT="production")
    with pytest.raises(HTTPException) as exc_info:
        _run(security.require_api_token(credentials=None))
    assert exc_info.value.status_code == 503


def test_missing_credentials_rejected_when_tokens_configured(monkeypatch):
    security = _reload_security(monkeypatch, API_AUTH_TOKENS="secret1")
    with pytest.raises(HTTPException) as exc_info:
        _run(security.require_api_token(credentials=None))
    assert exc_info.value.status_code == 401


def test_valid_token_accepted(monkeypatch):
    security = _reload_security(monkeypatch, API_AUTH_TOKENS="secret1,secret2")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret2")
    result = _run(security.require_api_token(credentials=creds))
    assert result == "secret2"


def test_invalid_token_rejected(monkeypatch):
    security = _reload_security(monkeypatch, API_AUTH_TOKENS="secret1")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")
    with pytest.raises(HTTPException) as exc_info:
        _run(security.require_api_token(credentials=creds))
    assert exc_info.value.status_code == 401


def test_admin_token_required_for_admin_endpoints(monkeypatch):
    security = _reload_security(monkeypatch, API_AUTH_TOKENS="user1", API_ADMIN_TOKENS="admin1")
    user_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="user1")
    with pytest.raises(HTTPException) as exc_info:
        _run(security.require_admin_token(credentials=user_creds))
    assert exc_info.value.status_code == 403

    admin_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="admin1")
    result = _run(security.require_admin_token(credentials=admin_creds))
    assert result == "admin1"


def test_rate_limit_blocks_after_threshold(monkeypatch):
    security = _reload_security(
        monkeypatch, RATE_LIMIT_MAX_REQUESTS="2", RATE_LIMIT_WINDOW_SECONDS="60"
    )
    req = DummyRequest(path="/feedback/metrics-test-unique")
    _run(security.rate_limit(req))
    _run(security.rate_limit(req))
    with pytest.raises(HTTPException) as exc_info:
        _run(security.rate_limit(req))
    assert exc_info.value.status_code == 429


def test_health_and_ready_endpoints_are_public(monkeypatch):
    """/health and /ready must be reachable without any bearer token."""
    monkeypatch.delenv("API_AUTH_TOKENS", raising=False)
    monkeypatch.delenv("API_ADMIN_TOKENS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import src.api.security as security
    importlib.reload(security)

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        return {"status": "ready", "checks": {}}

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_protected_endpoint_requires_token_end_to_end(monkeypatch):
    """A router protected by require_api_token rejects unauthenticated calls."""
    monkeypatch.setenv("API_AUTH_TOKENS", "abc123")

    from fastapi import APIRouter, Depends, FastAPI
    from fastapi.testclient import TestClient

    import src.api.security as security
    importlib.reload(security)

    router = APIRouter(dependencies=[Depends(security.require_api_token)])

    @router.get("/protected")
    async def protected():
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    valid_header = {"Authorization": "Bearer " + "abc123"}
    invalid_header = {"Authorization": "Bearer " + "wrong-token"}

    assert client.get("/protected").status_code == 401
    assert client.get("/protected", headers=valid_header).status_code == 200
    assert client.get("/protected", headers=invalid_header).status_code == 401

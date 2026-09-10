"""
Shared pytest fixtures for `/api/v1` SaaS API tests.

Provides:
  - `app_client`: a FastAPI TestClient wired the same way as `main.py`'s
    `serve` command (v1 router + JWT auth), backed by a fresh, isolated
    LocalStore per test so tests never share state.
  - `make_token`: mint a Supabase-shaped JWT signed with a fixed test
    secret, for a given user id / email / role claim.
"""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_JWT_SECRET = "unit-test-jwt-secret-do-not-use-in-production"


@pytest.fixture()
def local_store(tmp_path, monkeypatch):
    """Give each test a fresh, isolated JSON-file-backed local store."""
    from src.database import local_store as ls

    store = ls.reset_local_store(tmp_path / "saas")
    yield store


@pytest.fixture()
def app_client(monkeypatch, local_store, tmp_path):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)

    # Reset the Supabase client singleton so the env changes above (no
    # SUPABASE_URL) actually take effect for this test.
    from src.database import client as db_client
    db_client.reset_client()

    from src.api.v1.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)

    with TestClient(app) as client:
        yield client


def make_token(user_id: str | None = None, email: str = "user@example.com", role: str = "authenticated", exp_delta: int = 3600) -> str:
    user_id = user_id or str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "aud": "authenticated",
        "exp": int(time.time()) + exp_delta,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


def auth_header(token: str) -> dict:
    return {"Authorization": "Bearer " + token}

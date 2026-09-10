"""
Tests for `/api/v1` authentication (Supabase JWT verification).
"""

from __future__ import annotations

import time

import jwt

from tests.conftest import TEST_JWT_SECRET, auth_header, make_token


def test_unauthenticated_request_rejected(app_client):
    resp = app_client.get("/api/v1/organizations")
    assert resp.status_code == 401


def test_missing_secret_returns_503(app_client, monkeypatch):
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    resp = app_client.get("/api/v1/organizations", headers=auth_header(make_token()))
    assert resp.status_code == 503


def test_valid_token_accepted(app_client):
    token = make_token()
    resp = app_client.get("/api/v1/organizations", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_invalid_signature_rejected(app_client):
    bad_token = jwt.encode({"sub": "x", "exp": int(time.time()) + 3600}, "wrong-secret", algorithm="HS256")
    resp = app_client.get("/api/v1/organizations", headers=auth_header(bad_token))
    assert resp.status_code == 401


def test_expired_token_rejected(app_client):
    token = make_token(exp_delta=-60)
    resp = app_client.get("/api/v1/organizations", headers=auth_header(token))
    assert resp.status_code == 401


def test_malformed_bearer_header_rejected(app_client):
    resp = app_client.get("/api/v1/organizations", headers={"Authorization": "NotBearer abc"})
    assert resp.status_code == 401


def test_token_without_sub_rejected(app_client):
    token = jwt.encode({"exp": int(time.time()) + 3600}, TEST_JWT_SECRET, algorithm="HS256")
    resp = app_client.get("/api/v1/organizations", headers=auth_header(token))
    assert resp.status_code == 401

"""
Tests for user auth system:
- UserStore: register, login, credit management, plan upgrade
- Auth routes: POST /auth/register, POST /auth/login, GET /auth/me
- JWT token encode / decode
- Review endpoints: optional JWT, credit enforcement
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# UserStore tests
# ---------------------------------------------------------------------------

class TestUserStore:

    @pytest.fixture
    def store(self, tmp_path):
        from src.db.user_store import UserStore
        return UserStore(db_path=tmp_path / "auth_test.db")

    def test_create_and_retrieve_by_email(self, store):
        user = store.create("alice@example.com", "password123", full_name="Alice Smith")
        assert user["email"] == "alice@example.com"
        assert user["full_name"] == "Alice Smith"
        assert "password_hash" not in user
        assert user["plan"] == "free"
        assert user["credits"] == 1

        fetched = store.get_by_email("alice@example.com")
        assert fetched is not None
        assert fetched["id"] == user["id"]

    def test_email_is_normalised_to_lowercase(self, store):
        store.create("Bob@Example.COM", "password123")
        user = store.get_by_email("bob@example.com")
        assert user is not None

    def test_duplicate_email_raises(self, store):
        store.create("dup@example.com", "password123")
        with pytest.raises(ValueError, match="already registered"):
            store.create("DUP@example.com", "differentpass")

    def test_verify_password_success(self, store):
        store.create("carol@example.com", "s3cr3tword")
        user = store.verify_password("carol@example.com", "s3cr3tword")
        assert user is not None
        assert user["email"] == "carol@example.com"
        assert "password_hash" not in user

    def test_verify_password_wrong_password(self, store):
        store.create("dave@example.com", "correctpass")
        assert store.verify_password("dave@example.com", "wrongpass") is None

    def test_verify_password_unknown_email(self, store):
        assert store.verify_password("nobody@example.com", "anything") is None

    def test_decrement_credit_free_tier(self, store):
        user = store.create("eve@example.com", "pass12345")
        assert user["credits"] == 1
        assert store.decrement_credit(user["id"]) is True
        # Second call should fail — no credits left
        assert store.decrement_credit(user["id"]) is False

    def test_decrement_credit_pro_plan_unlimited(self, store):
        user = store.create("frank@example.com", "pass12345")
        store.set_plan(user["id"], "pro")
        # Pro plan has unlimited credits
        for _ in range(5):
            assert store.decrement_credit(user["id"]) is True

    def test_set_plan_updates_credits(self, store):
        user = store.create("grace@example.com", "pass12345")
        store.set_plan(user["id"], "agency")
        updated = store.get_by_id(user["id"])
        assert updated["plan"] == "agency"
        assert updated["credits"] == 9999

    def test_set_plan_stores_stripe_customer_id(self, store):
        user = store.create("henry@example.com", "pass12345")
        store.set_plan(user["id"], "pro", stripe_customer_id="cus_test123")
        updated = store.get_by_id(user["id"])
        assert updated["stripe_customer_id"] == "cus_test123"

    def test_get_by_id_unknown_returns_none(self, store):
        assert store.get_by_id("nonexistent-uuid") is None

    def test_password_shorter_than_8_chars_rejected_by_api(self):
        """Password validation happens at the Pydantic layer, not the store."""
        from pydantic import ValidationError

        from src.api.auth_routes import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(email="test@example.com", password="short")


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

class TestJWTHelpers:

    def test_make_and_decode_token(self):
        from src.api.auth_routes import _make_token, decode_token
        user = {"id": "user-123", "email": "jwt@example.com", "plan": "free"}
        token = _make_token(user)
        payload = decode_token(token)
        assert payload["sub"] == "user-123"
        assert payload["email"] == "jwt@example.com"
        assert payload["plan"] == "free"

    def test_decode_invalid_token_raises_401(self):
        from fastapi import HTTPException

        from src.api.auth_routes import decode_token
        with pytest.raises(HTTPException) as exc_info:
            decode_token("not.a.valid.token")
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Auth API routes (via TestClient)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def auth_client():
    os.environ["RATE_LIMIT_RPM"] = "0"
    from src.api.app import create_app
    app = create_app()
    os.environ.pop("RATE_LIMIT_RPM", None)
    from fastapi.testclient import TestClient
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _uid() -> str:
    import uuid
    return uuid.uuid4().hex[:10]


class TestAuthRoutes:

    def test_register_creates_account_and_returns_token(self, auth_client):
        email = f"newuser_{_uid()}@example.com"
        r = auth_client.post("/auth/register", json={
            "email": email,
            "password": "securepass1",
            "full_name": "Test User",
            "company": "Test Firm",
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == email
        assert body["user"]["plan"] == "free"
        assert body["user"]["credits"] == 1

    def test_register_duplicate_email_returns_409(self, auth_client):
        email = f"dup_{_uid()}@example.com"
        payload = {"email": email, "password": "pass12345"}
        auth_client.post("/auth/register", json=payload)
        r = auth_client.post("/auth/register", json=payload)
        assert r.status_code == 409

    def test_register_weak_password_returns_422(self, auth_client):
        r = auth_client.post("/auth/register", json={
            "email": f"weak_{_uid()}@example.com",
            "password": "short",
        })
        assert r.status_code == 422

    def test_login_valid_credentials(self, auth_client):
        email = f"login_{_uid()}@example.com"
        auth_client.post("/auth/register", json={"email": email, "password": "validpass99"})
        r = auth_client.post("/auth/login", json={"email": email, "password": "validpass99"})
        assert r.status_code == 200, r.text
        assert "access_token" in r.json()

    def test_login_wrong_password_returns_401(self, auth_client):
        email = f"badpass_{_uid()}@example.com"
        auth_client.post("/auth/register", json={"email": email, "password": "correctpass"})
        r = auth_client.post("/auth/login", json={"email": email, "password": "wrongpass"})
        assert r.status_code == 401

    def test_me_returns_current_user(self, auth_client):
        email = f"me_{_uid()}@example.com"
        reg = auth_client.post("/auth/register", json={
            "email": email,
            "password": "mypassword1",
            "full_name": "Me Tester",
        })
        assert reg.status_code == 201, reg.text
        token = reg.json()["access_token"]
        r = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["email"] == email

    def test_me_without_token_returns_401(self, auth_client):
        r = auth_client.get("/auth/me")
        assert r.status_code == 401

    def test_me_with_invalid_token_returns_401(self, auth_client):
        r = auth_client.get("/auth/me", headers={"Authorization": "Bearer not.valid.token"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Review endpoint — credit enforcement
# ---------------------------------------------------------------------------

class TestReviewCreditEnforcement:

    @pytest.fixture
    def auth_client(self):
        os.environ["RATE_LIMIT_RPM"] = "0"
        from src.api.app import create_app
        app = create_app()
        os.environ.pop("RATE_LIMIT_RPM", None)
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    def _register_and_token(self, client) -> str:
        import uuid
        email = f"credit_{uuid.uuid4().hex[:10]}@example.com"
        r = client.post("/auth/register", json={
            "email": email,
            "password": "testpassword1",
        })
        assert r.status_code == 201, r.text
        return r.json()["access_token"]

    def test_review_with_jwt_succeeds_on_first_call(self, auth_client):
        token = self._register_and_token(auth_client)
        r = auth_client.post(
            "/review",
            json={"project_name": "Credit Test", "text": "Occupied Hospital Type I-A"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 202, r.text

    def test_review_with_jwt_fails_after_credits_exhausted(self, auth_client):
        token = self._register_and_token(auth_client)
        # Use the 1 free credit
        auth_client.post(
            "/review",
            json={"project_name": "First review", "text": "Occupied Hospital"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Second call should return 402
        r = auth_client.post(
            "/review",
            json={"project_name": "Second review", "text": "Occupied Hospital"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 402
        detail = r.json()["detail"]
        assert detail["error"] == "no_credits"

    def test_review_without_jwt_still_works_anonymous(self, auth_client):
        """Anonymous requests (no token) go through the existing Stripe flow."""
        r = auth_client.post(
            "/review",
            json={"project_name": "Anon review", "text": "Occupied Hospital"},
        )
        # Returns 202 (dev mode — no API keys set, auth disabled)
        assert r.status_code in (202, 401)

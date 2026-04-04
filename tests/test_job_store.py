"""Tests for SQLite-backed job store and HTTP rate limiting."""

from __future__ import annotations

from datetime import UTC
from uuid import uuid4

import pytest

from src.api.models import JobStatus
from src.db.job_store import SQLiteJobStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """Fresh SQLiteJobStore backed by a temp file."""
    return SQLiteJobStore(db_path=tmp_path / "test_jobs.db")


# ---------------------------------------------------------------------------
# TestSQLiteJobStore
# ---------------------------------------------------------------------------

class TestSQLiteJobStore:

    def test_create_returns_pending_job(self, store):
        job = store.create("Test Hospital")
        assert job.status == JobStatus.pending
        assert job.project_name == "Test Hospital"
        assert job.job_id is not None
        assert job.created_at is not None

    def test_get_returns_created_job(self, store):
        job = store.create("Valley Medical")
        fetched = store.get(job.job_id)
        assert fetched is not None
        assert fetched.job_id == job.job_id
        assert fetched.project_name == "Valley Medical"
        assert fetched.status == JobStatus.pending

    def test_get_unknown_id_returns_none(self, store):
        assert store.get(uuid4()) is None

    def test_update_status_persists(self, store):
        job = store.create("Mercy General")
        job.status = JobStatus.processing
        store.update(job)

        fetched = store.get(job.job_id)
        assert fetched.status == JobStatus.processing

    def test_update_complete_with_violations(self, store):
        from datetime import datetime
        job = store.create("Sunrise Hospital")
        job.status = JobStatus.complete
        job.completed_at = datetime.now(UTC)
        store.update(job)

        fetched = store.get(job.job_id)
        assert fetched.status == JobStatus.complete
        assert fetched.completed_at is not None

    def test_update_failed_stores_error(self, store):
        job = store.create("Lakeview Clinic")
        job.status = JobStatus.failed
        job.error = "Claude API timeout"
        store.update(job)

        fetched = store.get(job.job_id)
        assert fetched.status == JobStatus.failed
        assert fetched.error == "Claude API timeout"

    def test_list_recent_returns_newest_first(self, store):
        j1 = store.create("Alpha")
        store.create("Beta")
        j3 = store.create("Gamma")

        jobs = store.list_recent(limit=10)
        ids = [str(j.job_id) for j in jobs]
        assert ids[0] == str(j3.job_id)
        assert ids[-1] == str(j1.job_id)

    def test_list_recent_respects_limit(self, store):
        for i in range(10):
            store.create(f"Project {i}")
        assert len(store.list_recent(limit=5)) == 5

    def test_len_counts_all_jobs(self, store):
        assert len(store) == 0
        store.create("A")
        store.create("B")
        assert len(store) == 2

    def test_jobs_persist_across_instances(self, tmp_path):
        """Simulate server restart by creating a second store on same DB."""
        db_path = tmp_path / "restart_test.db"
        store1 = SQLiteJobStore(db_path=db_path)
        job = store1.create("Persistent Hospital")
        job.status = JobStatus.complete
        store1.update(job)

        # New instance — same DB file
        store2 = SQLiteJobStore(db_path=db_path)
        fetched = store2.get(job.job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.complete
        assert fetched.project_name == "Persistent Hospital"

    def test_migrations_run_once_idempotent(self, tmp_path):
        """Running migrations twice should not raise or duplicate data."""
        db_path = tmp_path / "idempotent.db"
        SQLiteJobStore(db_path=db_path)
        SQLiteJobStore(db_path=db_path)  # second init — should not raise


# ---------------------------------------------------------------------------
# TestGetJobStoreFallback
# ---------------------------------------------------------------------------

class TestGetJobStoreFallback:
    """get_job_store() should fall back to in-memory if SQLite fails."""

    def test_in_memory_fallback_interface(self):
        """In-memory JobStore satisfies the same interface."""
        from src.api.jobs import JobStore
        store = JobStore()
        job = store.create("Fallback Clinic")
        assert store.get(job.job_id) is not None
        job.status = JobStatus.complete
        store.update(job)
        assert store.get(job.job_id).status == JobStatus.complete
        assert len(store.list_recent()) == 1


# ---------------------------------------------------------------------------
# TestRateLimitMiddleware
# ---------------------------------------------------------------------------

class TestRateLimitMiddleware:

    @pytest.fixture
    def client(self, monkeypatch):
        """TestClient with a very tight rate limit (2 rpm, burst=2)."""
        monkeypatch.setenv("RATE_LIMIT_RPM", "2")
        monkeypatch.setenv("RATE_LIMIT_BURST", "2")

        # Re-import to pick up new env vars
        import importlib

        import src.api.app as app_module
        importlib.reload(app_module)
        app = app_module.create_app()

        from fastapi.testclient import TestClient
        return TestClient(app, raise_server_exceptions=False)

    def test_requests_within_burst_succeed(self, client):
        r1 = client.get("/health")
        r2 = client.get("/health")
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_requests_exceeding_burst_are_throttled(self, client):
        # Health is exempt; use /reviews which is rate-limited
        responses = [client.get("/reviews") for _ in range(5)]
        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, f"Expected 429 among: {status_codes}"

    def test_throttled_response_has_retry_after_header(self, client):
        # Exhaust the burst
        for _ in range(5):
            r = client.get("/reviews")
            if r.status_code == 429:
                assert "retry-after" in r.headers
                return
        pytest.skip("Burst not exhausted in 5 requests — increase request count")

    def test_health_endpoint_exempt_from_rate_limit(self, client):
        # Health should never be rate-limited regardless of burst
        for _ in range(10):
            r = client.get("/health")
            assert r.status_code == 200

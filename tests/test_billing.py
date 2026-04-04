"""
Tests for Stripe order persistence (migration 8 + OrderStore).

Verifies that pending orders survive a simulated process restart
by using a fresh OrderStore instance pointed at the same DB file.
"""

import sqlite3

import pytest

from src.db.migrations import run_migrations
from src.db.order_store import OrderStore


@pytest.fixture
def order_store(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    run_migrations(conn)
    conn.close()
    return OrderStore(db_path=db)


@pytest.fixture
def fresh_store(order_store):
    """Simulate a restart by creating a new OrderStore instance on the same DB."""
    return OrderStore(db_path=order_store._db_path)


# ---------------------------------------------------------------------------
# save_pending + pop_pending
# ---------------------------------------------------------------------------

class TestSavePending:

    def test_save_and_retrieve(self, order_store):
        order_store.save_pending(
            session_id="cs_test_abc",
            job_id="job-1",
            project_name="Valley Hospital",
            customer_email="user@example.com",
            temp_file_path="/tmp/upload.pdf",
            pasted_text=None,
        )
        row = order_store.pop_pending("cs_test_abc")
        assert row is not None
        assert row["job_id"] == "job-1"
        assert row["project_name"] == "Valley Hospital"
        assert row["customer_email"] == "user@example.com"
        assert row["temp_file_path"] == "/tmp/upload.pdf"
        assert row["pasted_text"] is None

    def test_save_with_pasted_text(self, order_store):
        order_store.save_pending(
            session_id="cs_test_xyz",
            job_id="job-2",
            project_name="Clinic A",
            customer_email="a@b.com",
            temp_file_path=None,
            pasted_text="Occupied Hospital, 80 beds.",
        )
        row = order_store.pop_pending("cs_test_xyz")
        assert row["pasted_text"] == "Occupied Hospital, 80 beds."
        assert row["temp_file_path"] is None

    def test_pop_returns_none_for_unknown_session(self, order_store):
        assert order_store.pop_pending("cs_nonexistent") is None

    def test_pop_is_idempotent(self, order_store):
        """Popping the same session twice returns None on second call."""
        order_store.save_pending("cs_dup", "j", "P", "e@e.com", None, None)
        order_store.pop_pending("cs_dup")
        assert order_store.pop_pending("cs_dup") is None

    def test_save_is_idempotent(self, order_store):
        """Saving the same session_id twice doesn't raise."""
        for _ in range(2):
            order_store.save_pending("cs_idem", "j", "P", "e@e.com", None, None)
        row = order_store.pop_pending("cs_idem")
        assert row is not None

    def test_survives_restart(self, order_store, fresh_store):
        """Order saved in one instance is retrievable from another (same DB file)."""
        order_store.save_pending("cs_restart", "job-r", "Hospital", "h@h.com", None, None)
        row = fresh_store.pop_pending("cs_restart")
        assert row is not None
        assert row["job_id"] == "job-r"


# ---------------------------------------------------------------------------
# mark_completed + get_job_for_session
# ---------------------------------------------------------------------------

class TestMarkCompleted:

    def test_completed_lookup(self, order_store):
        order_store.save_pending("cs_done", "job-done", "P", "e@e.com", None, None)
        order_store.pop_pending("cs_done")
        order_store.mark_completed("cs_done", "job-done")
        assert order_store.get_job_for_session("cs_done") == "job-done"

    def test_pending_not_returned_by_lookup(self, order_store):
        order_store.save_pending("cs_pend", "job-p", "P", "e@e.com", None, None)
        assert order_store.get_job_for_session("cs_pend") is None

    def test_unknown_session_lookup_returns_none(self, order_store):
        assert order_store.get_job_for_session("cs_ghost") is None

    def test_completed_lookup_survives_restart(self, order_store, fresh_store):
        """Completed mapping is retrievable from a new store instance."""
        order_store.save_pending("cs_c_restart", "job-cr", "P", "e@e.com", None, None)
        order_store.pop_pending("cs_c_restart")
        order_store.mark_completed("cs_c_restart", "job-cr")
        assert fresh_store.get_job_for_session("cs_c_restart") == "job-cr"

    def test_multiple_orders_independent(self, order_store):
        for i in range(3):
            order_store.save_pending(f"cs_{i}", f"job-{i}", "P", "e@e.com", None, None)
        order_store.pop_pending("cs_1")
        order_store.mark_completed("cs_1", "job-1")

        assert order_store.get_job_for_session("cs_1") == "job-1"
        assert order_store.get_job_for_session("cs_0") is None
        assert order_store.get_job_for_session("cs_2") is None
        assert order_store.pop_pending("cs_0") is not None
        assert order_store.pop_pending("cs_2") is not None

"""
SQLite-backed store for Stripe Checkout orders.

Replaces the in-memory _pending / _completed dicts in billing.py so that
pending orders survive process restarts (e.g. Railway dyno restarts between
a customer clicking "Pay" and Stripe firing the webhook).

Uses the same data/hcai.db database as the job store.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import config
from src.monitoring.logger import get_logger

log = get_logger(__name__)

_DB_PATH = Path(config.BASE_DIR) / "data" / "hcai.db"
_lock = threading.Lock()


@contextmanager
def _conn(db_path: Path = _DB_PATH):
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


class OrderStore:
    """Persistent store for Stripe Checkout pending/completed orders."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path

    def save_pending(
        self,
        session_id: str,
        job_id: str,
        project_name: str,
        customer_email: str,
        temp_file_path: str | None,
        pasted_text: str | None,
    ) -> None:
        """Persist a pending Stripe order. Idempotent on session_id."""
        with _lock, _conn(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO stripe_orders
                    (session_id, job_id, project_name, customer_email,
                     temp_file_path, pasted_text, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (session_id, job_id, project_name, customer_email,
                 temp_file_path, pasted_text),
            )
            conn.commit()

    def pop_pending(self, session_id: str) -> dict | None:
        """
        Retrieve and remove a pending order by Stripe session ID.
        Returns None if not found or already completed.
        """
        with _lock, _conn(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM stripe_orders WHERE session_id = ? AND status = 'pending'",
                (session_id,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE stripe_orders SET status = 'processing' WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return dict(row)

    def mark_completed(self, session_id: str, job_id: str) -> None:
        """Mark an order as completed after the review job starts."""
        with _lock, _conn(self._db_path) as conn:
            conn.execute(
                """
                UPDATE stripe_orders
                SET status = 'completed', completed_at = datetime('now')
                WHERE session_id = ?
                """,
                (session_id,),
            )
            conn.commit()

    def get_job_for_session(self, session_id: str) -> str | None:
        """Return the job_id for a completed Stripe session, or None."""
        with _conn(self._db_path) as conn:
            row = conn.execute(
                "SELECT job_id FROM stripe_orders WHERE session_id = ? AND status = 'completed'",
                (session_id,),
            ).fetchone()
            return row["job_id"] if row else None


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_store: OrderStore | None = None


def get_order_store() -> OrderStore:
    global _store
    if _store is None:
        _store = OrderStore()
    return _store

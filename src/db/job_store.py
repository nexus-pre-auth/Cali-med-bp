"""
SQLite Job Store — durable replacement for the in-memory JobStore.

Jobs survive server restarts. The schema lives in migration 2.
Interface is a drop-in replacement for src/api/jobs.py's JobStore.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import config
from src.db.migrations import run_migrations
from src.api.models import JobStatus, ReviewResponse
from src.monitoring.logger import get_logger

log = get_logger(__name__)

_DB_PATH = Path(config.BASE_DIR) / "data" / "hcai.db"


class SQLiteJobStore:
    """Persistent, thread-safe job store backed by SQLite."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            run_migrations(conn)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def create(self, project_name: str) -> ReviewResponse:
        now = datetime.now(timezone.utc)
        job = ReviewResponse(
            job_id=uuid4(),
            project_name=project_name,
            status=JobStatus.pending,
            created_at=now,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO jobs (job_id, project_name, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    str(job.job_id),
                    job.project_name,
                    job.status.value,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return job

    def update(self, job: ReviewResponse) -> None:
        now = datetime.now(timezone.utc).isoformat()
        completed_at = job.completed_at.isoformat() if job.completed_at else None
        # Serialise the full response minus heavy fields that are not needed
        # for polling — store everything so GET /review/{id} can reconstruct.
        result_json = job.model_dump_json() if job.status in (JobStatus.complete, JobStatus.failed) else None
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE jobs
                   SET status=?, updated_at=?, completed_at=?, result_json=?, error=?
                   WHERE job_id=?""",
                (
                    job.status.value,
                    now,
                    completed_at,
                    result_json,
                    job.error,
                    str(job.job_id),
                ),
            )

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get(self, job_id: UUID) -> Optional[ReviewResponse]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id=?", (str(job_id),)
            ).fetchone()
        if row is None:
            return None
        return self._hydrate(row)

    def list_recent(self, limit: int = 50) -> list[ReviewResponse]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._hydrate(r) for r in rows]

    def __len__(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def cleanup_old_jobs(self, keep_days: int = 90) -> int:
        """
        Delete completed or failed jobs older than *keep_days* days.
        Pending and processing jobs are never deleted.
        Returns the number of rows removed.
        """
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """DELETE FROM jobs
                   WHERE status IN ('complete', 'failed')
                   AND created_at < ?""",
                (cutoff,),
            )
            return cur.rowcount

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _hydrate(row: sqlite3.Row) -> ReviewResponse:
        """Reconstruct a ReviewResponse from a DB row."""
        # If the job is complete/failed, result_json has the full model
        if row["result_json"]:
            try:
                return ReviewResponse.model_validate_json(row["result_json"])
            except Exception:
                pass  # fall through to lightweight reconstruction

        return ReviewResponse(
            job_id=UUID(row["job_id"]),
            project_name=row["project_name"],
            status=JobStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"])
                if row["completed_at"] else None
            ),
            error=row["error"],
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: Optional[SQLiteJobStore] = None
_store_lock = threading.Lock()


def get_sqlite_job_store() -> SQLiteJobStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SQLiteJobStore()
    return _store

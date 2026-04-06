"""
Job store for async review processing.

Defaults to the SQLite-backed store (survives restarts).
Falls back to the in-memory store if the DB is unavailable
(e.g. read-only filesystem or unit tests that don't need persistence).

Each review is submitted as a background job so POST /review
returns immediately with a job_id. Clients poll
GET /review/{job_id} for results.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Union
from uuid import UUID, uuid4

from src.api.models import JobStatus, ReviewResponse

# ---------------------------------------------------------------------------
# In-memory fallback (also used by tests directly)
# ---------------------------------------------------------------------------

class JobStore:
    """Thread-safe in-memory store for review jobs."""

    def __init__(self) -> None:
        self._jobs: dict[UUID, ReviewResponse] = {}
        self._lock = threading.Lock()

    def create(self, project_name: str) -> ReviewResponse:
        job = ReviewResponse(
            job_id=uuid4(),
            project_name=project_name,
            status=JobStatus.pending,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: UUID) -> ReviewResponse | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: ReviewResponse) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def list_recent(self, limit: int = 50) -> list[ReviewResponse]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def set_user_id(self, job_id: UUID, user_id: str) -> None:
        """No-op for in-memory store (used in tests)."""

    def list_by_user(self, user_id: str, limit: int = 50) -> list[ReviewResponse]:
        return []

    def __len__(self) -> int:
        return len(self._jobs)


# ---------------------------------------------------------------------------
# Module-level singleton — SQLite-backed by default, in-memory as fallback
# ---------------------------------------------------------------------------

_store: Union[JobStore, SQLiteJobStore] | None = None  # noqa: F821
_store_lock = threading.Lock()


def get_job_store() -> Union[JobStore, SQLiteJobStore]:  # noqa: F821
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                try:
                    from src.db.job_store import get_sqlite_job_store
                    _store = get_sqlite_job_store()
                except Exception:
                    _store = JobStore()
    return _store

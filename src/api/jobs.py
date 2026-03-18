"""
In-memory job store for async review processing.

Each review is submitted as a background job so the POST /review
endpoint returns immediately with a job_id. Clients poll
GET /review/{job_id} for results.

For production scale, replace with Redis + Celery or similar.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from src.api.models import JobStatus, ReviewResponse


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
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: UUID) -> Optional[ReviewResponse]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: ReviewResponse) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def list_recent(self, limit: int = 50) -> list[ReviewResponse]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def __len__(self) -> int:
        return len(self._jobs)


# Module-level singleton — shared across all requests
_store = JobStore()


def get_job_store() -> JobStore:
    return _store

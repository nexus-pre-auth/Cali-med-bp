"""
PostgreSQL-backed job store — drop-in async replacement for the SQLite JobStore.

Only imported when is_postgres_configured() returns True.
The existing SQLite job store remains fully functional as the default.

Usage in FastAPI
----------------
    from src.database.connection import is_postgres_configured
    from src.database.pg_job_store import PgJobStore

    if is_postgres_configured():
        store = PgJobStore()
    else:
        store = get_job_store()   # SQLite fallback
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import select, update, func

from src.api.models import JobStatus, ReviewResponse, ReviewSummary, SeveritySummary, ViolationResponse
from src.database.connection import get_db
from src.database.models import Job, Violation, ExtractedCondition
from src.monitoring.logger import get_logger

log = get_logger(__name__)


class PgJobStore:
    """Async, PostgreSQL-backed implementation of the JobStore interface."""

    async def create(self, project_name: str, customer_email: Optional[str] = None) -> ReviewResponse:
        job_id = uuid4()
        now    = datetime.now(timezone.utc)
        async with get_db() as db:
            db_job = Job(
                id=job_id,
                project_name=project_name,
                status="pending",
                customer_email=customer_email,
                created_at=now,
            )
            db.add(db_job)
        log.debug("PgJobStore: created job %s", job_id)
        return ReviewResponse(
            job_id=job_id,
            project_name=project_name,
            status=JobStatus.pending,
            created_at=now,
        )

    async def get(self, job_id: UUID) -> Optional[ReviewResponse]:
        async with get_db() as db:
            row = await db.get(Job, job_id)
            if row is None:
                return None
            return self._hydrate(row)

    async def update(self, job: ReviewResponse) -> None:
        async with get_db() as db:
            row = await db.get(Job, job.job_id)
            if row is None:
                return
            row.status        = job.status.value
            row.error_message = job.error
            if job.completed_at:
                row.completed_at = job.completed_at

            # Persist violations
            if job.violations:
                for v in job.violations:
                    db_v = Violation(
                        job_id=job.job_id,
                        rule_id=v.rule_id,
                        discipline=v.discipline,
                        severity=v.severity.value,
                        trigger_condition=v.trigger_condition,
                        ahj_comment=v.ahj_comment,
                        fix_instructions=v.fix_instructions,
                        citations=v.citations,
                        confidence=v.confidence or 0.0,
                    )
                    db.add(db_v)

            # Persist extracted conditions
            if job.conditions:
                cond = job.conditions
                db_c = ExtractedCondition(
                    job_id=job.job_id,
                    occupancy_type=cond.occupancy_type,
                    construction_type=cond.construction_type,
                    licensed_beds=cond.licensed_beds,
                    sprinklered=cond.sprinklered,
                    county=cond.county,
                    city=cond.city,
                    seismic_zone=cond.seismic.seismic_zone if cond.seismic else None,
                    hvac_systems=cond.hvac_systems or [],
                    electrical_systems=cond.electrical_systems or [],
                    plumbing_systems=cond.plumbing_systems or [],
                    medical_gas_systems=cond.medical_gas_systems or [],
                    room_types=cond.room_types or [],
                    extraction_confidence=cond.extraction_confidence or 0.0,
                )
                db.add(db_c)

    async def list_recent(self, limit: int = 50) -> list[ReviewResponse]:
        async with get_db() as db:
            result = await db.execute(
                select(Job).order_by(Job.created_at.desc()).limit(limit)
            )
            return [self._hydrate(row) for row in result.scalars().all()]

    async def stats(self) -> dict[str, int]:
        async with get_db() as db:
            result = await db.execute(
                select(Job.status, func.count()).group_by(Job.status)
            )
            return {row[0]: row[1] for row in result.all()}

    # ------------------------------------------------------------------

    def _hydrate(self, row: Job) -> ReviewResponse:
        return ReviewResponse(
            job_id=row.id,
            project_name=row.project_name,
            status=JobStatus(row.status),
            created_at=row.created_at,
            completed_at=row.completed_at,
            error=row.error_message,
        )

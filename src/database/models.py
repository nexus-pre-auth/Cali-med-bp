"""
SQLAlchemy ORM models for the PostgreSQL persistence layer.

Tables
------
jobs            — async compliance review jobs
violations      — findings produced per job
extracted_conds — structured conditions extracted from each document
rules           — dynamic rule store (mirrors hcai_rules.json)
audit_log       — append-only audit trail
api_keys        — hashed API keys with rate-limit metadata

pgvector extension
------------------
The `extracted_conds.embedding` column uses the pgvector Vector type for
semantic similarity search over previous project conditions.
Run once on the database before first use:
    CREATE EXTENSION IF NOT EXISTS vector;
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# pgvector is optional at import time — only required when actually writing embeddings
try:
    from pgvector.sqlalchemy import Vector
    _VECTOR_TYPE = Vector(1536)
except ImportError:
    _VECTOR_TYPE = None   # column will be skipped if pgvector not installed


def _utcnow():
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class Job(Base):
    __tablename__ = "pg_jobs"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_name   = Column(String(512), nullable=False)
    status         = Column(String(32), nullable=False, default="pending", index=True)
    customer_email = Column(String(256))
    stripe_session = Column(String(256))
    paid           = Column(Boolean, default=False)
    created_at     = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    started_at     = Column(DateTime(timezone=True))
    completed_at   = Column(DateTime(timezone=True))
    error_message  = Column(Text)
    metadata_json  = Column(JSONB, default=dict)

    violations = relationship("Violation", back_populates="job", cascade="all, delete-orphan")
    conditions = relationship("ExtractedCondition", back_populates="job", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Violations
# ---------------------------------------------------------------------------

class Violation(Base):
    __tablename__ = "pg_violations"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id           = Column(UUID(as_uuid=True), ForeignKey("pg_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id          = Column(String(64), nullable=False, index=True)
    discipline       = Column(String(128))
    severity         = Column(String(32), nullable=False)
    trigger_condition= Column(Text)
    ahj_comment      = Column(Text)
    fix_instructions = Column(Text)
    citations        = Column(JSONB, default=list)   # list[str]
    confidence       = Column(Float, default=0.0)
    reviewer_accepted= Column(Boolean)               # feedback loop
    reviewer_notes   = Column(Text)
    created_at       = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    job = relationship("Job", back_populates="violations")

    __table_args__ = (
        Index("ix_pg_violations_job_severity", "job_id", "severity"),
    )


# ---------------------------------------------------------------------------
# Extracted conditions (with optional pgvector embedding)
# ---------------------------------------------------------------------------

class ExtractedCondition(Base):
    __tablename__ = "pg_extracted_conditions"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id          = Column(UUID(as_uuid=True), ForeignKey("pg_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    occupancy_type  = Column(String(128))
    construction_type = Column(String(64))
    licensed_beds   = Column(Integer)
    sprinklered     = Column(Boolean)
    county          = Column(String(128))
    city            = Column(String(128))
    seismic_zone    = Column(String(8))
    wui_zone        = Column(Boolean)
    hvac_systems    = Column(JSONB, default=list)
    electrical_systems = Column(JSONB, default=list)
    plumbing_systems = Column(JSONB, default=list)
    medical_gas_systems = Column(JSONB, default=list)
    room_types      = Column(JSONB, default=list)
    extraction_confidence = Column(Float, default=0.0)
    # pgvector embedding for similarity search (1536-dim = text-embedding-3-small)
    embedding       = Column(_VECTOR_TYPE) if _VECTOR_TYPE else Column(Text)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    job = relationship("Job", back_populates="conditions")


# ---------------------------------------------------------------------------
# Rules  (mirrors hcai_rules.json for querying via pgvector similarity)
# ---------------------------------------------------------------------------

class Rule(Base):
    __tablename__ = "pg_rules"

    id                  = Column(String(64), primary_key=True)
    discipline          = Column(String(128), index=True)
    description         = Column(Text)
    violation_template  = Column(Text)
    fix_template        = Column(Text)
    severity_override   = Column(String(32))
    effective_date      = Column(String(32))   # ISO date string
    is_active           = Column(Boolean, default=True, index=True)
    trigger_wui         = Column(Boolean)
    trigger_occupancies = Column(JSONB, default=list)
    trigger_systems     = Column(JSONB, default=list)
    trigger_rooms       = Column(JSONB, default=list)
    code_references     = Column(JSONB, default=list)
    metadata_json       = Column(JSONB, default=dict)
    created_at          = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at          = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "pg_audit_log"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    event         = Column(String(64), nullable=False, index=True)
    job_id        = Column(String(64), index=True)
    payload       = Column(JSONB, default=dict)
    ip_address    = Column(INET)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

class ApiKey(Base):
    __tablename__ = "pg_api_keys"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash     = Column(String(128), unique=True, nullable=False)
    name         = Column(String(256), nullable=False)
    rate_limit   = Column(Integer, default=100)    # requests/hour
    is_active    = Column(Boolean, default=True, index=True)
    last_used_at = Column(DateTime(timezone=True))
    created_at   = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

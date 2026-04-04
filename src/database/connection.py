"""
PostgreSQL async connection pool — powered by SQLAlchemy 2 + asyncpg.

Activated when DATABASE_URL (or DB_HOST / DB_NAME / DB_USER / DB_PASSWORD)
is set in the environment.  Falls back gracefully when not configured so the
existing SQLite layer continues to work in development.

Usage
-----
    from src.database.connection import get_db, is_postgres_configured

    if is_postgres_configured():
        async with get_db() as session:
            result = await session.execute(select(Job))
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from src.monitoring.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config — resolved once at import time
# ---------------------------------------------------------------------------

def _build_url() -> str | None:
    explicit = os.getenv("DATABASE_URL", "")
    if explicit:
        # Normalize postgres:// → postgresql+asyncpg://
        return explicit.replace("postgres://", "postgresql+asyncpg://", 1).replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
    host = os.getenv("DB_HOST", "")
    if not host:
        return None
    port     = os.getenv("DB_PORT", "5432")
    name     = os.getenv("DB_NAME", "hcai_compliance")
    user     = os.getenv("DB_USER", "hcai_user")
    password = os.getenv("DB_PASSWORD", "")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


_DATABASE_URL: str | None = _build_url()

# Lazy-initialised — only created when Postgres is actually configured
_engine       = None
_SessionLocal = None


def is_postgres_configured() -> bool:
    """True when a DATABASE_URL / DB_HOST is present in the environment."""
    return _DATABASE_URL is not None


def _get_engine():
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine

    if not _DATABASE_URL:
        raise RuntimeError(
            "PostgreSQL is not configured. "
            "Set DATABASE_URL or DB_HOST in your .env to enable it."
        )

    try:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        _engine = create_async_engine(
            _DATABASE_URL,
            echo=False,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
        )
        _SessionLocal = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        log.info("PostgreSQL engine initialised: %s", _DATABASE_URL.split("@")[-1])
        return _engine
    except ImportError as e:
        raise ImportError(
            "SQLAlchemy asyncio and asyncpg are required for PostgreSQL. "
            "Run: pip install 'sqlalchemy[asyncio]' asyncpg"
        ) from e


@asynccontextmanager
async def get_db() -> AsyncGenerator:
    """
    Async session context manager.

    async with get_db() as session:
        result = await session.execute(...)
    """
    _get_engine()   # ensure engine initialised

    async with _SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables() -> None:
    """Create all ORM-mapped tables. Call once on startup when Postgres is in use."""
    from src.database.models import Base
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("PostgreSQL tables created / verified.")


async def dispose() -> None:
    """Dispose the connection pool. Call on application shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None

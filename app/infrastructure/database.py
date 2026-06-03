from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.domain.models import Base

logger = logging.getLogger(__name__)

# Module-level singletons — initialised lazily on first use.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


# ---------------------------------------------------------------------------
# Engine / session-factory accessors
# ---------------------------------------------------------------------------

def get_engine() -> AsyncEngine:
    """Return (or create) the global async engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        engine_kwargs = {
            "echo": settings.DEBUG,
            "pool_pre_ping": True,
        }
        if not settings.DATABASE_URL.startswith("sqlite"):
            engine_kwargs["pool_size"] = settings.DATABASE_POOL_SIZE
            engine_kwargs["max_overflow"] = settings.DATABASE_MAX_OVERFLOW
        _engine = create_async_engine(
            settings.DATABASE_URL,
            **engine_kwargs
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return (or create) the global async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


# ---------------------------------------------------------------------------
# Session context manager (general purpose)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager that yields a transactional session.

    Commits on clean exit; rolls back on exception.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — inject into route handlers via ``Depends(get_db)``.

    Usage::

        @router.get("/")
        async def handler(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with get_db_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """Create all mapped tables if they do not already exist."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created (or already exist)")

    # Seeding POS data if empty
    try:
        from sqlalchemy import select, func
        from app.domain.models import POSTransaction
        from app.services.pos_correlator import load_pos_data
        from pathlib import Path

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(select(func.count(POSTransaction.id)))
            count = result.scalar() or 0
            if count == 0:
                csv_path = Path(__file__).resolve().parent.parent.parent / "sample_data" / "POS - sample transactionsb1e826f.csv"
                if csv_path.exists():
                    logger.info("Seeding POS transactions from %s...", csv_path)
                    inserted = await load_pos_data(session, csv_path)
                    await session.commit()
                    logger.info("Seeded %d POS transactions", inserted)
                else:
                    logger.warning("POS sample CSV not found at %s", csv_path)
    except Exception as e:
        logger.error("Failed to seed POS database: %s", e)


async def check_db_health() -> bool:
    """
    Lightweight connectivity probe.

    Returns ``True`` if the database responds to a ``SELECT 1``,
    ``False`` otherwise.
    """
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("DB health check failed: %s", exc)
        return False


async def close_db() -> None:
    """Dispose the engine and reset the module-level singleton."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("Database connection pool closed")

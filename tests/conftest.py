# PROMPT:
# Create pytest fixtures for the Store Intelligence Platform test suite.
# Fixtures include: async test database, FastAPI test client, sample events.
#
# CHANGES MADE:
# - Used SQLite in-memory for tests (asyncpg not needed)
# - Created fresh tables per session
# - Provided helper for generating test events

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.domain.enums import EventType
from app.domain.models import Base
from app.domain.schemas import EventMetadata, StoreEvent
from app.infrastructure.database import get_db
from app.main import create_app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
TEST_STORE_ID = "ST_TEST"
TEST_CAMERA_ID = "CAM_TEST"


# ---------------------------------------------------------------------------
# Session-scoped event loop (required for session-scoped async fixtures)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """
    Create an async SQLite in-memory engine and build all tables once per
    test session.  The engine is disposed after all tests have run.
    """
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a fresh AsyncSession for each test.  Changes are rolled back after
    the test completes so tests remain isolated.
    """
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# HTTP client fixture
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """
    Yield an httpx AsyncClient backed by the FastAPI ASGI app.
    The real database dependency is replaced with the in-memory SQLite engine
    so no external Postgres instance is required.
    """
    app = create_app()

    # Build a session factory bound to the test engine
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Event factory helper
# ---------------------------------------------------------------------------
def make_event(
    event_type: EventType = EventType.ENTRY,
    visitor_id: Optional[str] = None,
    store_id: str = TEST_STORE_ID,
    camera_id: str = TEST_CAMERA_ID,
    zone_id: Optional[str] = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.9,
    timestamp: Optional[datetime] = None,
    queue_depth: Optional[int] = None,
) -> StoreEvent:
    """
    Construct a valid :class:`StoreEvent` with sensible defaults.

    Parameters
    ----------
    event_type:
        The type of store event to simulate.
    visitor_id:
        Optional explicit visitor ID; auto-generated if omitted.
    store_id:
        Store identifier (defaults to TEST_STORE_ID).
    camera_id:
        Camera identifier (defaults to TEST_CAMERA_ID).
    zone_id:
        Zone identifier; required for zone-related event types.
    dwell_ms:
        Dwell duration in milliseconds.
    is_staff:
        Whether the person is a staff member (excluded from KPIs).
    confidence:
        Detection confidence score in [0, 1].
    timestamp:
        Event timestamp; defaults to *now* in UTC.
    queue_depth:
        Current billing-queue depth; surfaced in EventMetadata.

    Returns
    -------
    StoreEvent
        A fully-populated, Pydantic-validated store event instance.
    """
    return StoreEvent(
        event_id=str(uuid.uuid4()),
        store_id=store_id,
        camera_id=camera_id,
        visitor_id=visitor_id or f"VIS_{uuid.uuid4().hex[:8].upper()}",
        event_type=event_type,
        timestamp=timestamp or datetime.now(timezone.utc),
        zone_id=zone_id,
        dwell_ms=dwell_ms,
        is_staff=is_staff,
        confidence=confidence,
        metadata=EventMetadata(queue_depth=queue_depth, session_seq=1),
    )


# ---------------------------------------------------------------------------
# Miscellaneous convenience fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_visitor_id() -> str:
    """Return a fresh random visitor ID string."""
    return f"VIS_{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture
def now() -> datetime:
    """Return the current UTC timestamp (timezone-aware)."""
    return datetime.now(timezone.utc)

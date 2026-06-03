from __future__ import annotations
import time
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.database import get_db, check_db_health
from app.infrastructure.repositories import EventRepository
from app.domain.schemas import HealthResponse
from app.config import get_settings

router = APIRouter(tags=["Health"])
logger = logging.getLogger(__name__)

_start_time = time.monotonic()


@router.get("/health", response_model=HealthResponse)
async def health_check(
    db: AsyncSession = Depends(get_db),
    settings=Depends(get_settings),
):
    """Return service health status."""
    db_ok = await check_db_health()

    last_event_ts: datetime | None = None
    stale = False

    if db_ok:
        try:
            repo = EventRepository(db)
            # Check across common store IDs
            from sqlalchemy import select, func
            from app.domain.models import EventRecord
            result = await db.execute(select(func.max(EventRecord.timestamp)))
            last_event_ts = result.scalar_one_or_none()

            if last_event_ts:
                age = (datetime.now(timezone.utc) - last_event_ts).total_seconds()
                stale = age > settings.STALE_FEED_THRESHOLD_SECONDS
        except Exception as e:
            logger.warning("Could not fetch last event: %s", e)

    status = "healthy" if db_ok else "degraded"
    uptime = round(time.monotonic() - _start_time, 2)

    response = HealthResponse(
        status=status,
        database="connected" if db_ok else "disconnected",
        last_event_timestamp=last_event_ts,
        stale_feed=stale,
        stale_feed_threshold_seconds=settings.STALE_FEED_THRESHOLD_SECONDS,
        uptime_seconds=uptime,
    )

    status_code = 200 if db_ok else 503
    return JSONResponse(content=response.model_dump(mode="json"), status_code=status_code)

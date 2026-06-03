from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.database import get_db
from app.infrastructure.repositories import EventRepository
from app.domain.schemas import IngestRequest, IngestResult
from app.services.deduplication import get_dedup_cache

router = APIRouter(prefix="/events", tags=["Events"])
logger = logging.getLogger(__name__)


@router.post("/ingest", response_model=IngestResult, status_code=201)
async def ingest_events(
    payload: IngestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest a batch of store events.
    - Validates each event via Pydantic schema
    - Deduplicates by event_id (in-memory + DB upsert)
    - Supports partial success: accepted + rejected counts returned
    - Idempotent: same event_id processed twice returns same result
    """
    request.state.event_count = len(payload.events)
    if not payload.events:
        raise HTTPException(status_code=422, detail="No events provided")

    cache = get_dedup_cache()
    repo = EventRepository(db)

    accepted = 0
    rejected = 0
    duplicates = 0
    errors: list[str] = []

    for event in payload.events:
        try:
            # In-memory dedup check
            if cache.is_duplicate(event.event_id):
                duplicates += 1
                continue

            # DB upsert (handles race conditions)
            was_new = await repo.upsert(event)

            if was_new:
                cache.mark_seen(event.event_id)
                accepted += 1
            else:
                duplicates += 1

        except Exception as e:
            logger.error("Failed to ingest event %s: %s", event.event_id, e)
            errors.append(f"event_id={event.event_id}: {type(e).__name__}")
            rejected += 1

    return IngestResult(
        accepted=accepted,
        rejected=rejected,
        duplicates=duplicates,
        errors=errors,
    )

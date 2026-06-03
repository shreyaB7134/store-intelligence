from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.database import get_db
from app.services.analytics import get_store_metrics, get_store_funnel, get_store_heatmap
from app.services.anomaly import detect_anomalies
from app.domain.schemas import (
    MetricsResponse, FunnelResponse, HeatmapResponse, AnomaliesResponse
)

router = APIRouter(prefix="/stores", tags=["Stores"])
logger = logging.getLogger(__name__)


def _parse_dt(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid datetime format: {dt_str}")


@router.get("/{store_id}/metrics", response_model=MetricsResponse)
async def get_metrics(
    store_id: str,
    since: Optional[str] = Query(None, description="ISO 8601 datetime"),
    until: Optional[str] = Query(None, description="ISO 8601 datetime"),
    db: AsyncSession = Depends(get_db),
):
    """Get store metrics: unique visitors, conversion rate, dwell, queue, abandonment."""
    try:
        return await get_store_metrics(
            db, store_id,
            since=_parse_dt(since),
            until=_parse_dt(until),
        )
    except Exception as e:
        logger.exception("Error computing metrics for %s", store_id)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")


@router.get("/{store_id}/funnel", response_model=FunnelResponse)
async def get_funnel(
    store_id: str,
    since: Optional[str] = Query(None, description="ISO 8601 datetime"),
    db: AsyncSession = Depends(get_db),
):
    """Get customer journey funnel: Entry → Zone → Billing → Purchase."""
    try:
        return await get_store_funnel(db, store_id, since=_parse_dt(since))
    except Exception as e:
        logger.exception("Error computing funnel for %s", store_id)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")


@router.get("/{store_id}/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    store_id: str,
    since: Optional[str] = Query(None, description="ISO 8601 datetime"),
    db: AsyncSession = Depends(get_db),
):
    """Get normalized zone popularity scores for heatmap visualization."""
    try:
        return await get_store_heatmap(db, store_id, since=_parse_dt(since))
    except Exception as e:
        logger.exception("Error computing heatmap for %s", store_id)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")


@router.get("/{store_id}/anomalies", response_model=AnomaliesResponse)
async def get_anomalies(
    store_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Detect queue spikes, dead zones, and conversion drops."""
    try:
        return await detect_anomalies(db, store_id)
    except Exception as e:
        logger.exception("Error detecting anomalies for %s", store_id)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

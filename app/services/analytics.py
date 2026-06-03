from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.repositories import EventRepository, POSRepository
from app.services.pos_correlator import compute_conversion_rate
from app.domain.schemas import (
    MetricsResponse, FunnelResponse, FunnelStage,
    HeatmapResponse, ZoneScore
)
from app.domain.enums import EventType
from app.config import get_settings

logger = logging.getLogger(__name__)


async def get_store_metrics(
    session: AsyncSession,
    store_id: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> MetricsResponse:
    repo = EventRepository(session)
    settings = get_settings()

    unique_visitors = await repo.get_unique_visitor_count(store_id, since=since, until=until)
    avg_dwell = await repo.get_average_dwell(store_id, since=since)
    queue_depth = await repo.get_queue_depth(store_id)

    # Abandonment rate
    joins = await repo.count_events_by_type(store_id, EventType.BILLING_QUEUE_JOIN, since=since)
    abandons = await repo.count_events_by_type(store_id, EventType.BILLING_QUEUE_ABANDON, since=since)
    abandonment_rate = (abandons / joins) if joins > 0 else 0.0

    # Conversion rate using POS correlation
    conversion_rate = await compute_conversion_rate(
        session, store_id, unique_visitors,
        pos_window_seconds=settings.POS_MATCH_WINDOW_SECONDS,
    )

    return MetricsResponse(
        store_id=store_id,
        period_start=since,
        period_end=until or datetime.now(timezone.utc),
        unique_visitors=unique_visitors,
        conversion_rate=round(conversion_rate, 4),
        average_dwell_ms=round(avg_dwell, 2),
        queue_depth=queue_depth,
        abandonment_rate=round(abandonment_rate, 4),
    )


async def get_store_funnel(
    session: AsyncSession,
    store_id: str,
    since: Optional[datetime] = None,
) -> FunnelResponse:
    repo = EventRepository(session)
    counts = await repo.get_funnel_counts(store_id, since=since)

    entry = counts["entry"]
    zone = counts["zone"]
    billing = counts["billing"]
    purchase = counts["purchase"]

    def dropoff(current: int, previous: int) -> float:
        if previous == 0:
            return 0.0
        return round((1 - current / previous) * 100, 2)

    stages = [
        FunnelStage(stage="Entry", count=entry, dropoff_pct=0.0),
        FunnelStage(stage="Zone Browse", count=zone, dropoff_pct=dropoff(zone, entry)),
        FunnelStage(stage="Billing Queue", count=billing, dropoff_pct=dropoff(billing, zone)),
        FunnelStage(stage="Purchase", count=purchase, dropoff_pct=dropoff(purchase, billing)),
    ]
    return FunnelResponse(store_id=store_id, stages=stages)


async def get_store_heatmap(
    session: AsyncSession,
    store_id: str,
    since: Optional[datetime] = None,
) -> HeatmapResponse:
    repo = EventRepository(session)
    zone_stats = await repo.get_zone_stats(store_id, since=since)
    total_sessions = await repo.get_total_sessions(store_id)
    data_confidence = total_sessions >= 20

    if not zone_stats:
        return HeatmapResponse(store_id=store_id, zones=[], data_confidence=data_confidence)

    max_visits = max(z["visit_count"] for z in zone_stats) or 1
    zones = [
        ZoneScore(
            zone_id=z["zone_id"],
            score=round((z["visit_count"] / max_visits) * 100, 2),
            visit_count=z["visit_count"],
            avg_dwell_ms=round(z["avg_dwell_ms"], 2),
        )
        for z in zone_stats
    ]
    return HeatmapResponse(store_id=store_id, zones=zones, data_confidence=data_confidence)

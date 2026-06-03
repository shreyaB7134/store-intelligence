from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.repositories import EventRepository
from app.domain.schemas import AnomaliesResponse, AnomalyItem
from app.domain.enums import Severity, AnomalyType
from app.config import get_settings

logger = logging.getLogger(__name__)


async def detect_anomalies(
    session: AsyncSession, store_id: str
) -> AnomaliesResponse:
    settings = get_settings()
    repo = EventRepository(session)
    now = datetime.now(timezone.utc)
    anomalies: list[AnomalyItem] = []

    # --- 1. Queue Spike ---
    current_queue = await repo.get_queue_depth(store_id)
    historical_avg = await repo.get_historical_queue_depth(store_id, days=7)
    threshold = settings.QUEUE_SPIKE_MULTIPLIER

    if historical_avg > 0 and current_queue > historical_avg * threshold:
        anomalies.append(AnomalyItem(
            anomaly_type=AnomalyType.QUEUE_SPIKE,
            severity=Severity.CRITICAL if current_queue > historical_avg * threshold * 1.5 else Severity.WARN,
            message=f"Queue depth {current_queue} is {current_queue / historical_avg:.1f}x historical average ({historical_avg:.1f})",
            suggested_action="Deploy additional billing staff immediately. Consider opening secondary counter.",
            detected_at=now,
            metadata={"current_queue": current_queue, "historical_avg": historical_avg},
        ))
    elif current_queue > 10:  # Absolute threshold
        anomalies.append(AnomalyItem(
            anomaly_type=AnomalyType.QUEUE_SPIKE,
            severity=Severity.WARN,
            message=f"Queue depth {current_queue} is unusually high (no historical data)",
            suggested_action="Monitor queue and consider opening secondary counter.",
            detected_at=now,
            metadata={"current_queue": current_queue},
        ))

    # --- 2. Conversion Drop ---
    current_conv = await repo.get_historical_conversion_rate(store_id, days=1)
    rolling_7d = await repo.get_historical_conversion_rate(store_id, days=7)
    drop_threshold = settings.CONVERSION_DROP_THRESHOLD

    if rolling_7d > 0 and current_conv < rolling_7d * drop_threshold:
        anomalies.append(AnomalyItem(
            anomaly_type=AnomalyType.CONVERSION_DROP,
            severity=Severity.CRITICAL if current_conv < rolling_7d * 0.25 else Severity.WARN,
            message=f"Conversion rate dropped to {current_conv:.1%} vs 7-day avg {rolling_7d:.1%}",
            suggested_action="Check if billing is functional. Review customer journey and remove friction points.",
            detected_at=now,
            metadata={"current_rate": current_conv, "rolling_7d_rate": rolling_7d},
        ))

    # --- 3. Dead Zones ---
    dead_zone_threshold = timedelta(minutes=settings.DEAD_ZONE_MINUTES)
    all_zones = await repo.get_all_zones(store_id)

    for zone_id in all_zones:
        last_activity = await repo.get_last_zone_activity(store_id, zone_id)
        if last_activity:
            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)
            if (now - last_activity) > dead_zone_threshold:
                idle_minutes = int((now - last_activity).total_seconds() / 60)
                anomalies.append(AnomalyItem(
                    anomaly_type=AnomalyType.DEAD_ZONE,
                    severity=Severity.WARN if idle_minutes < 60 else Severity.CRITICAL,
                    message=f"Zone {zone_id} has had no activity for {idle_minutes} minutes",
                    suggested_action=f"Check camera feed for zone {zone_id}. Verify products are stocked and displays are attractive.",
                    detected_at=now,
                    metadata={"zone_id": zone_id, "idle_minutes": idle_minutes},
                ))

    return AnomaliesResponse(store_id=store_id, anomalies=anomalies)

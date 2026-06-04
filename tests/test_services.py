from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta
from app.services.analytics import get_store_metrics, get_store_funnel, get_store_heatmap
from app.services.pos_correlator import compute_conversion_rate, load_pos_data
from app.services.deduplication import DeduplicationCache
from app.domain.schemas import MetricsResponse, FunnelResponse, HeatmapResponse
from app.domain.enums import EventType

@pytest.mark.asyncio
async def test_get_store_metrics():
    with patch('app.services.analytics.EventRepository') as mock_repo_class, \
         patch('app.services.analytics.compute_conversion_rate', new_callable=AsyncMock) as mock_compute:
        
        mock_repo = mock_repo_class.return_value
        mock_repo.get_unique_visitor_count = AsyncMock(return_value=100)
        mock_repo.get_average_dwell = AsyncMock(return_value=1500.0)
        mock_repo.get_queue_depth = AsyncMock(return_value=5)
        mock_repo.get_current_occupancy = AsyncMock(return_value=25)
        mock_repo.count_events_by_type = AsyncMock(side_effect=[10, 2]) # joins, abandons
        
        mock_compute.return_value = 0.45
        
        # We don't actually need a real AsyncSession, just a mock
        session = AsyncMock()
        
        metrics = await get_store_metrics(session, "ST1008")
        
        assert isinstance(metrics, MetricsResponse)
        assert metrics.unique_visitors == 100
        assert metrics.average_dwell_ms == 1500.0
        assert metrics.queue_depth == 5
        assert metrics.current_occupancy == 25
        assert metrics.abandonment_rate == 0.2  # 2 / 10
        assert metrics.conversion_rate == 0.45

@pytest.mark.asyncio
async def test_get_store_funnel():
    with patch('app.services.analytics.EventRepository') as mock_repo_class:
        mock_repo = mock_repo_class.return_value
        mock_repo.get_funnel_counts = AsyncMock(return_value={
            "entry": 100,
            "zone": 80,
            "billing": 50,
            "purchase": 40
        })
        
        session = AsyncMock()
        funnel = await get_store_funnel(session, "ST1008")
        
        assert isinstance(funnel, FunnelResponse)
        assert len(funnel.stages) == 4
        assert funnel.stages[0].count == 100
        assert funnel.stages[1].count == 80
        assert funnel.stages[1].dropoff_pct == 20.0  # (1 - 80/100) * 100
        assert funnel.stages[3].count == 40
        assert funnel.stages[3].dropoff_pct == 20.0  # (1 - 40/50) * 100

@pytest.mark.asyncio
async def test_get_store_heatmap():
    with patch('app.services.analytics.EventRepository') as mock_repo_class:
        mock_repo = mock_repo_class.return_value
        mock_repo.get_total_sessions = AsyncMock(return_value=100)
        mock_repo.get_zone_stats = AsyncMock(return_value=[
            {"zone_id": "Z1", "zone_name": "A", "visit_count": 50, "avg_dwell_ms": 1000},
            {"zone_id": "Z2", "zone_name": "B", "visit_count": 25, "avg_dwell_ms": 2000},
        ])
        
        session = AsyncMock()
        heatmap = await get_store_heatmap(session, "ST1008")
        
        assert isinstance(heatmap, HeatmapResponse)
        assert heatmap.data_confidence is True
        assert len(heatmap.zones) == 2
        assert heatmap.zones[0].score == 100.0  # 50 / 50 * 100
        assert heatmap.zones[1].score == 50.0   # 25 / 50 * 100

@pytest.mark.asyncio
async def test_compute_conversion_rate(db_session):
    from app.domain.models import EventRecord, POSTransaction
    from app.domain.enums import EventType
    from app.services.pos_correlator import compute_conversion_rate
    
    t1 = datetime.now(timezone.utc)
    ev = EventRecord(
        event_id="EV1",
        store_id="ST1",
        camera_id="CAM1",
        visitor_id="V1",
        event_type=EventType.BILLING_QUEUE_JOIN,
        timestamp=t1,
        is_staff=False
    )
    pos = POSTransaction(
        order_id="TX1",
        store_id="ST1",
        order_datetime=t1 + timedelta(seconds=10),
        total_amount=50.0,
        product_id="SKU1",
        brand_name="Brand"
    )
    db_session.add(ev)
    db_session.add(pos)
    await db_session.commit()
    
    rate = await compute_conversion_rate(db_session, "ST1", 10)
    assert rate == 0.1
    
    rate_zero = await compute_conversion_rate(db_session, "ST1", 0)
    assert rate_zero == 0.0
    
    rate_cap = await compute_conversion_rate(db_session, "ST1", 1)
    assert rate_cap == 1.0

@pytest.mark.asyncio
async def test_deduplicator():
    dedup = DeduplicationCache(ttl_seconds=60)
    
    # Is unique first time
    assert dedup.is_duplicate("EV1") is False
    
    # Mark it
    dedup.mark_seen("EV1")
    
    # Now it is duplicate
    assert dedup.is_duplicate("EV1") is True
    
    # Another event
    assert dedup.is_duplicate("EV2") is False

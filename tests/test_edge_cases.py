# PROMPT:
# Test edge cases: empty store, zero purchases, staff-only traffic,
# duplicate events, malformed events, and health endpoint.
#
# CHANGES MADE:
# - Isolated stores per test to avoid data interference
# - Tests health endpoint response schema

from __future__ import annotations

import pytest

from app.domain.enums import EventType
from tests.conftest import make_event


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_health_endpoint(client):
    """
    The /health endpoint must return 200 (or 503 when degraded) and always
    include the four canonical status fields.
    """
    response = await client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data, "Missing 'status' field"
    assert "database" in data, "Missing 'database' field"
    assert "stale_feed" in data, "Missing 'stale_feed' field"
    assert "uptime_seconds" in data, "Missing 'uptime_seconds' field"


# ---------------------------------------------------------------------------
# Staff-only traffic
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_staff_only_traffic_excluded_from_visitors(client):
    """
    When all ENTRY events belong to staff members, unique_visitors must be 0.
    """
    store = "ST_STAFF_ONLY"
    events = [
        make_event(EventType.ENTRY, store_id=store, is_staff=True),
        make_event(EventType.ENTRY, store_id=store, is_staff=True),
    ]
    payload = {"events": [e.model_dump(mode="json") for e in events]}
    await client.post("/events/ingest", json=payload)

    r = await client.get(f"/stores/{store}/metrics")
    data = r.json()
    assert data["unique_visitors"] == 0


# ---------------------------------------------------------------------------
# Deduplication correctness
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_duplicate_events_not_double_counted(client):
    """
    Re-submitting the same event must not inflate unique_visitors.  The second
    submission must be flagged as a duplicate and the visitor count must remain 1.
    """
    store = "ST_DEDUP_TEST"
    event = make_event(EventType.ENTRY, store_id=store)
    payload = {"events": [event.model_dump(mode="json")]}

    r1 = await client.post("/events/ingest", json=payload)
    r2 = await client.post("/events/ingest", json=payload)

    assert r1.json()["accepted"] == 1
    assert r2.json()["duplicates"] == 1

    r = await client.get(f"/stores/{store}/metrics")
    assert r.json()["unique_visitors"] == 1


# ---------------------------------------------------------------------------
# Malformed / missing fields
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_malformed_event_rejected(client):
    """
    A completely malformed event body with no recognisable fields must be
    rejected with HTTP 422.
    """
    response = await client.post("/events/ingest", json={
        "events": [{"bad_field": "bad_value"}]
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_required_fields(client):
    """
    An event object that is missing visitor_id, camera_id, and timestamp must
    be rejected with HTTP 422.
    """
    response = await client.post("/events/ingest", json={
        "events": [{
            "store_id": "X",
            "event_type": "ENTRY",
            # visitor_id, camera_id, event_id, and timestamp are all absent
        }]
    })
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Heatmap edge case
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_heatmap_empty_store(client):
    """
    A store with no zone events must return an empty zones list, not an error.
    """
    response = await client.get("/stores/ST_HEATMAP_EMPTY/heatmap")
    assert response.status_code == 200
    data = response.json()
    assert "zones" in data
    assert data["zones"] == []


@pytest.mark.asyncio
async def test_heatmap_data_confidence(client):
    """
    Test that the heatmap returns data_confidence=False when sessions < 20,
    and data_confidence=True when sessions >= 20.
    Also verify scores are normalized to 0-100.
    """
    store = "ST_HEATMAP_CONF"

    # 1. Check baseline with 0 sessions
    r1 = await client.get(f"/stores/{store}/heatmap")
    assert r1.status_code == 200
    assert r1.json()["data_confidence"] is False

    # 2. Ingest 20 unique sessions
    events = []
    for i in range(20):
        visitor = f"VIS_CONF_{i}"
        events.append(make_event(EventType.ENTRY, store_id=store, visitor_id=visitor))

    # Also add some zone events to test 0-100 score normalization
    events.append(make_event(EventType.ZONE_ENTER, store_id=store, visitor_id="VIS_CONF_0", zone_id="Z1"))
    events.append(make_event(EventType.ZONE_ENTER, store_id=store, visitor_id="VIS_CONF_1", zone_id="Z2"))
    events.append(make_event(EventType.ZONE_ENTER, store_id=store, visitor_id="VIS_CONF_2", zone_id="Z2"))

    payload = {"events": [e.model_dump(mode="json") for e in events]}
    await client.post("/events/ingest", json=payload)

    r2 = await client.get(f"/stores/{store}/heatmap")
    assert r2.status_code == 200
    data = r2.json()
    assert data["data_confidence"] is True

    # Z2 gets 2 visits (max), score should be 100
    # Z1 gets 1 visit (1/2), score should be 50
    zones = {z["zone_id"]: z["score"] for z in data["zones"]}
    assert zones["Z2"] == 100.0
    assert zones["Z1"] == 50.0


# ---------------------------------------------------------------------------
# Funnel staff exclusion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_funnel_staff_only(client):
    """
    When all traffic is staff, the Entry funnel stage should report 0 visitors
    because staff are excluded from journey analytics.
    """
    store = "ST_FUNNEL_STAFF"
    events = [
        make_event(EventType.ENTRY, store_id=store, is_staff=True),
        make_event(EventType.ZONE_ENTER, store_id=store, is_staff=True, zone_id="Z1"),
    ]
    payload = {"events": [e.model_dump(mode="json") for e in events]}
    await client.post("/events/ingest", json=payload)

    r = await client.get(f"/stores/{store}/funnel")
    data = r.json()
    stages = {s["stage"]: s["count"] for s in data["stages"]}
    assert stages["Entry"] == 0, (
        f"Expected 0 for Entry stage (staff-only traffic), got {stages['Entry']}"
    )

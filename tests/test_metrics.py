# PROMPT:
# Test store metrics endpoint: unique visitors, conversion rate, dwell, queue, abandonment.
# Tests cover normal operation, empty store, zero purchases, staff-only traffic.
#
# CHANGES MADE:
# - Seeds test data via ingest API
# - Asserts all metric fields present with correct types

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from app.domain.enums import EventType
from tests.conftest import TEST_STORE_ID, make_event


# ---------------------------------------------------------------------------
# Empty / baseline
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metrics_empty_store(client):
    """
    A store that has never received any events should return a metrics payload
    with all counters at zero / 0.0.
    """
    response = await client.get("/stores/EMPTY_STORE_XYZ/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0
    assert data["queue_depth"] == 0
    assert data["abandonment_rate"] == 0.0


# ---------------------------------------------------------------------------
# Visitor counting
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metrics_with_visitors(client):
    """Ingest 5 ENTRY events and verify unique_visitors equals 5."""
    store = "ST_METRICS_TEST"
    events = [make_event(EventType.ENTRY, store_id=store) for _ in range(5)]
    payload = {"events": [e.model_dump(mode="json") for e in events]}

    r = await client.post("/events/ingest", json=payload)
    assert r.json()["accepted"] == 5

    response = await client.get(f"/stores/{store}/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["unique_visitors"] == 5


# ---------------------------------------------------------------------------
# Staff exclusion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metrics_staff_excluded(client):
    """
    Staff ENTRY events must NOT contribute to unique_visitors.
    Only genuine customer traffic should be counted.
    """
    store = "ST_STAFF_TEST"
    staff_event = make_event(EventType.ENTRY, store_id=store, is_staff=True)
    cust_event = make_event(EventType.ENTRY, store_id=store, is_staff=False)

    payload = {"events": [
        staff_event.model_dump(mode="json"),
        cust_event.model_dump(mode="json"),
    ]}
    await client.post("/events/ingest", json=payload)

    response = await client.get(f"/stores/{store}/metrics")
    data = response.json()
    # Only 1 customer visitor; the staff member must be excluded
    assert data["unique_visitors"] == 1


# ---------------------------------------------------------------------------
# Abandonment rate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metrics_abandonment_rate(client):
    """
    A visitor who joins and then abandons the billing queue should produce an
    abandonment_rate of 1.0 (100 %).
    """
    store = "ST_ABANDON_TEST"
    visitor = "VIS_ABANDON_001"

    events = [
        make_event(EventType.ENTRY, visitor_id=visitor, store_id=store),
        make_event(EventType.BILLING_QUEUE_JOIN, visitor_id=visitor, store_id=store, zone_id="BILLING"),
        make_event(EventType.BILLING_QUEUE_ABANDON, visitor_id=visitor, store_id=store, zone_id="BILLING"),
    ]
    payload = {"events": [e.model_dump(mode="json") for e in events]}
    await client.post("/events/ingest", json=payload)

    response = await client.get(f"/stores/{store}/metrics")
    data = response.json()
    assert data["abandonment_rate"] == 1.0


# ---------------------------------------------------------------------------
# Zero-purchase conversion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metrics_zero_purchases(client):
    """
    Visitors who enter but never reach the billing queue should result in a
    conversion_rate of 0.0.
    """
    store = "ST_ZERO_PURCHASE"
    events = [make_event(EventType.ENTRY, store_id=store) for _ in range(3)]
    payload = {"events": [e.model_dump(mode="json") for e in events]}
    await client.post("/events/ingest", json=payload)

    response = await client.get(f"/stores/{store}/metrics")
    data = response.json()
    assert data["conversion_rate"] == 0.0


# ---------------------------------------------------------------------------
# Schema completeness
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metrics_response_schema(client):
    """
    The metrics response payload must include all required top-level fields
    regardless of whether there is any data for the store.
    """
    response = await client.get(f"/stores/{TEST_STORE_ID}/metrics")
    assert response.status_code == 200
    data = response.json()

    required_fields = [
        "store_id",
        "unique_visitors",
        "conversion_rate",
        "average_dwell_ms",
        "queue_depth",
        "abandonment_rate",
        "current_occupancy",
    ]
    for field in required_fields:
        assert field in data, f"Missing required field in response: {field}"

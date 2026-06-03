# PROMPT:
# Test customer journey funnel: correct stage progression, dropoff percentages,
# empty funnel, and staff exclusion.
#
# CHANGES MADE:
# - Seeds complete funnel journey
# - Verifies monotonic dropoff (each stage <= previous)

from __future__ import annotations

import pytest

from app.domain.enums import EventType
from tests.conftest import make_event


# ---------------------------------------------------------------------------
# Empty store baseline
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_funnel_empty(client):
    """
    A store with no events should return a funnel where the Entry stage
    count is 0.
    """
    response = await client.get("/stores/ST_FUNNEL_EMPTY/funnel")
    assert response.status_code == 200
    data = response.json()
    # Funnel stages must always be present even when empty
    assert len(data["stages"]) > 0
    assert data["stages"][0]["count"] == 0  # Entry stage


# ---------------------------------------------------------------------------
# Stage presence
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_funnel_stages_present(client):
    """
    The funnel response must contain all four canonical journey stages
    regardless of traffic volume.
    """
    response = await client.get("/stores/ST_FUNNEL_EMPTY/funnel")
    data = response.json()
    stage_names = [s["stage"] for s in data["stages"]]

    assert "Entry" in stage_names
    assert "Zone Browse" in stage_names
    assert "Billing Queue" in stage_names
    assert "Purchase" in stage_names


# ---------------------------------------------------------------------------
# Complete journey
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_funnel_complete_journey(client):
    """
    Seeding Entry, Zone Browse, and Billing Queue events for a single visitor
    should produce non-zero counts at each corresponding funnel stage.
    """
    store = "ST_FUNNEL_JOURNEY"
    visitor = "VIS_FUNNEL_001"

    events = [
        make_event(EventType.ENTRY, visitor_id=visitor, store_id=store),
        make_event(EventType.ZONE_ENTER, visitor_id=visitor, store_id=store, zone_id="Z1"),
        make_event(EventType.BILLING_QUEUE_JOIN, visitor_id=visitor, store_id=store, zone_id="BILLING"),
    ]
    payload = {"events": [e.model_dump(mode="json") for e in events]}
    r = await client.post("/events/ingest", json=payload)
    assert r.json()["accepted"] == 3

    response = await client.get(f"/stores/{store}/funnel")
    data = response.json()
    stages = {s["stage"]: s["count"] for s in data["stages"]}

    assert stages["Entry"] >= 1
    assert stages["Zone Browse"] >= 1
    assert stages["Billing Queue"] >= 1


# ---------------------------------------------------------------------------
# Monotonic dropoff invariant
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_funnel_dropoff_monotonic(client):
    """
    Each funnel stage count must be less than or equal to the count of the
    preceding stage (customers can only drop out, never appear from nowhere).
    """
    store = "ST_FUNNEL_DROPOFF"

    events: list = []

    # 5 visitors enter
    for i in range(5):
        v = f"VIS_DROP_{i:03d}"
        events.append(make_event(EventType.ENTRY, visitor_id=v, store_id=store))

    # 3 of them browse a zone
    for i in range(3):
        v = f"VIS_DROP_{i:03d}"
        events.append(make_event(EventType.ZONE_ENTER, visitor_id=v, store_id=store, zone_id="Z1"))

    # 2 of them reach the billing queue
    for i in range(2):
        v = f"VIS_DROP_{i:03d}"
        events.append(make_event(EventType.BILLING_QUEUE_JOIN, visitor_id=v, store_id=store, zone_id="BILLING"))

    payload = {"events": [e.model_dump(mode="json") for e in events]}
    await client.post("/events/ingest", json=payload)

    response = await client.get(f"/stores/{store}/funnel")
    data = response.json()
    counts = [s["count"] for s in data["stages"]]

    for i in range(1, len(counts)):
        assert counts[i] <= counts[i - 1], (
            f"Funnel stage {i} (count={counts[i]}) exceeds previous stage "
            f"(count={counts[i - 1]}) — funnel is not monotonically decreasing."
        )

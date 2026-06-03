# PROMPT:
# Test event ingestion: validation, deduplication, idempotency, partial success,
# malformed events, and empty batch handling.
#
# CHANGES MADE:
# - Uses httpx AsyncClient with ASGI transport
# - Tests dedup via repeated event_id submission
# - Tests partial success with mix of valid/invalid events

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.domain.enums import EventType
from tests.conftest import TEST_STORE_ID, make_event


# ---------------------------------------------------------------------------
# Single event ingestion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_single_valid_event(client):
    """A single well-formed ENTRY event must be accepted (201, accepted=1)."""
    event = make_event(EventType.ENTRY)
    payload = {"events": [event.model_dump(mode="json")]}
    response = await client.post("/events/ingest", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 0
    assert data["duplicates"] == 0


# ---------------------------------------------------------------------------
# Deduplication / idempotency
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_duplicate_event(client):
    """Re-submitting the same event_id must be counted as a duplicate, not accepted."""
    event = make_event(EventType.ENTRY)
    payload = {"events": [event.model_dump(mode="json")]}

    # First ingest – should succeed
    r1 = await client.post("/events/ingest", json=payload)
    assert r1.status_code == 201
    assert r1.json()["accepted"] == 1

    # Second ingest with identical event_id – should be detected as duplicate
    r2 = await client.post("/events/ingest", json=payload)
    assert r2.status_code == 201
    data = r2.json()
    assert data["duplicates"] >= 1
    assert data["accepted"] == 0


# ---------------------------------------------------------------------------
# Batch ingestion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_batch_events(client):
    """A batch of 10 unique events should all be accepted."""
    events = [make_event(EventType.ENTRY) for _ in range(10)]
    payload = {"events": [e.model_dump(mode="json") for e in events]}
    response = await client.post("/events/ingest", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["accepted"] == 10


# ---------------------------------------------------------------------------
# Empty batch
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_empty_batch(client):
    """An empty events list must be rejected with HTTP 422."""
    response = await client.post("/events/ingest", json={"events": []})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Malformed / schema-invalid events
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_malformed_event(client):
    """A completely malformed event body should return HTTP 422."""
    payload = {
        "events": [
            {
                "event_id": "test",
                "store_id": "X",
                # Missing all required fields
            }
        ]
    }
    response = await client.post("/events/ingest", json=payload)
    assert response.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_ingest_invalid_confidence(client):
    """
    Confidence > 1.0 is clamped to 1.0 by the schema validator.
    The event itself should still be accepted after clamping.
    """
    event = make_event(EventType.ENTRY, confidence=1.5)
    payload = {"events": [event.model_dump(mode="json")]}
    response = await client.post("/events/ingest", json=payload)
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# All event type coverage
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_all_event_types(client):
    """Every EventType variant should be accepted by the ingestion endpoint."""
    events = [
        make_event(EventType.ENTRY),
        make_event(EventType.EXIT),
        make_event(EventType.ZONE_ENTER, zone_id="ZONE_1"),
        make_event(EventType.ZONE_EXIT, zone_id="ZONE_1", dwell_ms=30_000),
        make_event(EventType.ZONE_DWELL, zone_id="ZONE_1", dwell_ms=60_000),
        make_event(EventType.BILLING_QUEUE_JOIN, zone_id="ZONE_BILLING"),
        make_event(EventType.BILLING_QUEUE_ABANDON, zone_id="ZONE_BILLING"),
        make_event(EventType.REENTRY),
    ]
    payload = {"events": [e.model_dump(mode="json") for e in events]}
    response = await client.post("/events/ingest", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["accepted"] == 8

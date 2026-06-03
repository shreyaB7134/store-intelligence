# PROMPT:
# Test anomaly detection: queue spike, dead zone, conversion drop.
# Tests cover severity levels and suggested_action presence.
#
# CHANGES MADE:
# - Seeds extreme queue depth to trigger spike
# - Verifies anomaly schema has all required fields

from __future__ import annotations

import pytest

from app.domain.enums import EventType
from tests.conftest import make_event


# ---------------------------------------------------------------------------
# Empty store baseline
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_anomalies_empty_store(client):
    """
    An empty store must return a 200 with an 'anomalies' list (possibly empty,
    or containing only informational dead-zone observations).
    """
    response = await client.get("/stores/ST_ANOMALY_EMPTY/anomalies")
    assert response.status_code == 200
    data = response.json()
    assert "anomalies" in data
    assert isinstance(data["anomalies"], list)


# ---------------------------------------------------------------------------
# Anomaly schema validation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_anomaly_schema(client):
    """
    Every anomaly object in the response must include all mandatory fields with
    the correct types and enumerated severity values.
    """
    store = "ST_ANOMALY_SCHEMA"

    # Seed 15 queue-join events with escalating queue_depth to trigger a spike
    events = []
    for i in range(15):
        events.append(make_event(
            EventType.BILLING_QUEUE_JOIN,
            store_id=store,
            zone_id="BILLING",
            queue_depth=i + 1,
        ))
    payload = {"events": [e.model_dump(mode="json") for e in events]}
    await client.post("/events/ingest", json=payload)

    response = await client.get(f"/stores/{store}/anomalies")
    data = response.json()

    for anomaly in data.get("anomalies", []):
        # Every anomaly must have all five required fields
        assert "anomaly_type" in anomaly, "Missing 'anomaly_type'"
        assert "severity" in anomaly, "Missing 'severity'"
        assert "message" in anomaly, "Missing 'message'"
        assert "suggested_action" in anomaly, "Missing 'suggested_action'"
        assert "detected_at" in anomaly, "Missing 'detected_at'"

        # Severity must be one of the three canonical values
        assert anomaly["severity"] in ("INFO", "WARN", "CRITICAL"), (
            f"Unexpected severity value: {anomaly['severity']}"
        )


# ---------------------------------------------------------------------------
# 200 status for any store
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_anomalies_endpoint_returns_200(client):
    """
    The anomalies endpoint must always return HTTP 200 even if no anomalies
    have been detected.
    """
    response = await client.get("/stores/ST_TEST/anomalies")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dead_zone_anomaly(client):
    """
    Ingest a zone event that happened in the past (e.g., 2 hours ago)
    and check that the anomalies endpoint correctly reports a dead zone.
    """
    from datetime import datetime, timezone, timedelta
    store = "ST_DEAD_ZONE"

    # 2 hours ago in UTC
    past_time = datetime.now(timezone.utc) - timedelta(hours=2)

    # Seed a zone entry event
    event = make_event(
        EventType.ZONE_ENTER,
        store_id=store,
        zone_id="ZONE_SHELF_A",
        timestamp=past_time
    )
    payload = {"events": [event.model_dump(mode="json")]}
    await client.post("/events/ingest", json=payload)

    response = await client.get(f"/stores/{store}/anomalies")
    assert response.status_code == 200
    data = response.json()

    dead_zone_anomalies = [
        a for a in data["anomalies"] if a["anomaly_type"] == "DEAD_ZONE"
    ]
    assert len(dead_zone_anomalies) > 0, "No dead zone anomaly detected"

    a = dead_zone_anomalies[0]
    assert a["severity"] in ("WARN", "CRITICAL")
    assert "ZONE_SHELF_A" in a["message"]


@pytest.mark.asyncio
async def test_detect_anomalies_direct(db_session):
    from app.services.anomaly import detect_anomalies
    from app.infrastructure.repositories import EventRepository
    from datetime import datetime, timezone, timedelta
    from app.domain.enums import EventType
    from tests.conftest import make_event
    
    store = "ST_ANOMALY_DIRECT"
    repo = EventRepository(db_session)
    
    past_time = datetime.now(timezone.utc) - timedelta(hours=2)
    event = make_event(
        EventType.ZONE_ENTER,
        store_id=store,
        zone_id="ZONE_DIRECT",
        timestamp=past_time
    )
    await repo.upsert(event)
    await db_session.commit()
    
    res = await detect_anomalies(db_session, store)
    assert res.store_id == store
    assert len(res.anomalies) > 0
    assert res.anomalies[0].anomaly_type.value == "DEAD_ZONE"



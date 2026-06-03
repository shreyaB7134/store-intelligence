"""
Load sample events from sample_events.jsonl into the Intelligence API.
This is useful for demo/testing without running the full video pipeline.
"""
from __future__ import annotations
import asyncio
import json
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
import httpx

logger = logging.getLogger(__name__)

SAMPLE_EVENTS_PATH = Path("../sample_eventsbe42122.jsonl")
API_URL = "http://localhost:8000"
STORE_ID = "ST1008"
CAMERA_ID = "CAM1"


def parse_sample_event(raw: dict) -> dict | None:
    """Convert sample_events.jsonl format to StoreEvent schema."""
    event_type_map = {
        "entry": "ENTRY",
        "exit": "EXIT",
        "zone_entered": "ZONE_ENTER",
        "zone_exited": "ZONE_EXIT",
        "queue_completed": "BILLING_QUEUE_JOIN",
        "queue_abandoned": "BILLING_QUEUE_ABANDON",
    }

    raw_type = raw.get("event_type", "")
    event_type = event_type_map.get(raw_type)
    if not event_type:
        return None

    # Get timestamp
    ts_str = raw.get("event_timestamp") or raw.get("event_time") or raw.get("queue_join_ts")
    if not ts_str:
        return None

    try:
        ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    # Visitor ID
    visitor_id = (
        raw.get("id_token")
        or f"VIS_{raw.get('track_id', uuid.uuid4().hex[:8])}"
    )

    # Zone
    zone_id = raw.get("zone_id")

    # Queue depth
    queue_depth = raw.get("queue_position_at_join")

    # Staff
    is_staff = raw.get("is_staff", False)

    return {
        "event_id": raw.get("queue_event_id") or str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": raw.get("camera_id") or CAMERA_ID,
        "visitor_id": str(visitor_id),
        "event_type": event_type,
        "timestamp": ts.isoformat(),
        "zone_id": zone_id,
        "dwell_ms": 0,
        "is_staff": is_staff,
        "confidence": 0.9,
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": None,
            "session_seq": 0,
        }
    }


async def load_sample_data(
    jsonl_path: str | Path = SAMPLE_EVENTS_PATH,
    api_url: str = API_URL,
) -> dict:
    path = Path(jsonl_path)
    if not path.exists():
        logger.error("Sample events file not found: %s", path)
        return {"error": "file not found"}

    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                event = parse_sample_event(raw)
                if event:
                    events.append(event)
            except json.JSONDecodeError as e:
                logger.warning("Skipping malformed line: %s", e)

    if not events:
        logger.warning("No valid events found")
        return {"accepted": 0}

    logger.info("Sending %d events to API...", len(events))

    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                f"{api_url}/events/ingest",
                json={"events": events},
                timeout=30.0,
            )
            result = r.json()
            logger.info("Result: %s", result)
            return result
        except Exception as e:
            logger.error("Failed to send events: %s", e)
            return {"error": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(load_sample_data())

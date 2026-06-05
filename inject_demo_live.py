import time
import httpx
import uuid
from datetime import datetime, timezone

API_URL = "https://store-intelligence.onrender.com"

def send_events(events):
    try:
        r = httpx.post(f"{API_URL}/events/ingest", json={"events": events}, timeout=180.0)
        print(f"Sent {len(events)} events: {r.status_code}")
    except Exception as e:
        print(f"Failed to send: {e}")

for store_id in ["ST1008", "ST1009", "STORE_BLR_002"]:
    print(f"Injecting data for {store_id}...")
    visitors = [f"DEM_{uuid.uuid4().hex[:4]}" for _ in range(5)]

    # Send entries
    entries = []
    for v in visitors:
        entries.append({
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM1",
            "visitor_id": v,
            "event_type": "ENTRY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_staff": False
        })
    send_events(entries)

    time.sleep(2)

    # Send zone enter
    zones = []
    for v in visitors[:3]:
        zones.append({
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM2",
            "visitor_id": v,
            "event_type": "ZONE_ENTER",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": "LIPSTICKS",
            "is_staff": False
        })
    send_events(zones)

    time.sleep(2)

    # Send queue joins
    queues = []
    for v in visitors[:2]:
        queues.append({
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM3",
            "visitor_id": v,
            "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_staff": False
        })
    send_events(queues)

    time.sleep(2)

print("Demo injection complete.")

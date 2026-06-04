import time
import httpx
import uuid
from datetime import datetime, timezone

API_URL = "https://store-intelligence.onrender.com"
STORE_ID = "ST1008"

def send_events(events):
    try:
        r = httpx.post(f"{API_URL}/events/ingest", json={"events": events}, timeout=60.0)
        print(f"Sent {len(events)} events: {r.status_code}")
    except Exception as e:
        print(f"Failed to send: {e}")

visitors = [f"DEMO_{uuid.uuid4().hex[:4]}" for _ in range(5)]

# Send entries
entries = []
for v in visitors:
    entries.append({
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
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
        "store_id": STORE_ID,
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
        "store_id": STORE_ID,
        "camera_id": "CAM3",
        "visitor_id": v,
        "event_type": "BILLING_QUEUE_JOIN",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_staff": False
    })
send_events(queues)

print("Demo injection complete.")

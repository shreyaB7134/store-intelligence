import time
import httpx
import uuid
import sys
from datetime import datetime, timezone

API_URL = "https://store-intelligence.onrender.com"

def send_events(events):
    try:
        r = httpx.post(f"{API_URL}/events/ingest", json={"events": events}, timeout=60.0)
        print(f"Sent {len(events)} events: {r.status_code}")
        sys.stdout.flush()
    except Exception as e:
        print(f"Failed to send: {e}")
        sys.stdout.flush()

print("Starting infinite demo injection...", flush=True)

while True:
    for store_id in ["ST1008", "ST1009", "STORE_BLR_002"]:
        print(f"Injecting for {store_id}...", flush=True)
        visitors = [f"DEM_{uuid.uuid4().hex[:4]}" for _ in range(5)]
        
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
        time.sleep(1)
        
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
        time.sleep(1)
        
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
        time.sleep(1)
    
    # Send an EXIT event for some visitors to show turnover
    for store_id in ["ST1008", "ST1009", "STORE_BLR_002"]:
        send_events([{
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM_EXIT",
            "visitor_id": visitors[0],
            "event_type": "EXIT",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_staff": False
        }])
        
    print("Sleeping for 15 seconds...", flush=True)
    time.sleep(15)

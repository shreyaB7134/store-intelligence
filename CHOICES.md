# Technical Choices - Store Intelligence Platform

## Decision 1: Detection Model

### Options Considered

| Option | Pros | Cons |
|---|---|---|
| YOLOv8n | Fast (3ms GPU), small (6MB), ByteTrack native | Lower mAP than larger models |
| YOLOv8s | Better accuracy | 2× slower, 2× larger |
| YOLOv8l | Best accuracy | Not suitable for edge/CPU |
| RT-DETR | Transformer-based, accurate | High compute requirement |
| MobileNet-SSD | Very fast, tiny | Outdated, lower accuracy |

### AI Recommendation

GPT-4 and Claude analysis both recommended **YOLOv8n** for retail edge deployment:
> "For a store with 10-30 people simultaneously visible, YOLOv8n provides sufficient detection accuracy (mAP@50 = 37.3 on COCO). The speed advantage is critical for real-time tracking — frame processing must complete within 1/FPS seconds."

### Final Choice: YOLOv8n

**Justification:**
- 10 FPS processing target is achievable on CPU (40ms/frame)
- Native integration with ByteTrack via ultralytics
- Automatic fallback to RT-DETR implemented in code
- Model size allows Docker image < 2GB

---

## Decision 2: Event Schema

### Options Considered

**Option A: Flat Schema**
- All fields at top level
- Simple to query
- Problem: Schema migration is disruptive

**Option B: Hybrid Schema (Chosen)**
- Core immutable fields at top level
- Extensible `metadata` object for event-specific data
- Pattern used by Segment, Amplitude, Mixpanel

**Option C: Fully Nested Schema**
- Maximum flexibility
- Problem: Complex queries, poor DB indexing

### AI Recommendation

> "Use a hybrid schema: stable core fields (event_id, store_id, visitor_id, timestamp, event_type) for indexing, with a metadata envelope for event-specific data. This mirrors industry standards used by Segment.io and Google Analytics 4."

### Final Choice: Hybrid Schema

```json
{
  "event_id": "uuid",
  "store_id": "string",
  "camera_id": "string",
  "visitor_id": "string",
  "event_type": "enum",
  "timestamp": "datetime",
  "zone_id": "string|null",
  "dwell_ms": "int",
  "is_staff": "bool",
  "confidence": "float",
  "metadata": {
    "queue_depth": "int|null",
    "sku_zone": "string|null",
    "session_seq": "int"
  }
}
```

**Justification:**
- Pydantic enforces schema at ingest time
- Core fields are indexed in PostgreSQL
- `metadata` allows adding fields without migrations
- `is_staff` on every event enables universal filtering

---

## Decision 3: API Architecture

### Options Considered

| Option | Pros | Cons |
|---|---|---|
| FastAPI (async) | High throughput, native asyncio, auto docs | Newer ecosystem |
| Flask | Familiar, large ecosystem | Synchronous by default |
| Django REST | Batteries included, ORM | Too heavy for this use case |
| gRPC | Maximum performance | Complex client integration |

### AI Recommendation

> "For an analytics API handling event ingestion at high throughput with PostgreSQL async queries, FastAPI with asyncpg is the optimal choice. The async-first design allows handling 2000+ events/sec on a single worker. The automatic OpenAPI documentation is critical for developer adoption."

### Final Choice: FastAPI + asyncpg

**Justification:**
- `async def` handlers + `asyncpg` = non-blocking DB queries
- Pydantic v2 validation at the boundary (auto-documented)
- Sub-millisecond overhead vs Django's 20-50ms middleware stack
- Auto-generated `/docs` Swagger UI for demo purposes
- Dependency injection makes testing trivial (override `get_db`)

**Architectural patterns used:**
- Repository pattern (EventRepository, POSRepository)
- Dependency injection (FastAPI Depends)
- Service layer separation (analytics.py, anomaly.py)
- In-memory deduplication + DB upsert for idempotency

---

## Decision 4: Tracking Algorithm

### Options Considered

| Option | MOTA | Speed | ReID Dependency |
|---|---|---|---|
| ByteTrack | 80.3 | Fast | No |
| DeepSORT | 75.8 | Medium | Yes (OSNet) |
| SORT | 59.8 | Very Fast | No |
| StrongSORT | 79.6 | Medium | Yes |

### Final Choice: ByteTrack

ByteTrack's key innovation: treats low-confidence detections as "second candidates" instead of discarding them. This is crucial in retail where people briefly occlude each other.

---

## Decision 5: Re-Identification

### Options Considered

1. **OSNet-x0.25** - Lightweight CNN trained for person ReID (chosen primary)
2. **Color histogram** - No deep learning required (fallback)
3. **Trajectory similarity** - Position-based matching (supplementary)
4. **Face recognition** - High accuracy, privacy concerns, GDPR issues

### Final Choice: OSNet + Histogram fallback

**Privacy consideration:** We explicitly avoided face recognition. OSNet uses full-body appearance only — no biometric data.

---

## Decision 6: Database

### Options Considered

| DB | Type | Pros | Cons |
|---|---|---|---|
| PostgreSQL | Relational | ACID, SQL, familiar | Not optimized for time-series |
| InfluxDB | Time-series | Perfect for metrics | No relational joins |
| TimescaleDB | Hybrid | Best of both | Complexity |
| MongoDB | Document | Flexible schema | Weak consistency |

### Final Choice: PostgreSQL 16

POS correlation requires joining events with transactions — a relational problem. PostgreSQL's composite indexes and window functions handle analytics queries efficiently enough for store-scale data volumes (< 100K events/day per store).

---

## Decision 7: Zone Classification Approach

### Options Considered

| Option | Pros | Cons |
|---|---|---|
| Rule-based (HSV + Polygons) | Deterministic, ultra-low latency, zero marginal cost | Requires manual initial configuration per camera |
| Vision-Language Models (VLM) | Zero-shot layout understanding, dynamic adjustment | High latency (>1s), expensive per frame, non-deterministic |

### AI Evaluation & Disagreement

During the design phase, an AI architecture review suggested using a VLM (like GPT-4V or Claude 3 Vision) to dynamically classify zones (e.g., "Billing Counter", "Lipstick Aisle") from raw camera frames in real-time. 

**Why we disagreed:**
While the zero-shot spatial reasoning of VLMs is impressive, passing CCTV frames to a VLM for zone classification is fundamentally unsuited for a real-time tracking pipeline. It introduces massive latency (often >1-2 seconds per request), unpredictable non-deterministic boundaries, and exorbitant per-frame API costs. 

### Final Choice: Rule-Based (HSV & Polygons)

**Justification:**
Instead of a VLM, we implemented deterministic polygonal boundary checks in `zone_manager.py` (e.g., `Point(x, y).within(polygon)`) and deterministic HSV color thresholding in `staff_classifier.py`. This executes in <1ms per frame directly on the edge device with zero recurring cloud API costs, satisfying the strict 10+ FPS performance requirement for the ByteTrack pipeline.

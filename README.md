# Store Intelligence Platform

> Production-grade retail analytics platform powered by computer vision, real-time event streaming, and intelligent anomaly detection.

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)](https://fastapi.tiangolo.com)
[![YOLOv8](https://img.shields.io/badge/YOLOv8-ultralytics-red)](https://ultralytics.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue)](https://postgresql.org)
[![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-orange)](https://streamlit.io)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   STORE INTELLIGENCE PLATFORM                   │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐  │
│  │  CCTV Feeds  │───►│ Detection Layer  │───►│  Event Bus   │  │
│  │  (mp4/rtsp)  │    │ YOLOv8+ByteTrack │    │  REST API    │  │
│  └──────────────┘    └──────────────────┘    └──────┬───────┘  │
│                                                      │          │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────▼───────┐  │
│  │  POS CSV     │───►│ POS Correlator   │───►│  PostgreSQL  │  │
│  └──────────────┘    └──────────────────┘    └──────┬───────┘  │
│                                                      │          │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────▼───────┐  │
│  │  Dashboard   │◄───│  Analytics API   │◄───│  Anomaly     │  │
│  │  (Streamlit) │    │  FastAPI         │    │  Detector    │  │
│  └──────────────┘    └──────────────────┘    └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Technology | Purpose |
|---|---|---|
| Detection | YOLOv8n | Real-time person detection |
| Tracking | ByteTrack | Multi-object tracking with occlusion handling |
| ReID | OSNet / Histogram | Re-entry visitor identification |
| API | FastAPI + asyncpg | High-throughput event ingestion & analytics |
| Database | PostgreSQL 16 | ACID-compliant analytics storage |
| Dashboard | Streamlit + Plotly | Live visual analytics |

## Quick Start

### Prerequisites

- Docker Desktop 24.0+
- Docker Compose 2.0+
- 8GB RAM minimum

### 1. Clone and Configure

```bash
git clone <repo-url>
cd store-intelligence
cp .env.example .env
# Edit .env if needed (defaults work out of the box)
```

### 2. Start All Services

```bash
docker compose up
```

This starts:
- **PostgreSQL** on port 5432
- **Intelligence API** on port 8000
- **Live Dashboard** on port 8501

### 3. Access the Platform

| Service | URL |
|---|---|
| API Documentation | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |
| Live Dashboard | http://localhost:8501 |

## API Reference

### POST /events/ingest

Ingest store events with validation, deduplication, and partial success support.

```bash
curl -X POST http://localhost:8000/events/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "store_id": "ST1008",
        "camera_id": "CAM_1",
        "visitor_id": "VIS_ABC123",
        "event_type": "ENTRY",
        "timestamp": "2026-03-08T18:10:05.120000Z",
        "is_staff": false,
        "confidence": 0.92,
        "metadata": {"queue_depth": null, "sku_zone": null, "session_seq": 1}
      }
    ]
  }'
```

**Response:**
```json
{
  "accepted": 1,
  "rejected": 0,
  "duplicates": 0,
  "errors": []
}
```

### GET /stores/{store_id}/metrics

```bash
curl http://localhost:8000/stores/ST1008/metrics
```

```json
{
  "store_id": "ST1008",
  "unique_visitors": 142,
  "conversion_rate": 0.34,
  "average_dwell_ms": 847500,
  "queue_depth": 3,
  "abandonment_rate": 0.12
}
```

### GET /stores/{store_id}/funnel

```bash
curl http://localhost:8000/stores/ST1008/funnel
```

```json
{
  "store_id": "ST1008",
  "stages": [
    {"stage": "Entry", "count": 142, "dropoff_pct": 0.0},
    {"stage": "Zone Browse", "count": 98, "dropoff_pct": 30.99},
    {"stage": "Billing Queue", "count": 52, "dropoff_pct": 46.94},
    {"stage": "Purchase", "count": 48, "dropoff_pct": 7.69}
  ]
}
```

### GET /stores/{store_id}/heatmap

```bash
curl http://localhost:8000/stores/ST1008/heatmap
```

### GET /stores/{store_id}/anomalies

```bash
curl http://localhost:8000/stores/ST1008/anomalies
```

```json
{
  "store_id": "ST1008",
  "anomalies": [
    {
      "anomaly_type": "QUEUE_SPIKE",
      "severity": "CRITICAL",
      "message": "Queue depth 15 is 3.0x historical average (5.0)",
      "suggested_action": "Deploy additional billing staff immediately.",
      "detected_at": "2026-03-08T18:30:00Z"
    }
  ]
}
```

### GET /health

```bash
curl http://localhost:8000/health
```

## Running Tests

```bash
# Install test dependencies
pip install -r requirements.test.txt

# Run full test suite
pytest tests/ -v --cov=app --cov-report=term-missing

# Run specific test files
pytest tests/test_ingestion.py -v
pytest tests/test_metrics.py -v
pytest tests/test_anomalies.py -v
```

## Running the Detection Pipeline

```bash
# Install pipeline dependencies
pip install -r requirements.pipeline.txt

# Process a single video
python -m pipeline.video_processor \
  --store-id ST1008 \
  --camera-id CAM1 \
  --video-path "Store 1/CAM 3 - entry.mp4" \
  --api-url http://localhost:8000
```

## Loading POS Data

```python
import asyncio
from app.infrastructure.database import get_db_session
from app.services.pos_correlator import load_pos_data

async def main():
    async with get_db_session() as session:
        count = await load_pos_data(session, "POS - sample transactions.csv")
        print(f"Loaded {count} POS transactions")

asyncio.run(main())
```

## Project Structure

```
store-intelligence/
├── app/                    # FastAPI application
│   ├── api/
│   │   ├── middleware.py   # Structured logging, trace IDs
│   │   └── routers/        # API endpoint handlers
│   ├── domain/
│   │   ├── enums.py        # EventType, Severity, etc.
│   │   ├── models.py       # SQLAlchemy ORM models
│   │   └── schemas.py      # Pydantic validation schemas
│   ├── infrastructure/
│   │   ├── database.py     # Async DB engine & session
│   │   └── repositories.py # Data access layer
│   └── services/
│       ├── analytics.py    # Metrics & funnel computation
│       ├── anomaly.py      # Anomaly detection engine
│       ├── deduplication.py # LRU event dedup cache
│       └── pos_correlator.py # POS ↔ visitor matching
├── pipeline/               # Computer vision pipeline
│   ├── detector.py         # YOLOv8 person detection
│   ├── tracker.py          # ByteTrack multi-object tracking
│   ├── zone_manager.py     # Polygon zone detection
│   ├── reid_engine.py      # Re-entry identification
│   ├── staff_classifier.py # Staff vs customer detection
│   ├── queue_detector.py   # Billing queue estimation
│   └── event_emitter.py    # Batch event emitter
├── dashboard/
│   └── app.py              # Streamlit live dashboard
├── tests/                  # pytest test suite
├── sql/
│   └── init.sql            # PostgreSQL initialization
├── docker-compose.yml      # Full stack deployment
├── Dockerfile.api          # API service container
├── Dockerfile.dashboard    # Dashboard container
├── .env.example            # Environment template
├── README.md
├── DESIGN.md
└── CHOICES.md
```

## Troubleshooting

### Database connection refused
```bash
# Check PostgreSQL is healthy
docker compose ps
docker compose logs postgres

# Wait for health check to pass
docker compose up --wait
```

### API returns 503
```bash
# Check API logs
docker compose logs api

# Verify DB is reachable
curl http://localhost:8000/health
```

### Dashboard not loading
```bash
docker compose logs dashboard
# Check API is running first
curl http://localhost:8000/health
```

### Pipeline GPU not detected
The pipeline defaults to CPU inference. Set `CUDA_VISIBLE_DEVICES=0` in your environment to enable GPU.

### Tests failing with DB errors
Tests use SQLite in-memory - no PostgreSQL required. Ensure `aiosqlite` is installed:
```bash
pip install aiosqlite
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | See .env.example | PostgreSQL connection string |
| `STORE_ID` | `ST1008` | Default store identifier |
| `QUEUE_SPIKE_MULTIPLIER` | `2.0` | Queue spike detection threshold |
| `CONVERSION_DROP_THRESHOLD` | `0.5` | Conversion drop alert threshold |
| `DEAD_ZONE_MINUTES` | `30` | Minutes before zone is "dead" |
| `POS_MATCH_WINDOW_SECONDS` | `300` | POS correlation window (5 min) |
| `DASHBOARD_REFRESH_SECONDS` | `5` | Dashboard auto-refresh interval |

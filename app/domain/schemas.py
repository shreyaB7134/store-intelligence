from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from app.domain.enums import EventType, Severity, AnomalyType


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = 0


class StoreEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: EventType
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = Field(default=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator('event_id')
    @classmethod
    def validate_event_id(cls, v: str) -> str:
        if not v or not v.strip():
            return str(uuid.uuid4())
        return v

    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    model_config = {"from_attributes": True}


class IngestRequest(BaseModel):
    events: list[StoreEvent]


class IngestResult(BaseModel):
    accepted: int
    rejected: int
    duplicates: int
    errors: list[str] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    store_id: str
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    unique_visitors: int
    conversion_rate: float
    average_dwell_ms: float
    queue_depth: int
    abandonment_rate: float


class FunnelStage(BaseModel):
    stage: str
    count: int
    dropoff_pct: float


class FunnelResponse(BaseModel):
    store_id: str
    stages: list[FunnelStage]


class ZoneScore(BaseModel):
    zone_id: str
    score: float
    visit_count: int
    avg_dwell_ms: float


class HeatmapResponse(BaseModel):
    store_id: str
    zones: list[ZoneScore]
    data_confidence: bool


class AnomalyItem(BaseModel):
    anomaly_type: AnomalyType
    severity: Severity
    message: str
    suggested_action: str
    detected_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnomaliesResponse(BaseModel):
    store_id: str
    anomalies: list[AnomalyItem]


class HealthResponse(BaseModel):
    status: str
    database: str
    last_event_timestamp: Optional[datetime]
    stale_feed: bool
    stale_feed_threshold_seconds: int
    uptime_seconds: float

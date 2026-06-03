"""
Event generation and emission to the Intelligence API.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
import httpx
from app.domain.schemas import StoreEvent, EventMetadata, IngestRequest
from app.domain.enums import EventType

logger = logging.getLogger(__name__)


class EventEmitter:
    """
    Creates and sends StoreEvent objects to the ingest API.
    Supports batching for efficiency.
    """

    def __init__(
        self,
        api_base_url: str = "http://localhost:8000",
        batch_size: int = 50,
        flush_interval_seconds: float = 1.0,
    ):
        self._api_url = api_base_url
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds
        self._pending: list[StoreEvent] = []
        self._client: Optional[httpx.AsyncClient] = None
        self._total_emitted = 0
        self._total_failed = 0

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, *args):
        await self.flush()
        if self._client:
            await self._client.aclose()

    def create_event(
        self,
        event_type: EventType,
        visitor_id: str,
        store_id: str,
        camera_id: str,
        zone_id: Optional[str] = None,
        dwell_ms: int = 0,
        is_staff: bool = False,
        confidence: float = 1.0,
        queue_depth: Optional[int] = None,
        sku_zone: Optional[str] = None,
        session_seq: int = 0,
        timestamp: Optional[datetime] = None,
    ) -> StoreEvent:
        return StoreEvent(
            event_id=str(uuid.uuid4()),
            store_id=store_id,
            camera_id=camera_id,
            visitor_id=visitor_id,
            event_type=event_type,
            timestamp=timestamp or datetime.now(timezone.utc),
            zone_id=zone_id,
            dwell_ms=dwell_ms,
            is_staff=is_staff,
            confidence=confidence,
            metadata=EventMetadata(
                queue_depth=queue_depth,
                sku_zone=sku_zone,
                session_seq=session_seq,
            ),
        )

    def emit(self, event: StoreEvent) -> None:
        """Queue event for batch sending."""
        self._pending.append(event)
        if len(self._pending) >= self._batch_size:
            # Schedule flush without blocking
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.flush())
            except RuntimeError:
                pass  # No event loop running

    async def flush(self) -> None:
        """Send all pending events to the API."""
        if not self._pending or not self._client:
            return

        batch = self._pending.copy()
        self._pending.clear()

        try:
            payload = IngestRequest(events=batch)
            response = await self._client.post(
                f"{self._api_url}/events/ingest",
                json=payload.model_dump(mode="json"),
                timeout=10.0,
            )
            if response.status_code == 201:
                result = response.json()
                self._total_emitted += result.get("accepted", 0)
                logger.debug(
                    "Emitted %d events (accepted=%d, dupes=%d)",
                    len(batch), result.get("accepted", 0), result.get("duplicates", 0)
                )
            else:
                logger.warning(
                    "API returned %d for batch of %d events",
                    response.status_code, len(batch)
                )
                self._total_failed += len(batch)
        except Exception as e:
            logger.error("Failed to emit %d events: %s", len(batch), e)
            self._total_failed += len(batch)

    @property
    def stats(self) -> dict:
        return {
            "total_emitted": self._total_emitted,
            "total_failed": self._total_failed,
            "pending": len(self._pending),
        }

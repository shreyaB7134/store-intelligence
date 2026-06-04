from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import EventType
from app.domain.models import EventRecord, POSTransaction, VisitorSession
from app.domain.schemas import StoreEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EventRepository
# ---------------------------------------------------------------------------

class EventRepository:
    """
    Data-access layer for camera/sensor events and derived visitor sessions.

    All methods are coroutines that execute against the injected
    ``AsyncSession``. The caller is responsible for committing / rolling back
    the session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def upsert(self, event: StoreEvent) -> bool:
        """
        Idempotently persist *event* to ``event_records``.

        Uses a PostgreSQL ``INSERT … ON CONFLICT DO NOTHING`` keyed on
        ``event_id`` so that duplicate deliveries are silently dropped.

        Returns:
            ``True`` if the row was newly inserted, ``False`` if it was a
            duplicate.
        """
        stmt = (
            pg_insert(EventRecord)
            .values(
                event_id=event.event_id,
                store_id=event.store_id,
                camera_id=event.camera_id,
                visitor_id=event.visitor_id,
                event_type=event.event_type.value,
                timestamp=event.timestamp,
                zone_id=event.zone_id,
                dwell_ms=event.dwell_ms,
                is_staff=event.is_staff,
                confidence=event.confidence,
                queue_depth=event.metadata.queue_depth,
                sku_zone=event.metadata.sku_zone,
                session_seq=event.metadata.session_seq,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        result = await self.session.execute(stmt)
        was_new = result.rowcount > 0

        if was_new:
            await self._upsert_visitor_session(event)

        return was_new

    async def _upsert_visitor_session(self, event: StoreEvent) -> None:
        """
        Keep the ``visitor_sessions`` table in sync whenever a new event
        arrives for a visitor.

        * Inserts the session row if it does not yet exist (keyed on the
          ``uq_visitor_store`` unique constraint).
        * Updates ``entry_time`` / ``exit_time`` / ``visited_billing`` based
          on the event type.
        """
        # Ensure the session row exists before we try to update it.
        insert_stmt = (
            pg_insert(VisitorSession)
            .values(
                visitor_id=event.visitor_id,
                store_id=event.store_id,
                is_staff=event.is_staff,
            )
            .on_conflict_do_nothing(index_elements=["visitor_id", "store_id"])
        )
        await self.session.execute(insert_stmt)

        # Apply field-level updates based on the incoming event type.
        base_where = and_(
            VisitorSession.visitor_id == event.visitor_id,
            VisitorSession.store_id == event.store_id,
        )

        if event.event_type == EventType.ENTRY:
            await self.session.execute(
                update(VisitorSession)
                .where(base_where)
                .values(entry_time=event.timestamp)
            )

        elif event.event_type == EventType.EXIT:
            await self.session.execute(
                update(VisitorSession)
                .where(base_where)
                .values(exit_time=event.timestamp)
            )

        elif event.event_type in (EventType.ZONE_ENTER, EventType.ZONE_DWELL):
            # Mark the billing zone flag when the visitor steps into any zone
            # whose ID contains "BILLING" (case-insensitive).
            if event.zone_id and "BILLING" in event.zone_id.upper():
                await self.session.execute(
                    update(VisitorSession)
                    .where(base_where)
                    .values(visited_billing=True)
                )

    # ------------------------------------------------------------------
    # Feed-health queries
    # ------------------------------------------------------------------

    async def get_last_event_timestamp(self, store_id: str) -> Optional[datetime]:
        """Return the most-recent event timestamp for *store_id*, or ``None``."""
        result = await self.session.execute(
            select(func.max(EventRecord.timestamp)).where(
                EventRecord.store_id == store_id
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Aggregation queries
    # ------------------------------------------------------------------

    async def count_events_by_type(
        self,
        store_id: str,
        event_type: EventType,
        since: Optional[datetime] = None,
    ) -> int:
        """
        Count non-staff events of *event_type* for *store_id*.

        Args:
            since: If supplied, only events at or after this timestamp are
                counted.
        """
        q = select(func.count(EventRecord.id)).where(
            EventRecord.store_id == store_id,
            EventRecord.event_type == event_type.value,
            EventRecord.is_staff == False,  # noqa: E712
        )
        if since:
            q = q.where(EventRecord.timestamp >= since)
        result = await self.session.execute(q)
        return result.scalar_one() or 0

    async def get_unique_visitor_count(
        self,
        store_id: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> int:
        """Count distinct non-staff visitors who have an ENTRY event."""
        q = select(func.count(distinct(EventRecord.visitor_id))).where(
            EventRecord.store_id == store_id,
            EventRecord.is_staff == False,  # noqa: E712
            EventRecord.event_type == EventType.ENTRY.value,
        )
        if since:
            q = q.where(EventRecord.timestamp >= since)
        if until:
            q = q.where(EventRecord.timestamp <= until)
        result = await self.session.execute(q)
        return result.scalar_one() or 0

    async def get_total_sessions(self, store_id: str) -> int:
        """Count the total number of unique visitor sessions stored for store_id."""
        q = select(func.count(VisitorSession.id)).where(
            VisitorSession.store_id == store_id
        )
        result = await self.session.execute(q)
        return result.scalar_one() or 0

    async def get_average_dwell(
        self,
        store_id: str,
        since: Optional[datetime] = None,
    ) -> float:
        """
        Return the mean dwell duration (milliseconds) across all non-staff
        ``ZONE_DWELL`` events with a positive ``dwell_ms`` value.
        """
        q = select(func.avg(EventRecord.dwell_ms)).where(
            EventRecord.store_id == store_id,
            EventRecord.is_staff == False,  # noqa: E712
            EventRecord.event_type == EventType.ZONE_DWELL.value,
            EventRecord.dwell_ms > 0,
        )
        if since:
            q = q.where(EventRecord.timestamp >= since)
        result = await self.session.execute(q)
        return float(result.scalar_one() or 0.0)

    async def get_queue_depth(self, store_id: str) -> int:
        """
        Estimate the current billing-queue depth.

        Computes ``(queue_joins − queue_abandons)`` over the most recent
        15-minute rolling window and clamps the result to zero.
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=15)

        joins_result = await self.session.execute(
            select(func.count(EventRecord.id)).where(
                EventRecord.store_id == store_id,
                EventRecord.event_type == EventType.BILLING_QUEUE_JOIN.value,
                EventRecord.timestamp >= window_start,
            )
        )
        abandons_result = await self.session.execute(
            select(func.count(EventRecord.id)).where(
                EventRecord.store_id == store_id,
                EventRecord.event_type == EventType.BILLING_QUEUE_ABANDON.value,
                EventRecord.timestamp >= window_start,
            )
        )

        joins = joins_result.scalar_one() or 0
        abandons = abandons_result.scalar_one() or 0
        return max(0, joins - abandons)

    async def get_zone_stats(
        self,
        store_id: str,
        since: Optional[datetime] = None,
    ) -> list[dict]:
        """
        Return per-zone visit counts and average dwell times, ordered by
        visit count descending.

        Each dict has keys: ``zone_id``, ``visit_count``, ``avg_dwell_ms``.
        """
        q = (
            select(
                EventRecord.zone_id,
                func.count(EventRecord.id).label("visit_count"),
                func.avg(EventRecord.dwell_ms).label("avg_dwell_ms"),
            )
            .where(
                EventRecord.store_id == store_id,
                EventRecord.zone_id.isnot(None),
                EventRecord.is_staff == False,  # noqa: E712
                EventRecord.event_type.in_(
                    [EventType.ZONE_ENTER.value, EventType.ZONE_DWELL.value]
                ),
            )
            .group_by(EventRecord.zone_id)
            .order_by(func.count(EventRecord.id).desc())
        )
        if since:
            q = q.where(EventRecord.timestamp >= since)
        result = await self.session.execute(q)
        return [
            {
                "zone_id": row.zone_id,
                "visit_count": row.visit_count,
                "avg_dwell_ms": float(row.avg_dwell_ms or 0.0),
            }
            for row in result
        ]

    async def get_funnel_counts(
        self,
        store_id: str,
        since: Optional[datetime] = None,
    ) -> dict:
        """
        Return a four-stage conversion-funnel dict::

            {
                "entry":    <int>,   # Visitors who entered the store
                "zone":     <int>,   # Visitors who entered at least one zone
                "billing":  <int>,   # Visitors who joined the billing queue
                "purchase": <int>,   # Visitors who joined AND did not abandon
            }
        """

        async def _distinct_visitors(et: EventType) -> int:
            q = select(func.count(distinct(EventRecord.visitor_id))).where(
                EventRecord.store_id == store_id,
                EventRecord.event_type == et.value,
                EventRecord.is_staff == False,  # noqa: E712
            )
            if since:
                q = q.where(EventRecord.timestamp >= since)
            r = await self.session.execute(q)
            return r.scalar_one() or 0

        entry = await _distinct_visitors(EventType.ENTRY)
        zone = await _distinct_visitors(EventType.ZONE_ENTER)
        billing = await _distinct_visitors(EventType.BILLING_QUEUE_JOIN)

        # "Purchase" = joined the billing queue AND never abandoned it.
        abandon_subq = (
            select(EventRecord.visitor_id)
            .where(
                EventRecord.store_id == store_id,
                EventRecord.event_type == EventType.BILLING_QUEUE_ABANDON.value,
            )
        )
        purchase_q = select(
            func.count(distinct(EventRecord.visitor_id))
        ).where(
            EventRecord.store_id == store_id,
            EventRecord.event_type == EventType.BILLING_QUEUE_JOIN.value,
            EventRecord.is_staff == False,  # noqa: E712
            EventRecord.visitor_id.not_in(abandon_subq),
        )
        if since:
            purchase_q = purchase_q.where(EventRecord.timestamp >= since)
        purchase_result = await self.session.execute(purchase_q)
        purchase = purchase_result.scalar_one() or 0

        return {
            "entry": entry,
            "zone": zone,
            "billing": billing,
            "purchase": purchase,
        }

    async def get_last_zone_activity(
        self,
        store_id: str,
        zone_id: str,
    ) -> Optional[datetime]:
        """Return the timestamp of the most-recent event in *zone_id*."""
        result = await self.session.execute(
            select(func.max(EventRecord.timestamp)).where(
                EventRecord.store_id == store_id,
                EventRecord.zone_id == zone_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_all_zones(self, store_id: str) -> list[str]:
        """Return every distinct non-null zone ID seen for *store_id*."""
        result = await self.session.execute(
            select(distinct(EventRecord.zone_id)).where(
                EventRecord.store_id == store_id,
                EventRecord.zone_id.isnot(None),
            )
        )
        return [row[0] for row in result]

    async def get_historical_queue_depth(
        self,
        store_id: str,
        days: int = 7,
    ) -> float:
        """
        Return the average ``queue_depth`` field on ``BILLING_QUEUE_JOIN``
        events over the past *days* days.  Used as the baseline for spike
        detection.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(func.avg(EventRecord.queue_depth)).where(
                EventRecord.store_id == store_id,
                EventRecord.event_type == EventType.BILLING_QUEUE_JOIN.value,
                EventRecord.timestamp >= since,
                EventRecord.queue_depth.isnot(None),
            )
        )
        return float(result.scalar_one() or 0.0)

    async def get_historical_conversion_rate(
        self,
        store_id: str,
        days: int = 7,
    ) -> float:
        """
        Return the ratio of billing-queue visitors to total entry visitors
        over the past *days* days.  Returns ``0.0`` when there are no entries.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        entries = await self.get_unique_visitor_count(store_id, since=since)
        if entries == 0:
            return 0.0
        billing_visitors = await self.count_events_by_type(
            store_id, EventType.BILLING_QUEUE_JOIN, since=since
        )
        return billing_visitors / entries

    async def get_current_occupancy(self, store_id: str) -> int:
        """
        Return the count of visitors currently in the store.
        Calculated as the number of visitor sessions that have an entry_time
        and no exit_time.
        """
        q = select(func.count(VisitorSession.id)).where(
            VisitorSession.store_id == store_id,
            VisitorSession.entry_time.isnot(None),
            VisitorSession.exit_time.is_(None),
            VisitorSession.is_staff == False,  # noqa: E712
        )
        result = await self.session.execute(q)
        return result.scalar_one() or 0


# ---------------------------------------------------------------------------
# POSRepository
# ---------------------------------------------------------------------------

class POSRepository:
    """
    Data-access layer for Point-of-Sale transaction data.

    Transactions are matched against camera events to correlate footfall
    with actual purchases.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_insert(self, transactions: list[dict]) -> int:
        """
        Insert multiple POS transactions, silently skipping duplicates.

        Args:
            transactions: List of dicts whose keys match the
                ``pos_transactions`` column names.

        Returns:
            Number of rows actually inserted (duplicates excluded).
        """
        count = 0
        for tx in transactions:
            stmt = (
                pg_insert(POSTransaction)
                .values(**tx)
                .on_conflict_do_nothing()
            )
            result = await self.session.execute(stmt)
            count += result.rowcount
        return count

    async def get_transactions_in_window(
        self,
        store_id: str,
        start: datetime,
        end: datetime,
    ) -> list[POSTransaction]:
        """
        Return all POS transactions for *store_id* whose ``order_datetime``
        falls within [*start*, *end*], ordered chronologically.
        """
        result = await self.session.execute(
            select(POSTransaction)
            .where(
                POSTransaction.store_id == store_id,
                POSTransaction.order_datetime >= start,
                POSTransaction.order_datetime <= end,
            )
            .order_by(POSTransaction.order_datetime)
        )
        return list(result.scalars().all())

    async def count_purchase_sessions(
        self,
        store_id: str,
        since: Optional[datetime] = None,
    ) -> int:
        """
        Count distinct purchase moments (``order_datetime`` values) for
        *store_id*.

        Each unique ``order_datetime`` corresponds to one purchase event.
        """
        q = select(
            func.count(distinct(POSTransaction.order_datetime))
        ).where(POSTransaction.store_id == store_id)
        if since:
            q = q.where(POSTransaction.order_datetime >= since)
        result = await self.session.execute(q)
        return result.scalar_one() or 0

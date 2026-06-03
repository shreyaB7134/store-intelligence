"""
Queue detection at billing counters.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class QueueState:
    zone_id: str
    current_depth: int = 0
    members: set = None  # visitor_ids in queue
    join_times: dict = None  # visitor_id -> join datetime

    def __post_init__(self):
        if self.members is None:
            self.members = set()
        if self.join_times is None:
            self.join_times = {}


class QueueDetector:
    """
    Tracks visitors in billing zones to estimate queue depth.
    Emits JOIN and ABANDON events.
    """

    ABANDON_THRESHOLD_SECONDS = 60    # If person leaves billing without purchase
    MIN_QUEUE_DWELL_SECONDS = 10      # Minimum time to count as queue member

    def __init__(self):
        self._queues: dict[str, QueueState] = {}  # zone_id -> state

    def get_or_create(self, zone_id: str) -> QueueState:
        if zone_id not in self._queues:
            self._queues[zone_id] = QueueState(zone_id=zone_id)
        return self._queues[zone_id]

    def visitor_entered_billing(
        self, visitor_id: str, zone_id: str, now: Optional[datetime] = None
    ) -> int:
        """Record visitor joining billing queue. Returns queue position."""
        now = now or datetime.now(timezone.utc)
        state = self.get_or_create(zone_id)

        if visitor_id not in state.members:
            state.members.add(visitor_id)
            state.join_times[visitor_id] = now
            state.current_depth = len(state.members)

        return state.current_depth

    def visitor_exited_billing(
        self, visitor_id: str, zone_id: str, now: Optional[datetime] = None
    ) -> tuple[bool, int]:
        """
        Record visitor leaving billing zone.
        Returns (is_abandon, wait_seconds).
        """
        now = now or datetime.now(timezone.utc)
        state = self.get_or_create(zone_id)

        if visitor_id not in state.members:
            return False, 0

        join_time = state.join_times.get(visitor_id, now)
        wait_seconds = int((now - join_time).total_seconds())

        state.members.discard(visitor_id)
        state.join_times.pop(visitor_id, None)
        state.current_depth = len(state.members)

        # Abandon if waited short time without completing
        is_abandon = wait_seconds < self.ABANDON_THRESHOLD_SECONDS
        return is_abandon, wait_seconds

    def get_queue_depth(self, zone_id: str) -> int:
        state = self._queues.get(zone_id)
        return state.current_depth if state else 0

    def get_total_queue_depth(self) -> int:
        return sum(s.current_depth for s in self._queues.values())

"""
Visitor session management – generates stable, unique visitor IDs and
tracks each person's per-zone dwell timing.
"""
from __future__ import annotations
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VisitorSession:
    """
    All state associated with a single store visit by one person.
    """
    visitor_id: str
    track_id: int
    store_id: str
    camera_id: str
    entry_time: datetime
    is_staff: bool = False
    session_seq: int = 0

    # Zone state
    current_zones: set[str] = field(default_factory=set)
    zone_enter_times: dict[str, datetime] = field(default_factory=dict)
    last_dwell_emit: dict[str, datetime] = field(default_factory=dict)

    # Billing queue state
    in_billing_queue: bool = False
    billing_join_time: Optional[datetime] = None

    # Exit state
    exit_time: Optional[datetime] = None
    total_dwell_ms: int = 0

    # Counters
    frame_count: int = 0


class SessionManager:
    """
    Creates and manages VisitorSession objects for active tracks.

    Visitor IDs are deterministic hashes of (store, track, sequence, nonce)
    so they are opaque but stable within a session.  Re-entry detection
    is handled externally (ReIDEngine) and the matched ID is passed in
    via `reentry_visitor_id`.
    """

    DWELL_EMIT_INTERVAL_SECONDS: int = 30

    def __init__(self, store_id: str, camera_id: str) -> None:
        self._store_id = store_id
        self._camera_id = camera_id
        # track_id → VisitorSession
        self._active_sessions: dict[int, VisitorSession] = {}
        self._session_counter = 0

    # ------------------------------------------------------------------
    # ID generation
    # ------------------------------------------------------------------

    def _generate_visitor_id(
        self, track_id: int, store_id: str, session_seq: int
    ) -> str:
        """
        Generate a stable, unique visitor ID using SHA-256.
        A nanosecond timestamp is included as a nonce so two different
        visitors assigned the same tracker slot in separate visits get
        different IDs even if store_id / session_seq collide.
        """
        raw = f"{store_id}:{track_id}:{session_seq}:{time.time_ns()}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"VIS_{h.upper()}"

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(
        self,
        track_id: int,
        is_staff: bool = False,
        reentry_visitor_id: Optional[str] = None,
    ) -> VisitorSession:
        """
        Create a new VisitorSession for *track_id*.

        If *reentry_visitor_id* is provided (from ReIDEngine) the same
        visitor ID is reused so the API can link the two visits.
        """
        self._session_counter += 1

        visitor_id = (
            reentry_visitor_id
            if reentry_visitor_id
            else self._generate_visitor_id(
                track_id, self._store_id, self._session_counter
            )
        )

        session = VisitorSession(
            visitor_id=visitor_id,
            track_id=track_id,
            store_id=self._store_id,
            camera_id=self._camera_id,
            entry_time=datetime.now(timezone.utc),
            is_staff=is_staff,
            session_seq=self._session_counter,
        )
        self._active_sessions[track_id] = session
        logger.debug(
            "Created session %s for track %d (re-entry=%s)",
            visitor_id, track_id, reentry_visitor_id is not None,
        )
        return session

    def get_session(self, track_id: int) -> Optional[VisitorSession]:
        """Retrieve the active session for *track_id*, or None."""
        return self._active_sessions.get(track_id)

    def end_session(self, track_id: int) -> Optional[VisitorSession]:
        """
        Close the session for *track_id* and record the exit timestamp.
        Returns the closed session (or None if not found).
        """
        session = self._active_sessions.pop(track_id, None)
        if session:
            session.exit_time = datetime.now(timezone.utc)
            elapsed_ms = int(
                (session.exit_time - session.entry_time).total_seconds() * 1000
            )
            session.total_dwell_ms = elapsed_ms
            logger.debug(
                "Ended session %s for track %d (dwell=%d ms)",
                session.visitor_id, track_id, elapsed_ms,
            )
        return session

    def get_all_sessions(self) -> list[VisitorSession]:
        """Return all currently active sessions."""
        return list(self._active_sessions.values())

    # ------------------------------------------------------------------
    # Dwell emit helpers
    # ------------------------------------------------------------------

    def should_emit_dwell(
        self, session: VisitorSession, zone_id: str, now: datetime
    ) -> bool:
        """
        Return True if enough time has elapsed since the last ZONE_DWELL
        event was emitted for this (session, zone) pair.
        """
        last = session.last_dwell_emit.get(zone_id)
        if last is None:
            # First zone-enter sets the baseline; don't emit immediately
            return False
        elapsed = (now - last).total_seconds()
        return elapsed >= self.DWELL_EMIT_INTERVAL_SECONDS

    def mark_dwell_emitted(
        self, session: VisitorSession, zone_id: str, now: datetime
    ) -> None:
        """Record that a ZONE_DWELL event has just been emitted."""
        session.last_dwell_emit[zone_id] = now

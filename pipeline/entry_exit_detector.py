"""
Entry/Exit detection via virtual line crossing.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CrossingDirection(Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    NONE = "NONE"


@dataclass
class LineCrossing:
    """A virtual line defined by two endpoints."""
    x1: float
    y1: float
    x2: float
    y2: float
    entry_side: str = "top"  # Which side of the line is "inside" the store

    def which_side(self, x: float, y: float) -> float:
        """
        Returns a signed value indicating which side of the line the point is on.
        Positive on one side, negative on the other, zero on the line.
        Uses the cross-product of the line direction with the point-to-start vector.
        """
        return (self.x2 - self.x1) * (y - self.y1) - (self.y2 - self.y1) * (x - self.x1)


class EntryExitDetector:
    """
    Detects store entry/exit events by tracking when persons cross
    a virtual line at the store entrance.

    The line divides the frame into two halves.  Crossing from positive
    side → negative side is counted as ENTRY; the reverse is EXIT.
    These mappings can be reversed by swapping the line endpoints if
    the camera orientation differs.
    """

    def __init__(
        self,
        line: Optional[LineCrossing] = None,
        frame_size: tuple[int, int] = (640, 480),
    ) -> None:
        self._frame_size = frame_size
        if line is None:
            # Default: horizontal line at top 20 % of frame
            w, h = frame_size
            self._line = LineCrossing(0.0, h * 0.2, float(w), h * 0.2)
        else:
            self._line = line

        # Per-track state
        self._last_positions: dict[int, tuple[float, float]] = {}
        self._last_side: dict[int, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        track_id: int,
        center: tuple[float, float],
    ) -> CrossingDirection:
        """
        Update the stored position for `track_id` and detect line crossings.
        Returns:
            CrossingDirection.ENTRY  – person just crossed into the store
            CrossingDirection.EXIT   – person just crossed out of the store
            CrossingDirection.NONE   – no crossing this frame
        """
        cx, cy = center
        current_side = self._line.which_side(cx, cy)

        if track_id not in self._last_side:
            # First observation — record side, no crossing yet
            self._last_side[track_id] = current_side
            self._last_positions[track_id] = center
            return CrossingDirection.NONE

        prev_side = self._last_side[track_id]
        self._last_side[track_id] = current_side
        self._last_positions[track_id] = center

        # Sign change → crossing
        if prev_side > 0 and current_side <= 0:
            return CrossingDirection.ENTRY
        elif prev_side <= 0 and current_side > 0:
            return CrossingDirection.EXIT

        return CrossingDirection.NONE

    def remove_track(self, track_id: int) -> None:
        """Clean up state for a track that is no longer active."""
        self._last_positions.pop(track_id, None)
        self._last_side.pop(track_id, None)

    def set_line(self, line: LineCrossing) -> None:
        """Replace the virtual line (e.g. when camera config is reloaded)."""
        self._line = line
        # Clear stale state so tracks are re-initialised against the new line
        self._last_positions.clear()
        self._last_side.clear()

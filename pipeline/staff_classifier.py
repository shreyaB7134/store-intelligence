"""
Staff detection using rule-based and appearance-based heuristics.
"""
from __future__ import annotations
import logging
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


class StaffClassifier:
    """
    Classifies whether a tracked person is staff or a customer.

    Classification rules (applied in order; first match wins):
    1.  **Off-hours presence** – anyone detected before STORE_OPEN_HOUR or
        at/after STORE_CLOSE_HOUR is treated as staff.
    2.  **Staff-only zones** – person is currently in a zone labelled as
        staff-only (e.g. stock room, back office).
    3.  **Uniform colour detection** – torso region has a dominant green or
        purple/blue hue that matches the store's uniform palette.
    4.  **Manual override list** – visitor IDs added via `mark_as_staff()`.
    """

    STORE_OPEN_HOUR: int = 10   # 10:00 local time
    STORE_CLOSE_HOUR: int = 22  # 22:00 local time

    # HSV ranges for the Purplle store uniform (purple/violet tones)
    _UNIFORM_RANGES = [
        # (lower_hsv, upper_hsv, label)
        ((36, 50, 50), (86, 255, 255), "green"),
        ((100, 50, 50), (140, 255, 255), "blue/purple"),
    ]
    _UNIFORM_RATIO_THRESHOLD: float = 0.35  # fraction of torso pixels

    def __init__(
        self,
        staff_zone_ids: Optional[list[str]] = None,
        store_open_hour: int = 10,
        store_close_hour: int = 22,
    ) -> None:
        self._staff_zone_ids: set[str] = set(staff_zone_ids or [])
        self._known_staff: set[str] = set()
        self.STORE_OPEN_HOUR = store_open_hour
        self.STORE_CLOSE_HOUR = store_close_hour

    # ------------------------------------------------------------------
    # Manual overrides
    # ------------------------------------------------------------------

    def mark_as_staff(self, visitor_id: str) -> None:
        """Permanently mark a visitor ID as staff for this session."""
        self._known_staff.add(visitor_id)
        logger.debug("Visitor %s manually marked as staff", visitor_id)

    def unmark_staff(self, visitor_id: str) -> None:
        """Remove a visitor ID from the manual staff list."""
        self._known_staff.discard(visitor_id)

    def is_known_staff(self, visitor_id: str) -> bool:
        return visitor_id in self._known_staff

    def add_staff_zone(self, zone_id: str) -> None:
        self._staff_zone_ids.add(zone_id)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(
        self,
        track_id: int,
        current_zones: list[str],
        hour_of_day: int,
        frames_tracked: int,
        frame: Optional[np.ndarray] = None,
        bbox: Optional[tuple] = None,
    ) -> bool:
        """
        Return True if this person is likely a staff member.

        Parameters
        ----------
        track_id:       Internal tracker ID (for stateful heuristics).
        current_zones:  Zone IDs the person currently occupies.
        hour_of_day:    Current local hour (0–23).
        frames_tracked: How long this track has been active.
        frame:          Raw BGR frame (optional; enables uniform detection).
        bbox:           Bounding box (x1, y1, x2, y2) for the person crop.
        """
        # Rule 1: Outside business hours → staff
        if hour_of_day < self.STORE_OPEN_HOUR or hour_of_day >= self.STORE_CLOSE_HOUR:
            return True

        # Rule 2: Located in a staff-only zone
        if self._staff_zone_ids and any(z in self._staff_zone_ids for z in current_zones):
            return True

        # Rule 3: Uniform colour detection
        if frame is not None and bbox is not None:
            if self._detect_uniform(frame, bbox):
                return True

        return False

    # ------------------------------------------------------------------
    # Uniform detection helper
    # ------------------------------------------------------------------

    def _detect_uniform(self, frame: np.ndarray, bbox: tuple) -> bool:
        """
        Return True if the torso region of the bounding box exhibits
        a dominant uniform colour matching the configured HSV ranges.
        """
        try:
            import cv2  # type: ignore

            x1, y1, x2, y2 = [int(c) for c in bbox]
            h = y2 - y1
            if h <= 0:
                return False

            # Focus on the middle third (torso area)
            torso_y1 = y1 + h // 3
            torso_y2 = y2 - h // 3
            torso = frame[torso_y1:torso_y2, x1:x2]
            if torso.size == 0:
                return False

            hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
            total_pixels = torso.shape[0] * torso.shape[1]
            if total_pixels == 0:
                return False

            for lower, upper, label in self._UNIFORM_RANGES:
                mask = cv2.inRange(
                    hsv,
                    np.array(lower, dtype=np.uint8),
                    np.array(upper, dtype=np.uint8),
                )
                ratio = float(np.sum(mask > 0)) / total_pixels
                if ratio >= self._UNIFORM_RATIO_THRESHOLD:
                    logger.debug(
                        "Uniform detected (%s, %.0f%% of torso)", label, ratio * 100
                    )
                    return True

            return False
        except Exception as e:
            logger.debug("Uniform detection error: %s", e)
            return False

"""
Zone management using polygon containment detection.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Zone:
    zone_id: str
    name: str
    zone_type: str
    polygon: list[tuple[float, float]]  # [(x, y), ...]
    is_billing: bool = False
    is_entry: bool = False
    is_exit: bool = False

    def contains_point(self, x: float, y: float) -> bool:
        """Ray casting algorithm for point-in-polygon test."""
        n = len(self.polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = self.polygon[i]
            xj, yj = self.polygon[j]
            if ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi
            ):
                inside = not inside
            j = i
        return inside

    def contains_bbox_center(self, bbox: tuple[float, float, float, float]) -> bool:
        """Return True if the bounding-box centre lies inside this zone."""
        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        return self.contains_point(cx, cy)


class ZoneManager:
    """
    Manages store zones loaded from store_layout.json.
    Detects zone entry/exit for tracked persons.
    """

    def __init__(self) -> None:
        self._zones: dict[str, Zone] = {}
        self._default_zones_loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_from_file(self, layout_path: str | Path) -> None:
        """Load zones from a store_layout.json file."""
        path = Path(layout_path)
        if not path.exists():
            logger.warning("Layout file not found: %s, using defaults", path)
            self._load_default_zones()
            return

        with open(path) as f:
            data = json.load(f)

        zones_data = data.get("zones", data.get("Zones", []))
        for z in zones_data:
            zone_id = z.get("zone_id", z.get("id", ""))
            name = z.get("name", z.get("zone_name", ""))
            zone_type = z.get("type", z.get("zone_type", "SHELF")).upper()
            coords = z.get("polygon", z.get("coordinates", []))

            # Normalise coordinate format
            if coords and isinstance(coords[0], dict):
                polygon = [(c["x"], c["y"]) for c in coords]
            elif coords and isinstance(coords[0], (list, tuple)):
                polygon = [tuple(c) for c in coords]
            else:
                polygon = []

            if not polygon:
                # Fall back to axis-aligned bbox if polygon is missing
                bbox = z.get("bbox", z.get("bounding_box", {}))
                if bbox:
                    x1, y1 = bbox.get("x", 0), bbox.get("y", 0)
                    w, h = bbox.get("w", 100), bbox.get("h", 100)
                    polygon = [
                        (x1, y1),
                        (x1 + w, y1),
                        (x1 + w, y1 + h),
                        (x1, y1 + h),
                    ]

            zone = Zone(
                zone_id=zone_id,
                name=name,
                zone_type=zone_type,
                polygon=polygon,
                is_billing="BILLING" in zone_type or "BILLING" in zone_id.upper(),
                is_entry="ENTRY" in zone_type or "ENTRY" in zone_id.upper(),
                is_exit="EXIT" in zone_type or "EXIT" in zone_id.upper(),
            )
            self._zones[zone_id] = zone

        logger.info("Loaded %d zones from %s", len(self._zones), path)

    def _load_default_zones(self) -> None:
        """Create synthetic default zones suitable for a 640×480 feed."""
        default_zones = [
            Zone(
                "ZONE_ENTRY", "Entry Area", "ENTRY",
                [(0, 0), (640, 0), (640, 100), (0, 100)],
                is_entry=True,
            ),
            Zone(
                "ZONE_SHELF_L", "Left Shelf", "SHELF",
                [(0, 100), (213, 100), (213, 380), (0, 380)],
            ),
            Zone(
                "ZONE_DISPLAY", "Center Display", "DISPLAY",
                [(213, 100), (427, 100), (427, 380), (213, 380)],
            ),
            Zone(
                "ZONE_SHELF_R", "Right Shelf", "SHELF",
                [(427, 100), (640, 100), (640, 380), (427, 380)],
            ),
            Zone(
                "ZONE_BILLING", "Billing Counter", "BILLING",
                [(0, 380), (640, 380), (640, 480), (0, 480)],
                is_billing=True,
            ),
        ]
        for z in default_zones:
            self._zones[z.zone_id] = z
        logger.info("Loaded %d default zones", len(self._zones))
        self._default_zones_loaded = True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_zones_for_point(self, x: float, y: float) -> list[Zone]:
        """Return all zones that contain the given point."""
        return [z for z in self._zones.values() if z.contains_point(x, y)]

    def get_zones_for_bbox(self, bbox: tuple) -> list[Zone]:
        """Return all zones whose polygon contains the bbox centre."""
        return [z for z in self._zones.values() if z.contains_bbox_center(bbox)]

    def get_zone(self, zone_id: str) -> Optional[Zone]:
        return self._zones.get(zone_id)

    def all_zones(self) -> list[Zone]:
        return list(self._zones.values())

    def billing_zones(self) -> list[Zone]:
        return [z for z in self._zones.values() if z.is_billing]

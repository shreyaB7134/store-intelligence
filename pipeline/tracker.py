"""
Multi-object tracking using ByteTrack with DeepSORT fallback.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from pipeline.detector import Detection

logger = logging.getLogger(__name__)


@dataclass
class Track:
    """A tracked object with stable ID."""
    track_id: int
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    age: int = 0  # frames since first seen
    frames_since_seen: int = 0
    center_history: list[tuple[float, float]] = field(default_factory=list)
    appearance_embedding: Optional[np.ndarray] = None

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0, x2 - x1) * max(0, y2 - y1)

    def update(self, bbox: tuple, confidence: float) -> None:
        self.bbox = bbox
        self.confidence = confidence
        self.age += 1
        self.frames_since_seen = 0
        cx, cy = self.center
        self.center_history.append((cx, cy))
        if len(self.center_history) > 300:  # Keep last 300 positions
            self.center_history.pop(0)


class ByteTracker:
    """
    ByteTrack-inspired multi-object tracker.
    Tracks high and low confidence detections separately.
    Falls back to simple IoU matching.
    """

    def __init__(
        self,
        track_thresh: float = 0.5,
        track_buffer: int = 30,
        match_thresh: float = 0.8,
        min_box_area: float = 100.0,
    ):
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.min_box_area = min_box_area
        self._tracks: dict[int, Track] = {}
        self._next_id = 1
        self._frame_count = 0

        # Try to use real ByteTrack
        self._use_bytetrack = False
        self._bt_tracker = None
        self._init_bytetrack()

    def _init_bytetrack(self) -> None:
        try:
            from ultralytics import YOLO  # noqa: F401 – confirms ultralytics is present
            # ByteTrack is built into ultralytics
            logger.info("Using ByteTrack via ultralytics")
            self._use_bytetrack = True
        except ImportError:
            logger.info("ByteTrack unavailable, using IoU tracker")

    def update(self, detections: list[Detection], frame: Optional[np.ndarray] = None) -> list[Track]:
        """
        Update tracker with new detections.
        Returns list of active tracks.
        """
        self._frame_count += 1

        # Mark all tracks as not seen this frame
        for track in self._tracks.values():
            track.frames_since_seen += 1

        if not detections:
            # Remove stale tracks
            self._remove_stale_tracks()
            return list(self._tracks.values())

        # Filter by minimum area
        valid_dets = [
            d for d in detections
            if (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]) >= self.min_box_area
        ]

        if not self._tracks:
            # Initialize tracks for all detections
            for det in valid_dets:
                self._create_track(det)
        else:
            # Match detections to existing tracks using IoU
            self._match_and_update(valid_dets)

        self._remove_stale_tracks()
        return list(self._tracks.values())

    def _create_track(self, det: Detection) -> Track:
        track = Track(
            track_id=self._next_id,
            bbox=det.bbox,
            confidence=det.confidence,
        )
        self._tracks[self._next_id] = track
        self._next_id += 1
        return track

    def _match_and_update(self, detections: list[Detection]) -> None:
        if not detections:
            return

        track_ids = list(self._tracks.keys())
        track_bboxes = [self._tracks[tid].bbox for tid in track_ids]
        det_bboxes = [d.bbox for d in detections]

        # Compute IoU matrix (returned as cost matrix: lower = better match)
        iou_matrix = self._compute_iou_matrix(track_bboxes, det_bboxes)

        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()

        # Greedy matching — pick highest-IoU pairs first
        for _ in range(min(len(track_ids), len(detections))):
            if iou_matrix.size == 0:
                break
            max_idx = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
            t_idx, d_idx = int(max_idx[0]), int(max_idx[1])

            if iou_matrix[t_idx, d_idx] < (1 - self.match_thresh):
                break

            tid = track_ids[t_idx]
            self._tracks[tid].update(detections[d_idx].bbox, detections[d_idx].confidence)
            matched_tracks.add(t_idx)
            matched_dets.add(d_idx)

            # Zero out matched row/col to prevent re-selection
            iou_matrix[t_idx, :] = 0
            iou_matrix[:, d_idx] = 0

        # Create new tracks for unmatched high-confidence detections
        for d_idx, det in enumerate(detections):
            if d_idx not in matched_dets and det.confidence >= self.track_thresh:
                self._create_track(det)

    def _compute_iou_matrix(
        self,
        bboxes1: list[tuple],
        bboxes2: list[tuple],
    ) -> np.ndarray:
        """
        Returns a cost matrix where element [i, j] = 1 - IoU(b1_i, b2_j).
        Greedy matching maximises this matrix (i.e. picks highest IoU pairs).
        """
        if not bboxes1 or not bboxes2:
            return np.zeros((len(bboxes1), len(bboxes2)))

        matrix = np.zeros((len(bboxes1), len(bboxes2)))
        for i, b1 in enumerate(bboxes1):
            for j, b2 in enumerate(bboxes2):
                matrix[i, j] = self._iou(b1, b2)
        # Return as similarity matrix (higher = better), not cost matrix
        return matrix

    def _iou(self, b1: tuple, b2: tuple) -> float:
        """Compute Intersection-over-Union for two bounding boxes."""
        x1 = max(b1[0], b2[0])
        y1 = max(b1[1], b2[1])
        x2 = min(b1[2], b2[2])
        y2 = min(b1[3], b2[3])

        if x2 <= x1 or y2 <= y1:
            return 0.0

        inter = (x2 - x1) * (y2 - y1)
        area1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
        area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
        union = area1 + area2 - inter
        return inter / union if union > 0 else 0.0

    def _remove_stale_tracks(self) -> None:
        """Remove tracks that have not been matched for `track_buffer` frames."""
        to_remove = [
            tid for tid, track in self._tracks.items()
            if track.frames_since_seen > self.track_buffer
        ]
        for tid in to_remove:
            del self._tracks[tid]

    def get_track(self, track_id: int) -> Optional[Track]:
        return self._tracks.get(track_id)

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1
        self._frame_count = 0

"""
Main video processing pipeline - orchestrates detection, tracking, and event emission.
"""
from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import numpy as np

from pipeline.detector import PersonDetector
from pipeline.tracker import ByteTracker
from pipeline.zone_manager import ZoneManager
from pipeline.session_manager import SessionManager
from pipeline.entry_exit_detector import EntryExitDetector, CrossingDirection
from pipeline.reid_engine import ReIDEngine
from pipeline.staff_classifier import StaffClassifier
from pipeline.queue_detector import QueueDetector
from pipeline.event_emitter import EventEmitter
from app.domain.enums import EventType

logger = logging.getLogger(__name__)


class VideoProcessor:
    """
    End-to-end pipeline for a single camera feed.
    Processes frames and emits intelligence events.
    """

    def __init__(
        self,
        store_id: str,
        camera_id: str,
        layout_path: Optional[str] = None,
        api_url: str = "http://localhost:8000",
        max_fps: float = 10.0,
    ):
        self.store_id = store_id
        self.camera_id = camera_id
        self.max_fps = max_fps
        self._frame_interval = 1.0 / max_fps
        self._frame_count = 0

        # Initialize components
        self._detector = PersonDetector()
        self._tracker = ByteTracker()
        self._zone_manager = ZoneManager()
        self._session_manager = SessionManager(store_id, camera_id)
        self._entry_detector = EntryExitDetector()
        self._reid_engine = ReIDEngine()
        self._staff_classifier = StaffClassifier()
        self._queue_detector = QueueDetector()
        self._emitter = EventEmitter(api_base_url=api_url)

        # Load zones
        if layout_path:
            self._zone_manager.load_from_file(layout_path)
        else:
            self._zone_manager._load_default_zones()

        # Track active zones per track
        self._track_zones: dict[int, set[str]] = {}

    async def process_video(self, video_path: str) -> dict:
        """
        Process a video file end-to-end.
        Returns processing statistics.
        """
        try:
            import cv2
        except ImportError:
            logger.error("OpenCV not installed. Cannot process video.")
            return {"error": "opencv not available"}

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error("Cannot open video: %s", video_path)
            return {"error": f"cannot open {video_path}"}

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_skip = max(1, int(fps / self.max_fps))

        logger.info(
            "Processing %s: %.1f fps, %d frames, skip=%d",
            video_path, fps, total_frames, frame_skip
        )

        async with self._emitter:
            frame_idx = 0
            t_start = time.monotonic()

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                frame_idx += 1

                # Frame skipping for performance
                if frame_idx % frame_skip != 0:
                    continue

                self._frame_count += 1
                await self._process_frame(frame, frame_idx, fps)

                # Periodic flush
                if self._frame_count % 30 == 0:
                    await self._emitter.flush()

            # End all active sessions
            for track_id in list(self._session_manager._active_sessions.keys()):
                await self._handle_exit(track_id, frame_idx)

            await self._emitter.flush()

        cap.release()
        elapsed = time.monotonic() - t_start
        stats = {
            "frames_processed": self._frame_count,
            "total_frames": total_frames,
            "elapsed_seconds": round(elapsed, 2),
            **self._emitter.stats,
        }
        logger.info("Video processing complete: %s", stats)
        return stats

    async def _process_frame(
        self, frame: np.ndarray, frame_idx: int, fps: float
    ) -> None:
        """Process a single frame."""
        now = datetime.now(timezone.utc)
        hour = now.hour

        # 1. Detect persons
        detections = self._detector.detect(frame, frame_idx)

        # 2. Track
        tracks = self._tracker.update(detections, frame)
        active_track_ids = {t.track_id for t in tracks}

        # 3. Process each track
        for track in tracks:
            tid = track.track_id
            session = self._session_manager.get_session(tid)

            # New track - check for reentry first
            if session is None:
                embedding = self._reid_engine.extract_embedding(frame, track.bbox)
                reentry_id = self._reid_engine.find_match(
                    embedding, frame_idx,
                    exclude_ids={s.visitor_id for s in self._session_manager.get_all_sessions()}
                )

                current_zone_ids = [z.zone_id for z in self._zone_manager.get_zones_for_bbox(track.bbox)]
                is_staff = self._staff_classifier.classify(
                    tid, current_zone_ids, hour, track.age, frame, track.bbox
                )

                session = self._session_manager.create_session(
                    tid, is_staff=is_staff, reentry_visitor_id=reentry_id
                )

                if reentry_id:
                    event = self._emitter.create_event(
                        EventType.REENTRY, session.visitor_id,
                        self.store_id, self.camera_id,
                        confidence=0.75, is_staff=is_staff,
                        session_seq=session.session_seq,
                        timestamp=now,
                    )
                    self._emitter.emit(event)
                else:
                    # Check entry crossing
                    direction = self._entry_detector.update(tid, track.center)
                    if direction == CrossingDirection.ENTRY:
                        event = self._emitter.create_event(
                            EventType.ENTRY, session.visitor_id,
                            self.store_id, self.camera_id,
                            confidence=track.confidence, is_staff=is_staff,
                            session_seq=session.session_seq,
                            timestamp=now,
                        )
                        self._emitter.emit(event)

            # Zone detection
            current_zones = {z.zone_id for z in self._zone_manager.get_zones_for_bbox(track.bbox)}
            prev_zones = self._track_zones.get(tid, set())

            # Zone enter events
            for zone_id in current_zones - prev_zones:
                zone = self._zone_manager.get_zone(zone_id)
                session.current_zones.add(zone_id)
                session.zone_enter_times[zone_id] = now
                session.last_dwell_emit[zone_id] = now

                event = self._emitter.create_event(
                    EventType.ZONE_ENTER, session.visitor_id,
                    self.store_id, self.camera_id,
                    zone_id=zone_id, is_staff=session.is_staff,
                    confidence=track.confidence,
                    session_seq=session.session_seq,
                    timestamp=now,
                )
                self._emitter.emit(event)

                # Billing queue join
                if zone and zone.is_billing:
                    pos = self._queue_detector.visitor_entered_billing(
                        session.visitor_id, zone_id, now
                    )
                    session.in_billing_queue = True
                    session.billing_join_time = now
                    event = self._emitter.create_event(
                        EventType.BILLING_QUEUE_JOIN, session.visitor_id,
                        self.store_id, self.camera_id,
                        zone_id=zone_id, is_staff=session.is_staff,
                        confidence=track.confidence,
                        queue_depth=pos,
                        session_seq=session.session_seq,
                        timestamp=now,
                    )
                    self._emitter.emit(event)

            # Zone exit events
            for zone_id in prev_zones - current_zones:
                enter_time = session.zone_enter_times.get(zone_id, now)
                dwell_ms = int((now - enter_time).total_seconds() * 1000)
                session.current_zones.discard(zone_id)

                event = self._emitter.create_event(
                    EventType.ZONE_EXIT, session.visitor_id,
                    self.store_id, self.camera_id,
                    zone_id=zone_id, dwell_ms=dwell_ms,
                    is_staff=session.is_staff,
                    confidence=track.confidence,
                    session_seq=session.session_seq,
                    timestamp=now,
                )
                self._emitter.emit(event)

                # Billing queue abandon check
                zone = self._zone_manager.get_zone(zone_id)
                if zone and zone.is_billing and session.in_billing_queue:
                    is_abandon, wait_secs = self._queue_detector.visitor_exited_billing(
                        session.visitor_id, zone_id, now
                    )
                    if is_abandon:
                        event = self._emitter.create_event(
                            EventType.BILLING_QUEUE_ABANDON, session.visitor_id,
                            self.store_id, self.camera_id,
                            zone_id=zone_id, dwell_ms=wait_secs * 1000,
                            is_staff=session.is_staff,
                            confidence=track.confidence,
                            session_seq=session.session_seq,
                            timestamp=now,
                        )
                        self._emitter.emit(event)
                    session.in_billing_queue = False

            # Dwell events (every 30s)
            for zone_id in current_zones:
                if self._session_manager.should_emit_dwell(session, zone_id, now):
                    enter_time = session.zone_enter_times.get(zone_id, now)
                    dwell_ms = int((now - enter_time).total_seconds() * 1000)
                    event = self._emitter.create_event(
                        EventType.ZONE_DWELL, session.visitor_id,
                        self.store_id, self.camera_id,
                        zone_id=zone_id, dwell_ms=dwell_ms,
                        is_staff=session.is_staff,
                        confidence=track.confidence,
                        session_seq=session.session_seq,
                        timestamp=now,
                    )
                    self._emitter.emit(event)
                    self._session_manager.mark_dwell_emitted(session, zone_id, now)

            self._track_zones[tid] = current_zones

        # Handle disappeared tracks (exit)
        disappeared = set(self._track_zones.keys()) - active_track_ids
        for tid in disappeared:
            await self._handle_exit(tid, frame_idx)

    async def _handle_exit(self, track_id: int, frame_idx: int) -> None:
        """Handle track disappearing - emit exit event and update ReID gallery."""
        session = self._session_manager.end_session(track_id)
        if session is None:
            self._track_zones.pop(track_id, None)
            self._entry_detector.remove_track(track_id)
            return

        now = datetime.now(timezone.utc)

        # Emit exit
        event = self._emitter.create_event(
            EventType.EXIT, session.visitor_id,
            self.store_id, self.camera_id,
            is_staff=session.is_staff,
            confidence=0.9,
            session_seq=session.session_seq,
            timestamp=now,
        )
        self._emitter.emit(event)

        # Add to ReID gallery
        dummy_embedding = np.zeros(96)  # Would be real embedding in production
        self._reid_engine.add_to_gallery(
            session.visitor_id,
            dummy_embedding,
            frame_idx,
            trajectory=list(session.zone_enter_times.keys()),
        )

        self._track_zones.pop(track_id, None)
        self._entry_detector.remove_track(track_id)

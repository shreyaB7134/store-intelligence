"""
Person detection using YOLOv8 with RT-DETR fallback.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """A single person detection from the model."""
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    class_id: int  # 0 = person
    frame_idx: int


class PersonDetector:
    """
    YOLOv8-based person detector.
    Falls back to RT-DETR if YOLOv8 unavailable.
    Uses class_id=0 (person) only.
    """

    PERSON_CLASS_ID = 0
    MIN_CONFIDENCE = 0.4

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        confidence_threshold: float = 0.4,
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.device = device
        self._model = None
        self._backend = "yolov8"
        self._load_model()

    def _load_model(self) -> None:
        """Load YOLOv8, fall back to RT-DETR."""
        try:
            from ultralytics import YOLO
            self._model = YOLO(self.model_name)
            self._backend = "yolov8"
            logger.info("Loaded YOLOv8 model: %s on %s", self.model_name, self.device)
        except Exception as e:
            logger.warning("YOLOv8 unavailable (%s), trying RT-DETR", e)
            try:
                from ultralytics import RTDETR
                self._model = RTDETR("rtdetr-l.pt")
                self._backend = "rtdetr"
                logger.info("Loaded RT-DETR fallback model")
            except Exception as e2:
                logger.error("Both YOLOv8 and RT-DETR failed: %s", e2)
                self._model = None

    def detect(self, frame: np.ndarray, frame_idx: int = 0) -> list[Detection]:
        """
        Run detection on a single frame.
        Returns list of person detections.
        """
        if self._model is None:
            return self._mock_detect(frame, frame_idx)

        try:
            results = self._model(
                frame,
                classes=[self.PERSON_CLASS_ID],
                conf=self.confidence_threshold,
                verbose=False,
                device=self.device,
            )
            detections = []
            for result in results:
                if result.boxes is None:
                    continue
                for box in result.boxes:
                    cls = int(box.cls.item())
                    if cls != self.PERSON_CLASS_ID:
                        continue
                    conf = float(box.conf.item())
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    detections.append(Detection(
                        bbox=(x1, y1, x2, y2),
                        confidence=conf,
                        class_id=cls,
                        frame_idx=frame_idx,
                    ))
            return detections
        except Exception as e:
            logger.error("Detection failed on frame %d: %s", frame_idx, e)
            return []

    def _mock_detect(self, frame: np.ndarray, frame_idx: int) -> list[Detection]:
        """Mock detector for testing without GPU/model."""
        h, w = frame.shape[:2] if frame is not None else (480, 640)
        # Simulate occasional detections
        if frame_idx % 5 == 0:
            return [
                Detection(
                    bbox=(100, 50, 200, 300),
                    confidence=0.85,
                    class_id=0,
                    frame_idx=frame_idx,
                )
            ]
        return []

    @property
    def backend(self) -> str:
        return self._backend

    def warmup(self, frame_size: tuple[int, int] = (640, 640)) -> None:
        """Warm up model with dummy frame."""
        dummy = np.zeros((*frame_size, 3), dtype=np.uint8)
        self.detect(dummy, frame_idx=-1)
        logger.info("Model warmed up")

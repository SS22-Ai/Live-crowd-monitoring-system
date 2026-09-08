"""
Person detector + tracker, built on Ultralytics YOLO.

- Loads a lightweight YOLO model (YOLO11n by default) and restricts
  inference to the COCO 'person' class (class id 0) only.
- Uses Ultralytics' built-in ByteTrack (`tracker='bytetrack.yaml'`) via
  `model.track(..., persist=True)`, which assigns a persistent integer
  track_id per person across frames.
- Selects Apple MPS when available, falling back to CPU. Never assumes
  CUDA. Prints the selected device at startup per spec section 5.

No face recognition, no biometric extraction, no identity storage —
only anonymous bounding boxes + track IDs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger("crowd_monitor.detector")

PERSON_CLASS_ID = 0  # COCO class 0 = person


@dataclass
class Detection:
    track_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float

    @property
    def bottom_center(self) -> Tuple[float, float]:
        """Bottom-center point of the bbox — the primary crossing point
        per spec section 4 (more stable for a walking person than centroid)."""
        return ((self.x1 + self.x2) / 2.0, self.y2)


def select_device() -> str:
    """Choose 'mps' on Apple Silicon when available, else 'cpu'. Never CUDA."""
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not query torch.backends.mps: %s", exc)
    return "cpu"


class PersonDetector:
    def __init__(
        self,
        model_path: str = "models/yolo11n.pt",
        confidence: float = 0.4,
        device: Optional[str] = None,
    ):
        from ultralytics import YOLO  # imported lazily; heavy + optional for tests

        self.model_path = model_path
        self.confidence = confidence
        self.device = device or select_device()
        print(f"Using device: {self.device.upper()}")
        logger.info("Loading model %s on device %s", model_path, self.device)

        try:
            self.model = YOLO(model_path)
        except Exception as exc:
            logger.error("Failed to load YOLO model from %s: %s", model_path, exc)
            raise RuntimeError(
                f"Could not load YOLO model at '{model_path}'. "
                f"Run `yolo11n.pt` download or check the path in config.yaml."
            ) from exc

        logger.info("Model loaded successfully")

    def track(self, frame) -> List[Detection]:
        """Run detection + tracking on a single BGR frame. Returns a list
        of Detection objects (person class only, with track IDs)."""
        results = self.model.track(
            frame,
            persist=True,
            classes=[PERSON_CLASS_ID],
            conf=self.confidence,
            device=self.device,
            tracker="bytetrack.yaml",
            verbose=False,
        )

        detections: List[Detection] = []
        if not results:
            return detections

        result = results[0]
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            return detections  # no confirmed tracks this frame

        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.cpu().numpy().astype(int)
        confs = boxes.conf.cpu().numpy()

        for (x1, y1, x2, y2), track_id, conf in zip(xyxy, ids, confs):
            detections.append(
                Detection(
                    track_id=int(track_id),
                    x1=float(x1),
                    y1=float(y1),
                    x2=float(x2),
                    y2=float(y2),
                    confidence=float(conf),
                )
            )
        return detections

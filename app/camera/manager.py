"""
CameraManager runs one independent processing pipeline per camera:

  CameraStream -> PersonDetector.track() -> LineCounter -> OccupancyManager
                                                   |
                                                   v
                                          SQLite (crossing events)

Each camera runs in its own thread. An exception or failure in one
camera's pipeline is caught and logged — it must never crash or stall
the other camera (spec section 13).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import cv2

from app.camera.frame_reader import LatestFrameReader
from app.camera.stream import CameraStream, CameraStatus
from app.config import CameraConfig
from app.database.database import Database
from app.occupancy.manager import OccupancyManager
from app.vision.detector import PersonDetector
from app.vision.draw import draw_frame
from app.vision.line_counter import LineCounter, EventType

logger = logging.getLogger("crowd_monitor.camera_manager")


def _live_capture_factory(source):
    """The real (non-test) capture backend: a plain cv2.VideoCapture wrapped
    in LatestFrameReader so RTSP staleness can't build up (see
    app/camera/frame_reader.py). CameraStream itself is untouched — this is
    injected only where cameras are actually constructed for real use, so
    its own unit tests keep using a fake, fully synchronous capture."""
    return LatestFrameReader(cv2.VideoCapture(source))


@dataclass
class CameraRuntimeStats:
    camera_id: str
    name: str
    status: str
    entries: int
    exits: int
    live_occupancy: int
    fps: float


class CameraPipeline:
    def __init__(
        self,
        cfg: CameraConfig,
        detector: PersonDetector,
        db: Database,
        session_id_getter,
        inference_width: int,
        inference_height: int,
        frame_skip: int = 0,
    ):
        self.cfg = cfg
        self.detector = detector
        self.db = db
        self.session_id_getter = session_id_getter
        self.inference_width = inference_width
        self.inference_height = inference_height
        self.frame_skip = frame_skip

        self.stream = CameraStream(
            source=cfg.source,
            camera_id=cfg.id,
            reconnect_interval_seconds=cfg.reconnect_interval_seconds,
            capture_factory=_live_capture_factory,
        )
        self.line_counter = LineCounter(
            frame_width=inference_width,
            line_position=cfg.line_position,
            line_buffer=cfg.line_buffer,
            entry_direction=cfg.entry_direction,
            track_expiry_seconds=cfg.track_expiry_seconds,
        )
        self.occupancy = OccupancyManager(cfg.id, initial_occupancy=cfg.initial_occupancy)

        self._latest_jpeg: Optional[bytes] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fps = 0.0

    def start(self):
        if not self.cfg.enabled:
            logger.info("Camera %s is disabled in config; not starting", self.cfg.id)
            return
        self._thread = threading.Thread(target=self._run, name=f"camera-{self.cfg.id}", daemon=True)
        self._thread.start()
        logger.info("Camera %s pipeline thread started", self.cfg.id)

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.stream.release()

    def _run(self):
        self.stream.open()
        frame_count = 0
        last_fps_time = time.time()
        fps_frame_count = 0

        while not self._stop_event.is_set():
            try:
                ok, frame = self.stream.read()
                if not ok or frame is None:
                    time.sleep(0.2)
                    self._publish_status_only_frame()
                    continue

                frame = cv2.resize(frame, (self.inference_width, self.inference_height))

                frame_count += 1
                if self.frame_skip and (frame_count % (self.frame_skip + 1) != 0):
                    continue

                detections = self.detector.track(frame)
                crossing_points = [(d.track_id, *d.bottom_center) for d in detections]
                events = self.line_counter.update(crossing_points)

                session_id = self.session_id_getter()
                for ev in events:
                    if ev.event_type == EventType.ENTRY:
                        self.occupancy.record_entry()
                    else:
                        self.occupancy.record_exit()
                    logger.info(
                        "%s event on camera %s: track_id=%d",
                        ev.event_type.value, self.cfg.id, ev.track_id,
                    )
                    if session_id is not None:
                        try:
                            self.db.record_event(
                                session_id, self.cfg.id, ev.track_id, ev.event_type.value, ev.timestamp
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.error("Failed to persist event for camera %s: %s", self.cfg.id, exc)

                annotated = draw_frame(
                    frame,
                    detections,
                    line_x=int(self.line_counter.line_x),
                    line_buffer=self.cfg.line_buffer,
                    camera_name=self.cfg.name,
                    entries=self.line_counter.entries,
                    exits=self.line_counter.exits,
                    live_occupancy=self.occupancy.live_occupancy,
                    status=self.stream.status.value,
                )
                self._publish_frame(annotated)

                fps_frame_count += 1
                now = time.time()
                if now - last_fps_time >= 1.0:
                    self._fps = fps_frame_count / (now - last_fps_time)
                    fps_frame_count = 0
                    last_fps_time = now

            except Exception as exc:  # noqa: BLE001 - never let one camera crash the app
                logger.error("Camera %s pipeline error (continuing): %s", self.cfg.id, exc)
                time.sleep(0.5)

    def _publish_frame(self, frame):
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with self._lock:
                self._latest_jpeg = jpeg.tobytes()

    def _publish_status_only_frame(self):
        # Keep serving the last good frame; MJPEG stream just stalls briefly
        # rather than showing a blank/black frame, which is fine for section 13.
        pass

    def latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def stats(self) -> CameraRuntimeStats:
        return CameraRuntimeStats(
            camera_id=self.cfg.id,
            name=self.cfg.name,
            status=self.stream.status.value if self.cfg.enabled else CameraStatus.OFFLINE.value,
            entries=self.line_counter.entries,
            exits=self.line_counter.exits,
            live_occupancy=self.occupancy.live_occupancy,
            fps=round(self._fps, 1),
        )

    def reset(self):
        self.line_counter.reset_counts()
        self.occupancy.reset(initial_occupancy=self.cfg.initial_occupancy)


class CameraManager:
    def __init__(
        self,
        camera_configs,
        detector_factory,
        db: Database,
        session_id_getter,
        inference_width: int,
        inference_height: int,
        frame_skip: int = 0,
        resume_session_id: Optional[int] = None,
    ):
        """
        `detector_factory` is a zero-arg callable that returns a NEW
        PersonDetector instance. Each enabled camera gets its OWN model
        instance — sharing one ultralytics model across threads would
        corrupt ByteTrack's internal state, since persist=True keeps
        tracker state inside the model object itself. Two threads
        feeding two unrelated video streams into the same tracker would
        cross-contaminate track IDs between cameras.

        `resume_session_id`: if given (the app crashed last time instead
        of shutting down cleanly — see app/main.py's resolve_startup_session),
        each camera's entries/exits are seeded from that session's already-
        recorded events instead of starting at 0, so live occupancy picks
        up where it left off rather than silently resetting to zero.
        """
        self.pipelines: Dict[str, CameraPipeline] = {}
        for cfg in camera_configs:
            if not cfg.enabled:
                # Still register a (lazy) pipeline entry so /api/cameras
                # reports OFFLINE, but don't waste time/memory loading a
                # model for a disabled camera.
                self.pipelines[cfg.id] = CameraPipeline(
                    cfg, None, db, session_id_getter, inference_width, inference_height, frame_skip
                )
                continue
            detector = detector_factory()
            self.pipelines[cfg.id] = CameraPipeline(
                cfg, detector, db, session_id_getter, inference_width, inference_height, frame_skip
            )

        if resume_session_id is not None:
            for cfg in camera_configs:
                pipeline = self.pipelines[cfg.id]
                entries = db.count_events(resume_session_id, cfg.id, "ENTRY")
                exits = db.count_events(resume_session_id, cfg.id, "EXIT")
                pipeline.line_counter.entries = entries
                pipeline.line_counter.exits = exits
                pipeline.occupancy.entries = entries
                pipeline.occupancy.exits = exits
                logger.info(
                    "Camera %s: resumed session %s with entries=%d exits=%d (live_occupancy=%d)",
                    cfg.id, resume_session_id, entries, exits, pipeline.occupancy.live_occupancy,
                )

    def start_all(self):
        for pipeline in self.pipelines.values():
            pipeline.start()

    def stop_all(self):
        for pipeline in self.pipelines.values():
            pipeline.stop()

    def get(self, camera_id: str) -> Optional[CameraPipeline]:
        return self.pipelines.get(camera_id)

    def all_stats(self):
        return [p.stats() for p in self.pipelines.values()]

    def reset_all(self):
        for p in self.pipelines.values():
            p.reset()

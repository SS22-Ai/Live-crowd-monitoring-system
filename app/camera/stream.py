"""
Camera abstraction. Supports:
  - local webcam index (int), e.g. 0, 1, 2
  - RTSP URL (str), e.g. rtsp://user:pass@ip:port/stream

No camera URLs are hard-coded — everything comes from config.yaml.

The capture backend is injectable (`capture_factory`) so the reconnect /
status state machine can be unit-tested without a real camera or network.
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Callable, Optional, Tuple, Union

logger = logging.getLogger("crowd_monitor.camera")


class CameraStatus(Enum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    RECONNECTING = "RECONNECTING"


class CameraStream:
    """
    Wraps a video capture backend (cv2.VideoCapture by default). Handles:
      - opening a local webcam index OR an RTSP URL
      - reporting ONLINE / OFFLINE / RECONNECTING status
      - automatic reconnection attempts on read failure
      - never raising out to the caller — failures degrade to OFFLINE/
        RECONNECTING so one camera failing can't crash the whole app.
    """

    def __init__(
        self,
        source: Union[int, str],
        camera_id: str,
        reconnect_interval_seconds: float = 3.0,
        capture_factory: Optional[Callable] = None,
        max_reconnect_attempts_before_offline: int = 3,
    ):
        self.source = source
        self.camera_id = camera_id
        self.reconnect_interval_seconds = reconnect_interval_seconds
        self.max_reconnect_attempts_before_offline = max_reconnect_attempts_before_offline

        if capture_factory is None:
            import cv2  # imported lazily so tests don't require opencv at import time

            capture_factory = cv2.VideoCapture
        self._capture_factory = capture_factory

        self._cap = None
        self._status = CameraStatus.OFFLINE
        self._last_attempt_time = 0.0
        self._consecutive_failures = 0

    @property
    def status(self) -> CameraStatus:
        return self._status

    def open(self) -> bool:
        try:
            self._cap = self._capture_factory(self.source)
            opened = bool(self._cap and self._cap.isOpened())
        except Exception as exc:  # noqa: BLE001 - never let a camera crash the app
            logger.warning("Camera %s: exception while opening: %s", self.camera_id, exc)
            opened = False

        if opened:
            self._status = CameraStatus.ONLINE
            self._consecutive_failures = 0
            logger.info("Camera %s connected (source=%s)", self.camera_id, self.source)
        else:
            self._consecutive_failures += 1
            self._status = (
                CameraStatus.OFFLINE
                if self._consecutive_failures >= self.max_reconnect_attempts_before_offline
                else CameraStatus.RECONNECTING
            )
            logger.warning(
                "Camera %s failed to open (attempt %d, status=%s)",
                self.camera_id,
                self._consecutive_failures,
                self._status.value,
            )
        self._last_attempt_time = time.time()
        return opened

    def read(self) -> Tuple[bool, object]:
        """Returns (success, frame). On failure, transitions status and
        respects the reconnect interval before trying again. Status only
        becomes ONLINE after an actual successful frame read — a device
        that merely reports isOpened()==True is treated as RECONNECTING
        until it proves it can deliver a frame."""
        if self._cap is None:
            interval_elapsed = (
                time.time() - self._last_attempt_time
            ) >= self.reconnect_interval_seconds
            if self._last_attempt_time > 0 and not interval_elapsed:
                return False, None  # don't hammer the source between attempts
            self._attempt_reconnect()
            if self._cap is None:
                return False, None

        try:
            ret, frame = self._cap.read()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Camera %s: exception during read: %s", self.camera_id, exc)
            ret, frame = False, None

        if not ret:
            logger.warning("Camera %s: read failed, will attempt reconnect", self.camera_id)
            self._teardown_capture()
            return False, None

        if self._status != CameraStatus.ONLINE:
            logger.info("Camera %s reconnected", self.camera_id)
        self._status = CameraStatus.ONLINE
        self._consecutive_failures = 0
        return True, frame

    def _attempt_reconnect(self):
        """Try to (re)open the capture device without yet claiming ONLINE —
        ONLINE is only set once a frame is actually read successfully."""
        self._last_attempt_time = time.time()
        try:
            cap = self._capture_factory(self.source)
            opened = bool(cap and cap.isOpened())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Camera %s: exception while opening: %s", self.camera_id, exc)
            cap, opened = None, False

        if opened:
            self._cap = cap
            # Leave status as RECONNECTING/OFFLINE; read() will confirm ONLINE.
            if self._status == CameraStatus.OFFLINE:
                self._status = CameraStatus.RECONNECTING
        else:
            self._cap = None
            self._consecutive_failures += 1
            self._status = (
                CameraStatus.OFFLINE
                if self._consecutive_failures >= self.max_reconnect_attempts_before_offline
                else CameraStatus.RECONNECTING
            )

    def _teardown_capture(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None
        self._consecutive_failures += 1
        self._status = (
            CameraStatus.OFFLINE
            if self._consecutive_failures >= self.max_reconnect_attempts_before_offline
            else CameraStatus.RECONNECTING
        )

    def release(self):
        self._teardown_capture()
        self._status = CameraStatus.OFFLINE
        logger.info("Camera %s released", self.camera_id)

"""
LatestFrameReader — fixes RTSP frame staleness.

cv2.VideoCapture.read() on an RTSP source can return frames that lag real
time by several seconds whenever the consumer (our detection pipeline)
reads slower than frames arrive: FFmpeg/OpenCV buffers frames internally,
so a `.read()` call after any delay drains from that backlog instead of
grabbing what the camera sees *now*. Measured on a real CP Plus DVR stream:
up to ~7s of lag after a few seconds of the pipeline being busy with
inference. That's enough for a person who crosses quickly to be completely
missed, or for their crossing to be reconstructed from old, mismatched
frames. Setting CAP_PROP_BUFFERSIZE=1 does not reliably fix this — it's
backend/protocol-dependent and wasn't honored here.

The fix: a dedicated background thread continuously drains the real
capture as fast as frames arrive, keeping only the single latest one.
`.read()` never blocks on the network/decoder — it just returns whatever
is freshest right now, dropping anything the pipeline couldn't keep up
with. That trades "process every frame" for "always process a current
one", which is the correct trade-off for real-time counting.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("crowd_monitor.camera")


class LatestFrameReader:
    """Wraps a cv2.VideoCapture-like object (anything with .isOpened(),
    .read() -> (bool, frame), .release()) and exposes the same interface,
    but .read() always returns the most recently grabbed frame instead of
    the next one in an internal queue."""

    def __init__(self, capture, first_frame_timeout: float = 2.0):
        self._capture = capture
        self._lock = threading.Lock()
        self._latest_ok = False
        self._latest_frame = None
        self._stop_event = threading.Event()
        self._first_frame_event = threading.Event()
        self._thread = None

        if self.isOpened():
            self._thread = threading.Thread(target=self._grab_loop, daemon=True)
            self._thread.start()
            # Block briefly for the first frame so callers that expect open()
            # to hand back a capture that's already readable (as a plain
            # cv2.VideoCapture effectively is) see the same behavior.
            self._first_frame_event.wait(timeout=first_frame_timeout)

    def _grab_loop(self):
        while not self._stop_event.is_set():
            try:
                ret, frame = self._capture.read()
            except Exception as exc:  # noqa: BLE001 - never let the grabber thread die silently
                logger.warning("LatestFrameReader: exception during read: %s", exc)
                ret, frame = False, None

            with self._lock:
                self._latest_ok = ret
                self._latest_frame = frame

            if ret:
                self._first_frame_event.set()
            else:
                # Source isn't delivering (closed/failing) -- don't spin-loop.
                self._stop_event.wait(timeout=0.05)

    def isOpened(self) -> bool:
        return bool(self._capture and self._capture.isOpened())

    def read(self):
        with self._lock:
            return self._latest_ok, self._latest_frame

    def release(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._capture is not None:
            self._capture.release()

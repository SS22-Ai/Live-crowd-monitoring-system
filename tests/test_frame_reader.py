"""
Regression tests for LatestFrameReader — the fix for RTSP frame staleness
(see app/camera/frame_reader.py's module docstring for the full story:
measured up to ~7s of lag on a real CP Plus DVR stream, which is enough to
miss a fast-moving person entirely).

Uses a FakeSlowCapture that behaves like a live source producing frames
over time (each .read() call blocks briefly, like a real blocking capture
would) — no real camera/network needed, fully deterministic, runs in well
under a second.

Run: python3 tests/test_frame_reader.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.camera.frame_reader import LatestFrameReader  # noqa: E402


class FakeSlowCapture:
    """Simulates a live source: each .read() blocks `delay` seconds (like a
    real network/decoder call would) and then hands back the next frame in
    sequence. Frames are just increasing ints here — only their identity/
    ordering matters for these tests."""

    def __init__(self, frame_count=50, delay=0.005):
        self._next_frame = 1
        self._frame_count = frame_count
        self._delay = delay
        self._opened = True
        self.release_called = False

    def isOpened(self):
        return self._opened

    def read(self):
        time.sleep(self._delay)
        if self._next_frame > self._frame_count:
            return False, None
        frame = self._next_frame
        self._next_frame += 1
        return True, frame

    def release(self):
        self._opened = False
        self.release_called = True


class NeverOpensCapture:
    def isOpened(self):
        return False

    def read(self):
        raise AssertionError("read() must never be called on a capture that never opened")

    def release(self):
        pass


class LatestFrameReaderTest(unittest.TestCase):
    def test_first_read_is_available_immediately_after_construction(self):
        """open() callers expect a capture that's already readable, the way
        a plain cv2.VideoCapture effectively is once isOpened() is True."""
        reader = LatestFrameReader(FakeSlowCapture(delay=0.005))
        try:
            ret, frame = reader.read()
            self.assertTrue(ret)
            self.assertIsNotNone(frame)
        finally:
            reader.release()

    def test_read_returns_latest_frame_not_the_oldest_queued_one(self):
        """The core regression: if the consumer doesn't call read() for a
        while (simulating slow YOLO inference), the NEXT read() must return
        whatever is freshest, not frame #1 out of a backlog."""
        capture = FakeSlowCapture(frame_count=200, delay=0.002)
        reader = LatestFrameReader(capture)
        try:
            # Let the background grabber run far ahead without us reading.
            time.sleep(0.2)
            ret, frame = reader.read()
            self.assertTrue(ret)
            # With a 2ms per-frame producer and a 200ms stall, dozens of
            # frames were produced -- frame 1 (the stale/oldest) must NOT
            # be what we get back.
            self.assertGreater(frame, 10, "read() returned a stale, queued-up frame instead of the latest one")
        finally:
            reader.release()

    def test_isOpened_delegates_to_underlying_capture(self):
        reader = LatestFrameReader(FakeSlowCapture())
        try:
            self.assertTrue(reader.isOpened())
        finally:
            reader.release()

    def test_release_stops_the_grabber_thread_and_releases_capture(self):
        capture = FakeSlowCapture(delay=0.005)
        reader = LatestFrameReader(capture)
        reader.read()  # make sure the thread actually started grabbing
        reader.release()
        self.assertTrue(capture.release_called)
        self.assertFalse(reader._thread.is_alive())

    def test_never_starts_a_thread_or_reads_if_capture_never_opened(self):
        reader = LatestFrameReader(NeverOpensCapture())
        self.assertIsNone(reader._thread)
        ret, frame = reader.read()
        self.assertFalse(ret)
        self.assertIsNone(frame)
        reader.release()  # must not raise even though nothing was started


if __name__ == "__main__":
    unittest.main(verbosity=2)

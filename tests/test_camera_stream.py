"""
Unit tests for CameraStream's ONLINE/OFFLINE/RECONNECTING state machine.
Uses a FAKE capture backend (no real webcam/network needed) injected via
`capture_factory`, so this genuinely exercises the reconnect logic.
Run: python3 tests/test_camera_stream.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.camera.stream import CameraStream, CameraStatus  # noqa: E402


class FakeCapture:
    """Stands in for cv2.VideoCapture. `should_open` and a queue of
    (ret, frame) read results are controlled by the test."""

    def __init__(self, source, should_open=True, read_results=None):
        self._opened = should_open
        self._read_results = list(read_results) if read_results else []

    def isOpened(self):
        return self._opened

    def read(self):
        if self._read_results:
            return self._read_results.pop(0)
        return True, "FRAME"

    def release(self):
        self._opened = False


def factory_always_opens(source):
    return FakeCapture(source, should_open=True)


def factory_never_opens(source):
    return FakeCapture(source, should_open=False)


class TestCameraStream(unittest.TestCase):

    def test_successful_open_is_online(self):
        cs = CameraStream(0, "cam1", capture_factory=factory_always_opens)
        ok = cs.open()
        self.assertTrue(ok)
        self.assertEqual(cs.status, CameraStatus.ONLINE)

    def test_failed_open_transitions_toward_offline(self):
        cs = CameraStream(
            0, "cam1", capture_factory=factory_never_opens,
            max_reconnect_attempts_before_offline=2,
        )
        cs.open()
        self.assertEqual(cs.status, CameraStatus.RECONNECTING)
        cs.open()
        self.assertEqual(cs.status, CameraStatus.OFFLINE)

    def test_read_success_returns_frame(self):
        cs = CameraStream(0, "cam1", capture_factory=factory_always_opens)
        cs.open()
        ok, frame = cs.read()
        self.assertTrue(ok)
        self.assertEqual(frame, "FRAME")

    def test_read_failure_does_not_raise_and_marks_reconnecting(self):
        def factory(source):
            return FakeCapture(source, should_open=True, read_results=[(False, None)])

        cs = CameraStream(0, "cam1", capture_factory=factory, reconnect_interval_seconds=0)
        cs.open()
        ok, frame = cs.read()
        self.assertFalse(ok)
        self.assertIsNone(frame)
        self.assertIn(cs.status, (CameraStatus.RECONNECTING, CameraStatus.OFFLINE))

    def test_one_camera_failing_does_not_affect_a_second_camera_instance(self):
        """Spec section 13: Camera 1 must keep working if Camera 2 fails."""
        cam1 = CameraStream(0, "event_entrance", capture_factory=factory_always_opens)
        cam2 = CameraStream(1, "dining_entrance", capture_factory=factory_never_opens)

        cam1.open()
        cam2.open()

        self.assertEqual(cam1.status, CameraStatus.ONLINE)
        self.assertIn(cam2.status, (CameraStatus.RECONNECTING, CameraStatus.OFFLINE))

        ok, frame = cam1.read()
        self.assertTrue(ok)
        self.assertEqual(frame, "FRAME")

    def test_exception_during_open_is_caught_not_raised(self):
        def exploding_factory(source):
            raise RuntimeError("simulated driver failure")

        cs = CameraStream(0, "cam1", capture_factory=exploding_factory)
        ok = cs.open()  # must not raise
        self.assertFalse(ok)
        self.assertIn(cs.status, (CameraStatus.RECONNECTING, CameraStatus.OFFLINE))

    def test_release_sets_offline(self):
        cs = CameraStream(0, "cam1", capture_factory=factory_always_opens)
        cs.open()
        self.assertEqual(cs.status, CameraStatus.ONLINE)
        cs.release()
        self.assertEqual(cs.status, CameraStatus.OFFLINE)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
Tests for the stuck-camera watchdog's tracking logic (CameraPipeline.
seconds_stuck_offline / CameraManager.max_seconds_stuck_offline).

Real-world motivation (2026-09-13): a USB webcam unplugged/replugged
while the app is running can leave CameraStream permanently unable to
reopen it in-process, even though a brand-new process opens the same
index fine immediately -- a known macOS/OpenCV AVFoundation limitation,
not a bug in the reconnect loop itself (confirmed live: dozens of
in-process reopen attempts all failed while a fresh `python
test_camera.py` process opened the same index without issue). The actual
fix is a full process restart (app/main.py's watchdog thread + the
launchd supervisor in deploy/); this file only tests the pure tracking
logic that decides *when* to trigger that restart -- no real camera,
thread, or process signal involved.

Run: python3 tests/test_stuck_camera_watchdog.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.camera.manager import CameraManager, CameraPipeline  # noqa: E402
from app.camera.stream import CameraStatus  # noqa: E402
from app.config import CameraConfig  # noqa: E402


def make_pipeline(camera_id="cam1", source=0):
    cfg = CameraConfig(id=camera_id, name=camera_id, source=source, enabled=True)
    return CameraPipeline(
        cfg, detector=None, db=None, session_id_getter=lambda: None,
        inference_width=640, inference_height=480,
    )


class TestSecondsStuckOffline(unittest.TestCase):
    def test_never_online_is_never_stuck(self):
        # A camera that has NEVER connected (e.g. genuinely unreachable) must
        # not trigger the watchdog -- restarting the whole process would just
        # disrupt every OTHER camera's pipeline too, forever, for a camera a
        # restart can't actually help.
        p = make_pipeline()
        p.stream._status = CameraStatus.OFFLINE
        p._track_stuck_state()
        self.assertEqual(p.seconds_stuck_offline(), 0.0)

    def test_currently_online_is_not_stuck(self):
        p = make_pipeline()
        p.stream._status = CameraStatus.ONLINE
        p._track_stuck_state()
        self.assertEqual(p.seconds_stuck_offline(), 0.0)

    def test_online_then_offline_is_stuck(self):
        p = make_pipeline()
        p.stream._status = CameraStatus.ONLINE
        p._track_stuck_state()
        p.stream._status = CameraStatus.OFFLINE
        p._track_stuck_state()
        p._offline_since -= 100  # backdate instead of a real sleep
        self.assertGreaterEqual(p.seconds_stuck_offline(), 100)

    def test_recovering_to_online_resets_the_clock(self):
        p = make_pipeline()
        p.stream._status = CameraStatus.ONLINE
        p._track_stuck_state()
        p.stream._status = CameraStatus.OFFLINE
        p._track_stuck_state()
        p._offline_since -= 100
        p.stream._status = CameraStatus.ONLINE
        p._track_stuck_state()
        self.assertEqual(p.seconds_stuck_offline(), 0.0)

    def test_reconnecting_status_counts_as_stuck_too(self):
        # RECONNECTING is still "not ONLINE" -- a camera flapping between
        # RECONNECTING and OFFLINE without ever reaching ONLINE again must
        # still accumulate stuck time.
        p = make_pipeline()
        p.stream._status = CameraStatus.ONLINE
        p._track_stuck_state()
        p.stream._status = CameraStatus.RECONNECTING
        p._track_stuck_state()
        p._offline_since -= 100
        self.assertGreaterEqual(p.seconds_stuck_offline(), 100)


class TestManagerMaxSecondsStuckOffline(unittest.TestCase):
    def setUp(self):
        self.manager = CameraManager(
            camera_configs=[
                CameraConfig(id="a", name="A", source=0, enabled=True),
                CameraConfig(id="b", name="B", source=1, enabled=True),
            ],
            detector_factory=lambda: None,
            db=None,
            session_id_getter=lambda: None,
            inference_width=640,
            inference_height=480,
        )

    def test_reports_the_worst_camera(self):
        pa = self.manager.pipelines["a"]
        pb = self.manager.pipelines["b"]
        for p, seconds in ((pa, 10), (pb, 500)):
            p.stream._status = CameraStatus.ONLINE
            p._track_stuck_state()
            p.stream._status = CameraStatus.OFFLINE
            p._track_stuck_state()
            p._offline_since -= seconds
        self.assertGreaterEqual(self.manager.max_seconds_stuck_offline(), 500)

    def test_zero_when_nothing_stuck(self):
        self.assertEqual(self.manager.max_seconds_stuck_offline(), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

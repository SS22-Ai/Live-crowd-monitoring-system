"""
Real-hardware smoke test for the YOLO + ByteTrack + MPS path.

Unlike tests/test_detector.py (which uses FAKE torch/ultralytics), this
runs the genuine stack. It is SKIPPED automatically unless:
  - `ultralytics` and a real `torch` import, AND
  - the model file models/yolo11n.pt already exists on disk
    (so the suite never triggers a network download).

When it does run it asserts that PersonDetector.track() returns real
Detection objects with integer track IDs for a picture that contains
people (Ultralytics' bundled bus.jpg), and that draw.py renders over
that real output without error.

Run: python3 tests/test_real_yolo_smoke.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "yolo11n.pt")


def _stack_available():
    if not os.path.exists(MODEL_PATH):
        return False
    try:
        import torch  # noqa: F401
        import ultralytics  # noqa: F401
        import cv2  # noqa: F401
    except Exception:
        return False
    return True


@unittest.skipUnless(
    _stack_available(),
    "real torch/ultralytics/cv2 + models/yolo11n.pt required (skipped in the build sandbox)",
)
class RealYoloSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        from ultralytics.utils import ASSETS
        from app.vision.detector import PersonDetector

        cls.cv2 = cv2
        cls.bus = cv2.imread(os.path.join(ASSETS, "bus.jpg"))
        assert cls.bus is not None, "could not load bundled bus.jpg"
        cls.detector = PersonDetector(model_path=MODEL_PATH, confidence=0.4)

    def test_device_is_mps_or_cpu(self):
        self.assertIn(self.detector.device, ("mps", "cpu"))

    def test_detects_people_with_integer_track_ids(self):
        dets = None
        # ByteTrack may need a frame or two to confirm IDs; give it a few.
        for _ in range(5):
            dets = self.detector.track(self.bus)
            if dets:
                break
        self.assertTrue(dets, "expected at least one person detection in bus.jpg")
        for d in dets:
            self.assertIsInstance(d.track_id, int)
            self.assertGreater(d.confidence, 0.0)
            self.assertLess(d.x1, d.x2)
            self.assertLess(d.y1, d.y2)

    def test_track_ids_are_stable_across_frames(self):
        first = {d.track_id for d in self.detector.track(self.bus)}
        second = {d.track_id for d in self.detector.track(self.bus)}
        self.assertTrue(first)
        # the same still frame -> the same tracked people
        self.assertEqual(first, second)

    def test_draw_frame_renders_over_real_detections(self):
        from app.vision.draw import draw_frame
        from app.vision.line_counter import LineCounter

        dets = self.detector.track(self.bus)
        h, w = self.bus.shape[:2]
        lc = LineCounter(frame_width=w, line_position=0.5, line_buffer=20)
        out = draw_frame(
            self.bus.copy(), dets, line_x=int(lc.line_x), line_buffer=20,
            camera_name="smoke", entries=0, exits=0, live_occupancy=0, status="ONLINE",
        )
        self.assertEqual(out.shape, self.bus.shape)
        ok, jpeg = self.cv2.imencode(".jpg", out)
        self.assertTrue(ok)
        self.assertGreater(len(jpeg.tobytes()), 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)

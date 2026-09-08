"""
Regression test for the shared-detector bug: CameraManager must give
each ENABLED camera its own PersonDetector instance (via a factory),
never share one model object across camera threads — sharing would
corrupt ByteTrack's persist=True tracker state across unrelated video
streams. Disabled cameras must not trigger a model load at all.

Uses a fake detector_factory (no real ultralytics/torch needed) and
constructs CameraPipeline objects directly — cv2 IS available in this
sandbox, so CameraStream construction (no actual camera open) is safe.

Run: python3 tests/test_camera_manager.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.camera.manager import CameraManager  # noqa: E402
from app.config import CameraConfig  # noqa: E402


class FakeDetector:
    """Stands in for PersonDetector — identity is all that matters here."""
    _next_id = 0

    def __init__(self):
        FakeDetector._next_id += 1
        self.instance_id = FakeDetector._next_id


def make_camera_configs():
    return [
        CameraConfig(id="event_entrance", name="Event Entrance", source=0, enabled=True),
        CameraConfig(id="dining_entrance", name="Dining Entrance", source=1, enabled=True),
        CameraConfig(id="storage_room", name="Storage Room", source=2, enabled=False),
    ]


class TestCameraManagerDetectorIsolation(unittest.TestCase):
    def setUp(self):
        FakeDetector._next_id = 0
        self.factory_call_count = 0

        def factory():
            self.factory_call_count += 1
            return FakeDetector()

        self.factory = factory
        self.manager = CameraManager(
            camera_configs=make_camera_configs(),
            detector_factory=self.factory,
            db=None,  # not exercised in this test — no db calls happen at construction time
            session_id_getter=lambda: None,
            inference_width=640,
            inference_height=480,
        )

    def test_each_enabled_camera_gets_a_distinct_detector_instance(self):
        det1 = self.manager.pipelines["event_entrance"].detector
        det2 = self.manager.pipelines["dining_entrance"].detector
        self.assertIsNotNone(det1)
        self.assertIsNotNone(det2)
        self.assertIsNot(det1, det2, "cameras must NOT share the same detector/model instance")
        self.assertNotEqual(det1.instance_id, det2.instance_id)

    def test_disabled_camera_gets_no_detector_and_no_model_load(self):
        pipeline = self.manager.pipelines["storage_room"]
        self.assertIsNone(pipeline.detector)

    def test_factory_called_exactly_once_per_enabled_camera(self):
        # 2 enabled cameras -> exactly 2 factory calls, NOT 3 (disabled
        # camera must not trigger a model load) and NOT 1 (would mean sharing)
        self.assertEqual(self.factory_call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

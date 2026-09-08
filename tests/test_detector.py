"""
Tests for PersonDetector / select_device using FAKE ultralytics/torch
modules injected into sys.modules.

IMPORTANT — what this test suite proves and does NOT prove:
  - detector.py imports `ultralytics` and `torch` lazily (inside
    functions), so we can substitute fake modules shaped like the real
    API and verify detector.py's OWN logic is correct: how it turns
    YOLO's result objects into Detection instances, how it handles the
    "no tracks yet" / "no results" cases, how it reacts to a model load
    failure, and the MPS/CPU device selection branch.
  - This does NOT prove real YOLO detects a real person, does NOT prove
    ByteTrack behaves correctly on real video, and does NOT prove MPS
    actually works on Apple Silicon. Those require the real libraries
    installed on real hardware — which this sandbox does not have.

Run: python3 tests/test_detector.py
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402


class FakeTensor:
    """Stands in for a torch.Tensor: real ultralytics results expose
    .xyxy / .id / .conf as tensors with a .cpu().numpy() chain."""

    def __init__(self, array):
        self._array = np.array(array)

    def cpu(self):
        return self

    def numpy(self):
        return self._array


class FakeBoxes:
    def __init__(self, xyxy=None, ids=None, confs=None):
        self.xyxy = FakeTensor(xyxy if xyxy is not None else [])
        self.id = FakeTensor(ids) if ids is not None else None
        self.conf = FakeTensor(confs if confs is not None else [])


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class FakeYOLOModel:
    """Stands in for ultralytics.YOLO(model_path)."""

    instances = []  # track constructed instances for assertions

    def __init__(self, model_path):
        self.model_path = model_path
        self.track_kwargs_history = []
        self._next_results = []
        FakeYOLOModel.instances.append(self)

    def set_next_track_result(self, results):
        self._next_results = results

    def track(self, frame, **kwargs):
        self.track_kwargs_history.append(kwargs)
        return self._next_results


# When a real `torch` / `ultralytics` is installed on the machine running
# the tests (i.e. anywhere but the original build sandbox), we must NOT
# just pop them from sys.modules after faking — re-importing torch later
# in the same process raises "Only a single TORCH_LIBRARY can be used".
# So we stash whatever was there and put it back verbatim in uninstall.
_SAVED_MODULES = {}


def _install_fake(name, module):
    if name not in _SAVED_MODULES:
        _SAVED_MODULES[name] = sys.modules.get(name, _MISSING)
    sys.modules[name] = module


_MISSING = object()


def install_fake_ultralytics(model_cls=FakeYOLOModel):
    fake_module = types.ModuleType("ultralytics")
    fake_module.YOLO = model_cls
    _install_fake("ultralytics", fake_module)


def install_fake_torch(mps_available: bool):
    fake_backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: mps_available)
    )
    fake_torch = types.ModuleType("torch")
    fake_torch.backends = fake_backends
    _install_fake("torch", fake_torch)


def uninstall_fakes():
    for name, original in list(_SAVED_MODULES.items()):
        if original is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
        del _SAVED_MODULES[name]


class TestSelectDevice(unittest.TestCase):
    def tearDown(self):
        uninstall_fakes()

    def test_selects_mps_when_available(self):
        install_fake_torch(mps_available=True)
        from app.vision.detector import select_device
        self.assertEqual(select_device(), "mps")

    def test_falls_back_to_cpu_when_mps_unavailable(self):
        install_fake_torch(mps_available=False)
        from app.vision.detector import select_device
        self.assertEqual(select_device(), "cpu")

    def test_falls_back_to_cpu_when_torch_missing_entirely(self):
        # Simulate torch genuinely not being installed. Setting the module
        # to None in sys.modules makes `import torch` raise ImportError,
        # which works whether or not a real torch is installed on the host
        # running the tests (the original version only passed on a machine
        # that happened to have no torch at all).
        with mock.patch.dict(sys.modules, {"torch": None}):
            from app.vision.detector import select_device
            self.assertEqual(select_device(), "cpu")


class TestPersonDetectorLoading(unittest.TestCase):
    def setUp(self):
        FakeYOLOModel.instances = []
        install_fake_torch(mps_available=False)
        install_fake_ultralytics()

    def tearDown(self):
        uninstall_fakes()

    def test_loads_model_with_configured_path(self):
        from app.vision.detector import PersonDetector
        det = PersonDetector(model_path="models/yolo11n.pt", confidence=0.4)
        self.assertEqual(det.model.model_path, "models/yolo11n.pt")
        self.assertEqual(det.device, "cpu")

    def test_prints_selected_device_at_startup(self):
        from app.vision.detector import PersonDetector
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            PersonDetector(model_path="models/yolo11n.pt")
        self.assertIn("Using device: CPU", buf.getvalue())

    def test_model_load_failure_raises_helpful_runtime_error(self):
        class ExplodingYOLO:
            def __init__(self, model_path):
                raise OSError("model file not found")

        install_fake_ultralytics(model_cls=ExplodingYOLO)
        from app.vision.detector import PersonDetector
        with self.assertRaises(RuntimeError) as ctx:
            PersonDetector(model_path="models/missing.pt")
        self.assertIn("missing.pt", str(ctx.exception))


class TestPersonDetectorTrack(unittest.TestCase):
    def setUp(self):
        FakeYOLOModel.instances = []
        install_fake_torch(mps_available=False)
        install_fake_ultralytics()
        from app.vision.detector import PersonDetector
        self.detector = PersonDetector(model_path="models/yolo11n.pt", confidence=0.4)
        self.fake_model = FakeYOLOModel.instances[-1]

    def tearDown(self):
        uninstall_fakes()

    def test_parses_multiple_detections_into_Detection_objects(self):
        boxes = FakeBoxes(
            xyxy=[[100, 150, 200, 400], [350, 180, 450, 420]],
            ids=[7, 12],
            confs=[0.91, 0.87],
        )
        self.fake_model.set_next_track_result([FakeResult(boxes)])

        detections = self.detector.track(frame="FAKE_FRAME")

        self.assertEqual(len(detections), 2)
        self.assertEqual(detections[0].track_id, 7)
        self.assertEqual(detections[0].x1, 100.0)
        self.assertEqual(detections[0].y2, 400.0)
        self.assertAlmostEqual(detections[0].confidence, 0.91)
        self.assertEqual(detections[1].track_id, 12)

    def test_bottom_center_computed_correctly_from_real_track_output(self):
        boxes = FakeBoxes(xyxy=[[100, 150, 200, 400]], ids=[7], confs=[0.9])
        self.fake_model.set_next_track_result([FakeResult(boxes)])
        detections = self.detector.track(frame="FAKE_FRAME")
        self.assertEqual(detections[0].bottom_center, (150.0, 400.0))

    def test_no_results_returns_empty_list(self):
        self.fake_model.set_next_track_result([])
        detections = self.detector.track(frame="FAKE_FRAME")
        self.assertEqual(detections, [])

    def test_no_confirmed_tracks_yet_returns_empty_list(self):
        """boxes.id is None the first frame(s) before ByteTrack confirms
        a track — must not crash, must return no detections."""
        boxes = FakeBoxes(xyxy=[[10, 10, 50, 50]], ids=None, confs=[0.5])
        self.fake_model.set_next_track_result([FakeResult(boxes)])
        detections = self.detector.track(frame="FAKE_FRAME")
        self.assertEqual(detections, [])

    def test_no_boxes_at_all_returns_empty_list(self):
        self.fake_model.set_next_track_result([FakeResult(boxes=None)])
        detections = self.detector.track(frame="FAKE_FRAME")
        self.assertEqual(detections, [])

    def test_track_call_restricts_to_person_class_only(self):
        from app.vision.detector import PERSON_CLASS_ID
        boxes = FakeBoxes(xyxy=[[0, 0, 1, 1]], ids=[1], confs=[0.5])
        self.fake_model.set_next_track_result([FakeResult(boxes)])
        self.detector.track(frame="FAKE_FRAME")
        last_call = self.fake_model.track_kwargs_history[-1]
        self.assertEqual(last_call["classes"], [PERSON_CLASS_ID])
        self.assertEqual(last_call["tracker"], "bytetrack.yaml")
        self.assertTrue(last_call["persist"])

    def test_track_ids_are_cast_to_int(self):
        """ids come back as floats from numpy/torch in real ultralytics —
        confirm we cast to int rather than leaving track_id as 7.0."""
        boxes = FakeBoxes(xyxy=[[0, 0, 1, 1]], ids=[7.0], confs=[0.5])
        self.fake_model.set_next_track_result([FakeResult(boxes)])
        detections = self.detector.track(frame="FAKE_FRAME")
        self.assertIsInstance(detections[0].track_id, int)
        self.assertEqual(detections[0].track_id, 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)

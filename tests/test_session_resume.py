"""
Regression tests for crash-recovery session resume (P0, added 2026-09-12).

The gap: on every startup, the app used to unconditionally start a brand
new session (db.start_session()), so if the process crashed instead of
shutting down cleanly, the live occupancy count silently reset to 0 on
restart even though the crossing_events for the people still inside were
safely sitting in the database the whole time.

The fix distinguishes "the app crashed last time" from "this is a clean
restart / first run" using the same ended_at column the shutdown hook
already writes: a session whose ended_at is still NULL at startup means
on_shutdown() never ran last time. app/main.py's resolve_startup_session()
makes that decision; app/camera/manager.py's CameraManager replays the
resumed session's recorded events back into each camera's counters.

Uses a real temporary SQLite Database (same pattern as
test_integration_pipeline.py) and a FakeDetector factory (same pattern as
test_camera_manager.py) -- no real camera, model, or server needed.

Run: python3 tests/test_session_resume.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.camera.manager import CameraManager  # noqa: E402
from app.config import CameraConfig  # noqa: E402
from app.database.database import Database  # noqa: E402
from app.main import resolve_startup_session  # noqa: E402


def make_temp_db() -> Database:
    tmp_dir = tempfile.mkdtemp()
    return Database(os.path.join(tmp_dir, "test.db"))


class FakeDetector:
    def __init__(self):
        pass


def make_camera_configs():
    return [
        CameraConfig(id="event_entrance", name="Event Entrance", source=0, enabled=True),
        CameraConfig(id="dining_entrance", name="Dining Entrance", source=1, enabled=True),
    ]


class ResolveStartupSessionTest(unittest.TestCase):
    def setUp(self):
        self.db = make_temp_db()

    def tearDown(self):
        self.db.close()

    def test_first_ever_run_starts_a_new_session(self):
        session_id, resumed = resolve_startup_session(self.db)
        self.assertFalse(resumed)
        self.assertIsNotNone(session_id)

    def test_clean_previous_stop_starts_a_new_session(self):
        old_id = self.db.start_session()
        self.db.end_session(old_id)  # simulates the shutdown hook running normally

        session_id, resumed = resolve_startup_session(self.db)

        self.assertFalse(resumed)
        self.assertNotEqual(session_id, old_id, "a cleanly-closed session must not be reused")

    def test_crash_resumes_the_unclosed_session(self):
        old_id = self.db.start_session()
        # no end_session() call -- simulates a crash / force-kill

        session_id, resumed = resolve_startup_session(self.db)

        self.assertTrue(resumed)
        self.assertEqual(session_id, old_id)

    def test_repeated_crashes_keep_resuming_the_same_session(self):
        old_id = self.db.start_session()

        first_id, first_resumed = resolve_startup_session(self.db)
        second_id, second_resumed = resolve_startup_session(self.db)

        self.assertTrue(first_resumed and second_resumed)
        self.assertEqual(first_id, old_id)
        self.assertEqual(second_id, old_id)


class CameraManagerResumeTest(unittest.TestCase):
    def setUp(self):
        self.db = make_temp_db()

    def tearDown(self):
        self.db.close()

    def test_resume_session_id_replays_recorded_counts_per_camera(self):
        session_id = self.db.start_session()
        # event_entrance: 5 people currently inside (5 in, 2 out)
        for _ in range(5):
            self.db.record_event(session_id, "event_entrance", track_id=1, event_type="ENTRY")
        for _ in range(2):
            self.db.record_event(session_id, "event_entrance", track_id=1, event_type="EXIT")
        # dining_entrance: nobody has crossed yet
        # (no events recorded)

        manager = CameraManager(
            camera_configs=make_camera_configs(),
            detector_factory=FakeDetector,
            db=self.db,
            session_id_getter=lambda: session_id,
            inference_width=640,
            inference_height=480,
            resume_session_id=session_id,
        )

        event_pipeline = manager.pipelines["event_entrance"]
        self.assertEqual(event_pipeline.line_counter.entries, 5)
        self.assertEqual(event_pipeline.line_counter.exits, 2)
        self.assertEqual(event_pipeline.occupancy.entries, 5)
        self.assertEqual(event_pipeline.occupancy.exits, 2)
        self.assertEqual(event_pipeline.occupancy.live_occupancy, 3)

        dining_pipeline = manager.pipelines["dining_entrance"]
        self.assertEqual(dining_pipeline.line_counter.entries, 0)
        self.assertEqual(dining_pipeline.occupancy.live_occupancy, 0)

    def test_no_resume_session_id_leaves_counts_at_zero(self):
        """Default/normal startup path (resume_session_id=None) must behave
        exactly as before this fix -- no regression for the common case."""
        session_id = self.db.start_session()
        self.db.record_event(session_id, "event_entrance", track_id=1, event_type="ENTRY")

        manager = CameraManager(
            camera_configs=make_camera_configs(),
            detector_factory=FakeDetector,
            db=self.db,
            session_id_getter=lambda: session_id,
            inference_width=640,
            inference_height=480,
            # resume_session_id intentionally omitted -> defaults to None
        )

        pipeline = manager.pipelines["event_entrance"]
        self.assertEqual(pipeline.line_counter.entries, 0)
        self.assertEqual(pipeline.occupancy.live_occupancy, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

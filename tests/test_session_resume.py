"""
Regression tests for session persistence across restarts (P0, added
2026-09-12; broadened 2026-09-12 per explicit request).

The gap: on every startup, the app used to unconditionally start a brand
new session (db.start_session()), so any restart -- a crash, or even just
stopping and starting it again on purpose -- silently reset live occupancy
to 0, even though the crossing_events were safely sitting in the database
the whole time.

The fix: data now persists across EVERY restart, clean or not.
app/main.py's resolve_startup_session() always resumes the most recent
session (if any exists at all) rather than only resuming after a crash;
app/camera/manager.py's CameraManager replays that session's recorded
events back into each camera's counters. The ONLY thing that actually
resets counts for good is an explicit user action -- POST /api/reset or
POST /api/session/start, both of which now go through
app/api/routes.py's begin_fresh_session(): it closes the current session
and opens a new one, so a later restart resumes the NEW (zeroed) session
instead of replaying the old numbers back.

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

from app.api.routes import begin_fresh_session  # noqa: E402
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

    def test_clean_previous_stop_still_resumes(self):
        """Data must persist across an ORDINARY restart too, not just a
        crash -- the user only wants counts to reset via an explicit
        Reset counts / Start new session action (see begin_fresh_session),
        never just because the process was stopped and started again."""
        old_id = self.db.start_session()
        self.db.end_session(old_id)  # simulates the shutdown hook running normally

        session_id, resumed = resolve_startup_session(self.db)

        self.assertTrue(resumed)
        self.assertEqual(session_id, old_id, "a cleanly-closed session must still be reused on restart")

    def test_crash_also_resumes_the_unclosed_session(self):
        old_id = self.db.start_session()
        # no end_session() call -- simulates a crash / force-kill

        session_id, resumed = resolve_startup_session(self.db)

        self.assertTrue(resumed)
        self.assertEqual(session_id, old_id)

    def test_repeated_restarts_keep_resuming_the_same_session(self):
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


class BeginFreshSessionTest(unittest.TestCase):
    """begin_fresh_session() backs both POST /api/reset and
    POST /api/session/start -- it's the only thing that makes a reset
    stick across a later restart."""

    def setUp(self):
        self.db = make_temp_db()

    def tearDown(self):
        self.db.close()

    def _manager_with_history(self, session_id):
        for _ in range(4):
            self.db.record_event(session_id, "event_entrance", track_id=1, event_type="ENTRY")
        return CameraManager(
            camera_configs=make_camera_configs(),
            detector_factory=FakeDetector,
            db=self.db,
            session_id_getter=lambda: session_id,
            inference_width=640,
            inference_height=480,
            resume_session_id=session_id,
        )

    def test_closes_the_old_session_and_opens_a_new_one(self):
        old_id = self.db.start_session()
        manager = self._manager_with_history(old_id)
        session_state = {"session_id": old_id}

        new_id = begin_fresh_session(self.db, session_state, manager)

        self.assertNotEqual(new_id, old_id)
        self.assertEqual(session_state["session_id"], new_id)
        old_record = self.db.get_session(old_id)
        self.assertIsNotNone(old_record.ended_at, "the old session must be marked closed")

    def test_resets_every_camera_counter_to_zero(self):
        old_id = self.db.start_session()
        manager = self._manager_with_history(old_id)
        self.assertEqual(manager.pipelines["event_entrance"].line_counter.entries, 4)  # sanity check

        begin_fresh_session(self.db, {"session_id": old_id}, manager)

        pipeline = manager.pipelines["event_entrance"]
        self.assertEqual(pipeline.line_counter.entries, 0)
        self.assertEqual(pipeline.occupancy.live_occupancy, 0)

    def test_a_later_restart_resumes_the_new_zeroed_session_not_the_old_numbers(self):
        """End-to-end guard for the actual user complaint: after Reset
        counts, restarting the app must NOT bring the old numbers back."""
        old_id = self.db.start_session()
        manager = self._manager_with_history(old_id)
        session_state = {"session_id": old_id}

        new_id = begin_fresh_session(self.db, session_state, manager)

        resumed_id, resumed = resolve_startup_session(self.db)
        self.assertTrue(resumed)
        self.assertEqual(resumed_id, new_id, "restart after a reset must resume the NEW session, not the old one")

        fresh_manager = CameraManager(
            camera_configs=make_camera_configs(),
            detector_factory=FakeDetector,
            db=self.db,
            session_id_getter=lambda: resumed_id,
            inference_width=640,
            inference_height=480,
            resume_session_id=resumed_id,
        )
        self.assertEqual(fresh_manager.pipelines["event_entrance"].line_counter.entries, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

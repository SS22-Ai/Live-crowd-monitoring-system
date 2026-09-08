"""
Integration test: the post-detection half of CameraPipeline._run, wired
together for real — LineCounter -> OccupancyManager -> SQLite Database —
exercised through the four physical walk-through scenarios in README §6.

No camera and no YOLO/torch needed: this feeds the exact
(track_id, bottom_center_x, bottom_center_y) tuples the real detector
emits (`[(d.track_id, *d.bottom_center) for d in detections]` in
app/camera/manager.py) for a person walking across the frame, and asserts
the ENTRY/EXIT counts, the live-occupancy number, and the rows persisted
to a real (temp-file) SQLite database.

Run: python3 tests/test_integration_pipeline.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.vision.line_counter import LineCounter, EventType  # noqa: E402
from app.occupancy.manager import OccupancyManager  # noqa: E402
from app.database.database import Database  # noqa: E402

FRAME_WIDTH = 640  # line at 320, buffer 20 -> LEFT < 300, RIGHT > 340
CAM_ID = "event_entrance"


class Pipeline:
    """Mirrors the relevant part of app/camera/manager.py CameraPipeline."""

    def __init__(self, db, session_id, entry_direction="left_to_right"):
        self.db = db
        self.session_id = session_id
        self.line_counter = LineCounter(
            frame_width=FRAME_WIDTH,
            line_position=0.50,
            line_buffer=20,
            entry_direction=entry_direction,
            track_expiry_seconds=2.0,
        )
        self.occupancy = OccupancyManager(CAM_ID, initial_occupancy=0)

    def feed(self, detections, now):
        """detections: list of (track_id, x). y is fixed (bottom of bbox)."""
        points = [(tid, float(x), 400.0) for tid, x in detections]
        events = self.line_counter.update(points, now=now)
        for ev in events:
            if ev.event_type == EventType.ENTRY:
                self.occupancy.record_entry()
            else:
                self.occupancy.record_exit()
            self.db.record_event(
                self.session_id, CAM_ID, ev.track_id, ev.event_type.value, ev.timestamp
            )
        return events


class IntegrationPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, "it.db"))
        self.session_id = self.db.start_session()

    def tearDown(self):
        self.db.close()

    def _walk(self, pipe, track_ids, xs, t0=0.0, dt=0.1):
        t = t0
        for x in xs:
            pipe.feed([(tid, x) for tid in track_ids], now=t)
            t += dt
        return t

    def test_scenario_1_left_to_right_is_one_entry(self):
        pipe = Pipeline(self.db, self.session_id)
        self._walk(pipe, [1], range(200, 460, 20))
        self.assertEqual(pipe.line_counter.entries, 1)
        self.assertEqual(pipe.line_counter.exits, 0)
        self.assertEqual(pipe.occupancy.live_occupancy, 1)

    def test_scenario_2_round_trip_entry_then_exit(self):
        pipe = Pipeline(self.db, self.session_id)
        t = self._walk(pipe, [1], range(200, 460, 20))
        self._walk(pipe, [1], range(440, 180, -20), t0=t)
        self.assertEqual(pipe.line_counter.entries, 1)
        self.assertEqual(pipe.line_counter.exits, 1)
        self.assertEqual(pipe.occupancy.live_occupancy, 0)

    def test_scenario_3_jitter_near_line_never_counts(self):
        pipe = Pipeline(self.db, self.session_id)
        # wobbles through the buffer but never resolves to the far side
        xs = [280, 305, 315, 325, 315, 305, 295, 310, 318, 299, 302, 298]
        self._walk(pipe, [1], xs)
        self.assertEqual(pipe.line_counter.entries, 0)
        self.assertEqual(pipe.line_counter.exits, 0)
        self.assertEqual(pipe.occupancy.live_occupancy, 0)
        self.assertEqual(
            self.db.get_events(session_id=self.session_id), []
        )

    def test_scenario_4_two_people_tracked_independently(self):
        pipe = Pipeline(self.db, self.session_id)
        t = self._walk(pipe, [10, 11], range(200, 460, 20))
        self.assertEqual(pipe.line_counter.entries, 2)
        self.assertEqual(pipe.occupancy.live_occupancy, 2)
        self._walk(pipe, [10, 11], range(440, 180, -20), t0=t)
        self.assertEqual(pipe.line_counter.entries, 2)
        self.assertEqual(pipe.line_counter.exits, 2)
        self.assertEqual(pipe.occupancy.live_occupancy, 0)

        rows = self.db.get_events(session_id=self.session_id)
        self.assertEqual(len(rows), 4)
        self.assertEqual({r.track_id for r in rows}, {10, 11})
        self.assertEqual(sum(r.event_type == "ENTRY" for r in rows), 2)
        self.assertEqual(sum(r.event_type == "EXIT" for r in rows), 2)

    def test_reset_direction_makes_right_to_left_the_entry(self):
        pipe = Pipeline(self.db, self.session_id, entry_direction="right_to_left")
        self._walk(pipe, [1], range(440, 180, -20))
        self.assertEqual(pipe.line_counter.entries, 1)
        self.assertEqual(pipe.line_counter.exits, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

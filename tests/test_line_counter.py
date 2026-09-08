"""
Unit tests for LineCounter. These simulate track positions frame-by-frame
(no camera/YOLO needed) to verify the counting logic itself is correct —
this is the part of the spec (sections 4, 11, 26) that matters most.

Zero extra dependencies (stdlib unittest only).
Run: python3 tests/test_line_counter.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.vision.line_counter import LineCounter, EventType  # noqa: E402

FRAME_WIDTH = 1280  # line at 640, buffer 20 -> LEFT < 620, RIGHT > 660


def make_counter(entry_direction="left_to_right"):
    return LineCounter(
        frame_width=FRAME_WIDTH,
        line_position=0.5,
        line_buffer=20,
        entry_direction=entry_direction,
        track_expiry_seconds=2.0,
    )


class TestLineCounter(unittest.TestCase):

    def test_single_left_to_right_crossing_is_one_entry(self):
        lc = make_counter()
        xs = [400, 500, 600, 640, 700, 800, 900]
        events = []
        for i, x in enumerate(xs):
            events += lc.update([(1, x, 400)], now=i * 0.1)
        self.assertEqual(lc.entries, 1)
        self.assertEqual(lc.exits, 0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, EventType.ENTRY)

    def test_single_right_to_left_crossing_is_one_exit(self):
        lc = make_counter()
        xs = [900, 800, 700, 640, 600, 500, 400]
        for i, x in enumerate(xs):
            lc.update([(1, x, 400)], now=i * 0.1)
        self.assertEqual(lc.entries, 0)
        self.assertEqual(lc.exits, 1)

    def test_enter_then_exit_round_trip(self):
        lc = make_counter()
        left_to_right = [400, 500, 640, 700, 900]
        right_to_left = [900, 700, 640, 500, 400]
        t = 0.0
        for x in left_to_right:
            lc.update([(1, x, 400)], now=t)
            t += 0.1
        for x in right_to_left:
            lc.update([(1, x, 400)], now=t)
            t += 0.1
        self.assertEqual(lc.entries, 1)
        self.assertEqual(lc.exits, 1)

    def test_person_hovering_near_line_does_not_double_count(self):
        """Spec: a person near the line must not continuously generate events."""
        lc = make_counter()
        xs = [400, 500, 600, 615, 625, 618, 630, 610, 600, 500, 400]
        all_events = []
        for i, x in enumerate(xs):
            all_events += lc.update([(1, x, 400)], now=i * 0.1)
        self.assertEqual(lc.entries, 0)
        self.assertEqual(lc.exits, 0)
        self.assertEqual(len(all_events), 0)

    def test_standing_still_on_one_side_generates_no_events(self):
        lc = make_counter()
        all_events = []
        for i in range(20):
            all_events += lc.update([(1, 300, 400)], now=i * 0.1)
        self.assertEqual(len(all_events), 0)
        self.assertEqual(lc.entries, 0)
        self.assertEqual(lc.exits, 0)

    def test_repeated_crossings_count_each_legitimate_crossing(self):
        lc = make_counter()
        t = 0.0
        for x in [400, 640, 900]:
            lc.update([(1, x, 400)], now=t)
            t += 0.1
        for x in [900, 640, 400]:
            lc.update([(1, x, 400)], now=t)
            t += 0.1
        for x in [400, 640, 900]:
            lc.update([(1, x, 400)], now=t)
            t += 0.1
        self.assertEqual(lc.entries, 2)
        self.assertEqual(lc.exits, 1)

    def test_multiple_independent_tracks_two_people_entering(self):
        """Spec section 11: two people crossing -> entries += 2, tracked
        independently (not just the most recent detection)."""
        lc = make_counter()
        t = 0.0
        a_xs = [400, 500, 640, 700, 900]
        b_xs = [380, 480, 620, 690, 880]
        for i in range(len(a_xs)):
            lc.update([(1, a_xs[i], 400), (2, b_xs[i], 420)], now=t)
            t += 0.1
        self.assertEqual(lc.entries, 2)
        self.assertEqual(lc.exits, 0)
        self.assertEqual(lc.tracks[1].crossing_count, 1)
        self.assertEqual(lc.tracks[2].crossing_count, 1)

    def test_multiple_people_one_enters_one_exits_same_time(self):
        lc = make_counter()
        t = 0.0
        a_xs = [400, 500, 640, 700, 900]
        b_xs = [900, 800, 640, 500, 400]
        for i in range(len(a_xs)):
            lc.update([(1, a_xs[i], 400), (2, b_xs[i], 420)], now=t)
            t += 0.1
        self.assertEqual(lc.entries, 1)
        self.assertEqual(lc.exits, 1)

    def test_track_disappearing_then_new_id_does_not_retroactively_fire(self):
        lc = make_counter()
        lc.update([(1, 400, 400)], now=0.0)
        lc.update([(1, 500, 400)], now=0.1)
        lc.update([(2, 900, 400)], now=0.2)  # fresh ID appears already on right
        self.assertEqual(lc.entries, 0)
        self.assertEqual(lc.exits, 0)

    def test_stale_tracks_are_expired(self):
        lc = make_counter()
        lc.update([(1, 400, 400)], now=0.0)
        self.assertIn(1, lc.tracks)
        lc.update([], now=5.0)  # > track_expiry_seconds with no detections
        self.assertNotIn(1, lc.tracks)

    def test_entry_direction_can_be_reversed(self):
        lc = make_counter(entry_direction="right_to_left")
        t = 0.0
        for x in [900, 700, 640, 500, 400]:
            lc.update([(1, x, 400)], now=t)
            t += 0.1
        self.assertEqual(lc.entries, 1)
        self.assertEqual(lc.exits, 0)

    def test_reset_clears_counts_and_tracks(self):
        lc = make_counter()
        lc.update([(1, 400, 400)], now=0.0)
        lc.update([(1, 900, 400)], now=0.1)
        self.assertEqual(lc.entries, 1)
        lc.reset_counts()
        self.assertEqual(lc.entries, 0)
        self.assertEqual(lc.exits, 0)
        self.assertEqual(len(lc.tracks), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
Unit tests for OccupancyManager. Run: python3 tests/test_occupancy.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.occupancy.manager import OccupancyManager  # noqa: E402


class TestOccupancyManager(unittest.TestCase):

    def test_formula_initial_plus_entries_minus_exits(self):
        om = OccupancyManager("event_entrance", initial_occupancy=5)
        om.record_entry()
        om.record_entry()
        om.record_exit()
        self.assertEqual(om.live_occupancy, 5 + 2 - 1)

    def test_starts_at_zero_by_default(self):
        om = OccupancyManager("event_entrance")
        self.assertEqual(om.live_occupancy, 0)

    def test_never_goes_below_zero(self):
        om = OccupancyManager("event_entrance", initial_occupancy=0)
        om.record_exit()
        om.record_exit()
        om.record_exit()
        self.assertEqual(om.live_occupancy, 0)

    def test_negative_initial_occupancy_clamped_to_zero(self):
        om = OccupancyManager("event_entrance", initial_occupancy=-3)
        self.assertEqual(om.initial_occupancy, 0)

    def test_entries_and_exits_move_occupancy_up_and_down(self):
        om = OccupancyManager("event_entrance")
        for _ in range(3):
            om.record_entry()
        self.assertEqual(om.live_occupancy, 3)
        om.record_exit()
        self.assertEqual(om.live_occupancy, 2)

    def test_reset_restores_initial_state(self):
        om = OccupancyManager("event_entrance", initial_occupancy=2)
        om.record_entry()
        om.record_entry()
        self.assertEqual(om.live_occupancy, 4)
        om.reset(initial_occupancy=0)
        self.assertEqual(om.live_occupancy, 0)
        self.assertEqual(om.entries, 0)
        self.assertEqual(om.exits, 0)

    def test_snapshot_reflects_current_state(self):
        om = OccupancyManager("dining_entrance", initial_occupancy=1)
        om.record_entry()
        snap = om.snapshot()
        self.assertEqual(snap.camera_id, "dining_entrance")
        self.assertEqual(snap.initial_occupancy, 1)
        self.assertEqual(snap.entries, 1)
        self.assertEqual(snap.exits, 0)
        self.assertEqual(snap.live_occupancy, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

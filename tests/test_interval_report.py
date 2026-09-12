"""
Unit tests for bucket_events_by_interval() — the pure logic behind
GET /api/reports/interval (30-minute-window occupancy reports).

Uses plain dicts for events (no DB/HTTP needed) so this runs instantly.

Run: python3 tests/test_interval_report.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.routes import bucket_events_by_interval, MAX_REPORT_BUCKETS  # noqa: E402

HOUR = 3600
MIN30 = 1800


def ev(ts, event_type):
    return {"timestamp": ts, "event_type": event_type}


class BucketEventsByIntervalTest(unittest.TestCase):
    def test_no_events_produces_empty_buckets_at_zero_occupancy(self):
        start = 0.0
        now = start + HOUR  # spans 2 30-min buckets
        buckets = bucket_events_by_interval([], start, now, interval_minutes=30, initial_occupancy=0)
        self.assertEqual(len(buckets), 2)
        for b in buckets:
            self.assertEqual(b["entries"], 0)
            self.assertEqual(b["exits"], 0)
            self.assertEqual(b["occupancy_at_end"], 0)

    def test_events_land_in_the_correct_bucket(self):
        start = 0.0
        now = start + HOUR
        events = [
            ev(start + 10, "ENTRY"),           # bucket 0
            ev(start + MIN30 - 1, "ENTRY"),    # bucket 0 (just before the boundary)
            ev(start + MIN30, "EXIT"),         # bucket 1 (exactly at the boundary -> next bucket)
            ev(start + MIN30 + 100, "ENTRY"),  # bucket 1
        ]
        buckets = bucket_events_by_interval(events, start, now, interval_minutes=30, initial_occupancy=0)

        self.assertEqual(buckets[0]["entries"], 2)
        self.assertEqual(buckets[0]["exits"], 0)
        self.assertEqual(buckets[0]["occupancy_at_end"], 2)

        self.assertEqual(buckets[1]["entries"], 1)
        self.assertEqual(buckets[1]["exits"], 1)
        # cumulative: 2 entries + 1 exit (bucket1) + 1 entry (bucket1) = 3 in, 1 out
        self.assertEqual(buckets[1]["occupancy_at_end"], 2)

    def test_occupancy_never_goes_negative(self):
        start = 0.0
        now = start + MIN30
        events = [ev(start + 5, "EXIT"), ev(start + 6, "EXIT")]  # exits with no prior entries
        buckets = bucket_events_by_interval(events, start, now, interval_minutes=30, initial_occupancy=0)
        self.assertEqual(buckets[0]["occupancy_at_end"], 0)

    def test_initial_occupancy_is_the_baseline(self):
        start = 0.0
        now = start + MIN30
        buckets = bucket_events_by_interval([], start, now, interval_minutes=30, initial_occupancy=5)
        self.assertEqual(buckets[0]["occupancy_at_end"], 5)

    def test_occupancy_carries_forward_across_buckets(self):
        start = 0.0
        now = start + HOUR
        events = [ev(start + 10, "ENTRY"), ev(start + 20, "ENTRY"), ev(start + 30, "ENTRY")]  # all in bucket 0
        buckets = bucket_events_by_interval(events, start, now, interval_minutes=30, initial_occupancy=0)
        self.assertEqual(buckets[0]["occupancy_at_end"], 3)
        # bucket 1 has no new events, but occupancy must carry forward, not reset
        self.assertEqual(buckets[1]["entries"], 0)
        self.assertEqual(buckets[1]["occupancy_at_end"], 3)

    def test_zero_or_negative_interval_does_not_hang(self):
        """Regression guard: interval_minutes<=0 must not create an infinite
        bucket-generation loop (a query-param footgun since this is a plain
        FastAPI int param with no validation upstream)."""
        start = 0.0
        now = start + HOUR
        buckets = bucket_events_by_interval([], start, now, interval_minutes=0, initial_occupancy=0)
        self.assertGreater(len(buckets), 0)  # clamped to >=1 minute, terminates
        buckets_neg = bucket_events_by_interval([], start, now, interval_minutes=-30, initial_occupancy=0)
        self.assertGreater(len(buckets_neg), 0)

    def test_very_small_interval_over_a_long_session_is_capped(self):
        start = 0.0
        now = start + 365 * 24 * HOUR  # a full year, 1-minute buckets would be ~525,600
        buckets = bucket_events_by_interval([], start, now, interval_minutes=1, initial_occupancy=0)
        self.assertLessEqual(len(buckets), MAX_REPORT_BUCKETS)

    def test_no_time_elapsed_yet_returns_one_bucket(self):
        start = 100.0
        buckets = bucket_events_by_interval([], start, start, interval_minutes=30, initial_occupancy=0)
        self.assertEqual(len(buckets), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

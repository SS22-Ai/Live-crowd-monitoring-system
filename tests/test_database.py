"""
Tests for the SQLite database layer — these run against a REAL temporary
SQLite file (not mocked), so they genuinely exercise sqlite3.
Run: python3 tests/test_database.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.database import Database  # noqa: E402


class TestDatabase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)  # let Database create it fresh
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_start_session_returns_incrementing_id(self):
        sid1 = self.db.start_session()
        sid2 = self.db.start_session()
        self.assertIsInstance(sid1, int)
        self.assertGreater(sid2, sid1)

    def test_record_and_fetch_events(self):
        sid = self.db.start_session()
        self.db.record_event(sid, "event_entrance", track_id=17, event_type="ENTRY")
        self.db.record_event(sid, "event_entrance", track_id=17, event_type="EXIT")
        events = self.db.get_events(session_id=sid)
        self.assertEqual(len(events), 2)
        types = sorted(e.event_type for e in events)
        self.assertEqual(types, ["ENTRY", "EXIT"])

    def test_invalid_event_type_rejected(self):
        sid = self.db.start_session()
        with self.assertRaises(ValueError):
            self.db.record_event(sid, "event_entrance", track_id=1, event_type="MAYBE")

    def test_count_events_by_camera_and_type(self):
        sid = self.db.start_session()
        for tid in (1, 2, 3):
            self.db.record_event(sid, "event_entrance", tid, "ENTRY")
        self.db.record_event(sid, "event_entrance", 1, "EXIT")
        self.db.record_event(sid, "dining_entrance", 4, "ENTRY")

        self.assertEqual(self.db.count_events(sid, "event_entrance", "ENTRY"), 3)
        self.assertEqual(self.db.count_events(sid, "event_entrance", "EXIT"), 1)
        self.assertEqual(self.db.count_events(sid, "dining_entrance", "ENTRY"), 1)

    def test_events_filtered_by_camera(self):
        sid = self.db.start_session()
        self.db.record_event(sid, "event_entrance", 1, "ENTRY")
        self.db.record_event(sid, "dining_entrance", 2, "ENTRY")
        only_dining = self.db.get_events(session_id=sid, camera_id="dining_entrance")
        self.assertEqual(len(only_dining), 1)
        self.assertEqual(only_dining[0].camera_id, "dining_entrance")

    def test_end_session_sets_ended_at(self):
        sid = self.db.start_session()
        session = self.db.get_session(sid)
        self.assertIsNone(session.ended_at)
        self.db.end_session(sid)
        session = self.db.get_session(sid)
        self.assertIsNotNone(session.ended_at)

    def test_latest_session_returns_most_recent(self):
        self.db.start_session()
        sid2 = self.db.start_session()
        latest = self.db.latest_session()
        self.assertEqual(latest.id, sid2)

    def test_no_biometric_fields_in_schema(self):
        """Sanity check per spec 14/29: schema must not contain face/biometric columns."""
        with self.db._cursor() as cur:
            cur.execute("PRAGMA table_info(crossing_events)")
            columns = {row["name"].lower() for row in cur.fetchall()}
        forbidden = {"face", "face_embedding", "biometric", "photo", "image"}
        self.assertEqual(columns & forbidden, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)

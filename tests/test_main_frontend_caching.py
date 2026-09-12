"""
Unit test for app/main.py's is_uncached_frontend_path() — the predicate
behind the no-store middleware that keeps the dashboard's HTML/JS/CSS from
being browser-cached (no build step here, so a stale cache silently serves
an old app.js/style.css after an edit until a hard refresh).

Deliberately does NOT boot the full app (create_app() loads a YOLO model
and starts camera threads) — just the pure path predicate, so this runs
instantly with no camera/model dependency.

Run: python3 tests/test_main_frontend_caching.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import is_uncached_frontend_path  # noqa: E402


class IsUncachedFrontendPathTest(unittest.TestCase):
    def test_dashboard_root_is_uncached(self):
        self.assertTrue(is_uncached_frontend_path("/"))

    def test_static_assets_are_uncached(self):
        self.assertTrue(is_uncached_frontend_path("/static/app.js"))
        self.assertTrue(is_uncached_frontend_path("/static/style.css"))
        self.assertTrue(is_uncached_frontend_path("/static/index.html"))

    def test_api_routes_are_not_touched(self):
        self.assertFalse(is_uncached_frontend_path("/api/status"))
        self.assertFalse(is_uncached_frontend_path("/api/events"))

    def test_video_stream_is_not_touched(self):
        self.assertFalse(is_uncached_frontend_path("/video/event_entrance"))

    def test_path_merely_containing_static_is_not_matched(self):
        # must be a "/static/" prefix, not just containing the substring
        self.assertFalse(is_uncached_frontend_path("/api/static_report"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

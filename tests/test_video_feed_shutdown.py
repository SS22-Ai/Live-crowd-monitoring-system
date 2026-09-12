"""
Regression tests for the MJPEG stream shutdown bug (P0):

`_mjpeg_generator()` in app/api/routes.py used to be `while True: ... ;
time.sleep(0.05)` with no way to ever stop on its own. Since /video/{id} is a
long-lived request, that meant its connection stayed "in flight" forever —
and uvicorn's graceful shutdown waits for all in-flight requests to finish
*before* it calls the app's shutdown hook (which ends the DB session and
releases the cameras). Net effect: SIGTERM hung forever needing a SIGKILL,
and the session's ended_at was never written.

These tests exercise the generator directly (no FastAPI TestClient / uvicorn
needed — this repo doesn't have httpx installed) with a fake pipeline and a
fake Request exposing an async is_disconnected(), so they run instantly and
need no camera, model, or running server.

Run: python3 tests/test_video_feed_shutdown.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.routes import _mjpeg_generator  # noqa: E402


class FakePipeline:
    def __init__(self, frames):
        self._frames = list(frames)

    def latest_jpeg(self):
        return self._frames.pop(0) if self._frames else None


class FakeRequest:
    """disconnect_after=N: is_disconnected() returns False for the first N
    calls, then True forever after — simulating the client leaving after N
    poll cycles. disconnect_after=0 simulates a client that's already gone
    (or a shutdown flag flipped) before the first check."""

    def __init__(self, disconnect_after):
        self.disconnect_after = disconnect_after
        self.calls = 0

    async def is_disconnected(self):
        self.calls += 1
        return self.calls > self.disconnect_after


class MjpegGeneratorShutdownTest(unittest.IsolatedAsyncioTestCase):
    async def test_stops_immediately_if_already_disconnected(self):
        """The core regression: the generator must terminate on its own
        instead of looping forever once the client is gone."""
        gen = _mjpeg_generator(FakePipeline([b"frame1"]), FakeRequest(disconnect_after=0))
        chunks = [chunk async for chunk in gen]
        self.assertEqual(chunks, [])

    async def test_stops_after_client_disconnects_mid_stream(self):
        gen = _mjpeg_generator(FakePipeline([b"f1", b"f2", b"f3"]), FakeRequest(disconnect_after=2))
        chunks = [chunk async for chunk in gen]
        self.assertEqual(len(chunks), 2)

    async def test_yields_no_chunk_when_no_frame_available_yet(self):
        """Camera not publishing frames yet (e.g. OFFLINE) must not raise or
        yield garbage — it should just keep waiting until disconnect."""
        gen = _mjpeg_generator(FakePipeline([None, None, b"f1"]), FakeRequest(disconnect_after=3))
        chunks = [chunk async for chunk in gen]
        self.assertEqual(len(chunks), 1)

    async def test_yielded_chunk_is_a_well_formed_multipart_frame(self):
        gen = _mjpeg_generator(FakePipeline([b"JPEGDATA"]), FakeRequest(disconnect_after=1))
        chunks = [chunk async for chunk in gen]
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertTrue(chunk.startswith(b"--frame\r\n"))
        self.assertIn(b"Content-Type: image/jpeg\r\n", chunk)
        self.assertIn(b"Content-Length: 8\r\n\r\n", chunk)
        self.assertTrue(chunk.endswith(b"JPEGDATA\r\n"))

    async def test_never_runs_unbounded_iterations(self):
        """Defense against a future regression reintroducing an unconditional
        while True: even with plenty of frames queued up, the generator must
        stop the moment the client disconnects rather than draining forever."""
        many_frames = [b"f"] * 10_000
        request = FakeRequest(disconnect_after=5)
        gen = _mjpeg_generator(FakePipeline(many_frames), request)
        chunks = [chunk async for chunk in gen]
        self.assertEqual(len(chunks), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)

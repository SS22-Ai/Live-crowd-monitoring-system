# DECISIONS — Event Crowd Monitor

Chronological record of technical decisions and why. Newest at the bottom.

---

### D1 — Counting via "confirmed side flip", not raw line intersection
**Context:** a person standing/jittering near the line must not generate a
stream of events (spec §26).
**Decision:** bucket each track LEFT / BUFFER / RIGHT; keep a per-track
*confirmed* side that only ever holds LEFT or RIGHT; fire exactly one event
when that confirmed side flips. BUFFER transitions are inert.
**Consequence:** robust to jitter and brief detection dropouts; a genuine
re-crossing is required to count again. Covered by `test_line_counter.py` +
`test_integration_pipeline.py`.

### D2 — One `PersonDetector` (YOLO model) instance per camera
**Context:** `model.track(persist=True)` stores ByteTrack tracker state
*inside the model object*.
**Decision:** `CameraManager` calls a `detector_factory()` per enabled camera;
never share one model across threads.
**Consequence:** track IDs can't cross-contaminate between cameras; ~2× model
memory when Camera 2 is enabled (acceptable — YOLO11n is ~5 MB). Regression:
`test_camera_manager.py`.

### D3 — Camera status is ONLINE only after a real frame read
**Context:** some backends report `isOpened()==True` but never deliver frames.
**Decision:** `CameraStream` stays RECONNECTING/OFFLINE until `read()` actually
returns a frame; a caught exception degrades state, never propagates.
**Consequence:** the dashboard never shows a dead camera as ONLINE. Covered by
`test_camera_stream.py` (this caught a real bug during the original build).

### D4 — Polling, not WebSockets, for live dashboard updates
**Decision:** `/api/status` every 1 s, `/api/events` every 2 s from `app.js`.
**Rationale:** simpler, resilient to a camera dropping, no connection lifecycle.
Spec explicitly allows the polling fallback. Easy to upgrade later.

### D5 — SQLite stores only sessions + crossing events, no biometrics
**Decision:** schema has `sessions` and `crossing_events` only; `event_type`
has a CHECK constraint; no columns for faces/embeddings/identity.
**Consequence:** privacy guarantee is structural, not just policy. Asserted by
`test_database.py::test_no_biometric_fields_in_schema`.

---

## 2026-09-07 — real-hardware bring-up decisions

### D6 — `.venv` created with `--system-site-packages`
**Context:** the only Python on this Mac is system `/usr/bin/python3` 3.9.6
(README assumed 3.10+). The user site-packages *already* has torch 2.8.0
(MPS working), torchvision, ultralytics 8.4.87, opencv 5.0.0, numpy 2.0.2,
PyYAML. A clean venv would re-download ~200 MB of torch for no benefit.
**Decision:** `python3 -m venv .venv --system-site-packages`, then pip-install
only the 4 genuinely missing packages: `fastapi`, `uvicorn[standard]`,
`python-multipart`, `lapx`.
**Trade-off:** not a hermetic venv. If full isolation is wanted later, delete
`.venv` and `pip install -r requirements.txt` into a plain one (gets the same
torch 2.8). Recorded so this isn't mistaken for a mistake.
**Python 3.9 note:** all app modules use `from __future__ import annotations`,
so PEP 604 (`X | Y`) annotations are strings and never evaluated — 3.9 is fine.

### D7 — Main-thread camera permission prime (`app/main.py`)
**Context:** OpenCV's AVFoundation backend can only call
`requestAccessForMediaType:` from the process **main thread** (needs the main
run loop). Camera pipelines run in worker threads, so the first
`cv2.VideoCapture()` there failed with *"can not spin main run loop from other
thread"* and the macOS permission prompt never appeared.
**Decision:** `create_app()` (runs on the main thread) calls
`prime_camera_permissions(cfg.cameras, logger)` before `CameraManager` starts
threads — it briefly opens each enabled **int** (webcam) source so macOS
resolves the TCC state / shows the prompt first. Best-effort, never fatal;
RTSP/URL sources are skipped.
**Fallback documented:** `OPENCV_AVFOUNDATION_SKIP_AUTH=1` if a machine still
hits the run-loop error after permission is granted.

### D8 — Rewrote `test_falls_back_to_cpu_when_torch_missing_entirely`
**Context:** it assumed torch was absent from the host (true in the build
sandbox). On a real Mac with torch installed it wrongly FAILED (`select_device()`
returned `mps`).
**Decision:** force the failure path deterministically with
`mock.patch.dict(sys.modules, {"torch": None})` so `import torch` raises
`ImportError` regardless of what's installed.

### D9 — `test_detector.py` fakes must save/restore `sys.modules`, not pop
**Context:** `uninstall_fakes()` did `sys.modules.pop("torch"/"ultralytics")`.
Harmless in the sandbox (never installed), but on a real machine it evicts the
*real* cached `torch`; a later re-import (e.g. from `test_real_yolo_smoke.py`)
crashes with *"Only a single TORCH_LIBRARY can be used to register the namespace
triton"*. torch is not safe to re-import in one process.
**Decision:** `install_fake_*` stashes the pre-existing module (or a MISSING
sentinel); `uninstall_fakes()` restores it verbatim. Suite is now order-independent.

### D10 — Added integration + real-stack smoke tests to `tests/`
**Decision:**
- `tests/test_integration_pipeline.py` (5): real `LineCounter` +
  `OccupancyManager` + real temp-file `Database` driven through the four
  README §6 walk-through scenarios with detector-shaped input tuples.
- `tests/test_real_yolo_smoke.py` (4): the genuine YOLO11n + ByteTrack + MPS
  path on Ultralytics' bundled `bus.jpg`. `@skipUnless` real torch/ultralytics/
  cv2 import **and** `models/yolo11n.pt` already on disk — so it never triggers
  a network download and auto-skips in a bare CI/sandbox.
**Rationale:** the original suite's detector tests deliberately use *fake*
torch; nothing permanent exercised the real inference or the counting→DB wiring.

---

## 2026-09-08 — open questions surfaced during deployment tracking

### D11 — Occupancy is derived-only, not persisted as its own table (RESOLVED 2026-09-12 — option (b) chosen)
**Original problem:** `OccupancyManager` lives in memory only. The DB stores
`sessions` + `crossing_events`, no `occupancy` table. On restart, occupancy
used to recompute from `initial_occupancy` (0) unconditionally, silently
losing the live count on a crash mid-event.
**Options considered:** (a) leave as-is; (b) on startup, replay
`crossing_events` for the active session to rebuild occupancy; (c) a
separate `occupancy_snapshots` table written every N seconds.
**Decision: (b), then broadened same day.** First cut (`d464df2`):
`app/main.py`'s `resolve_startup_session()` only resumed when the most
recent session's `ended_at` was `NULL` (a crash) — a clean stop still
started fresh at 0, on the assumption that an intentional stop meant an
intentional new day/event.
**Broadened per explicit request (same day):** that assumption was
wrong for how this is actually used — data must survive *any* restart,
clean or not, and only reset via an explicit action. `resolve_startup_session()`
now ignores `ended_at` entirely and always resumes the latest session if
one exists at all; `ended_at` is kept purely as "when did the process
last stop" telemetry, no longer load-bearing for the resume decision.
The only things that actually zero counts now are `POST /api/reset` and
`POST /api/session/start`, both routed through the new
`begin_fresh_session()` (`app/api/routes.py`) — it closes the current
session and opens a new one, so a *subsequent* restart resumes the new
(zeroed) session instead of replaying the pre-reset numbers back. Without
this, a plain in-memory reset would have been silently undone by the next
restart.
**No new table added** — (c) was rejected as unnecessary complexity;
replaying `crossing_events` from the current session covers every
restart scenario that actually matters.
**Verified live (both revisions):** crash (`SIGKILL`) resumes correctly;
a clean `SIGTERM` stop now *also* resumes correctly (previously it didn't
— confirmed by reproducing the old behavior first, then the fix); and
`POST /api/reset` followed by a restart correctly stays at zero rather
than replaying the old session. 9 automated tests in
`tests/test_session_resume.py`. Full suite 91/91.

### D12 — SIGTERM does not run the FastAPI shutdown hook (FIXED 2026-09-12, `cc2bf39`)
**Observed 2026-09-08:** killing `run.py` with SIGTERM does not invoke
`@app.on_event("shutdown")`, so `db.end_session()` and `manager.stop_all()`
don't run; sessions are left with `ended_at = NULL`; the process needed
`SIGKILL`.
**Root cause (found 2026-09-12, not what was assumed on 2026-09-08):** it
was never about `@app.on_event` being deprecated — the real cause was
`/video/{camera_id}`'s MJPEG generator (`while True: ... time.sleep(0.05)`,
no exit condition). uvicorn's graceful shutdown waits for all in-flight
requests to finish *before* it calls the ASGI shutdown event at all, and
that streaming request never finished on its own, so the shutdown hook —
`@app.on_event` or a `lifespan=` manager, either would have had the same
problem — never got invoked.
**Actual fix (simpler than the lifespan-migration originally planned
above):** `app/api/routes.py`'s `_mjpeg_generator` now checks
`await request.is_disconnected()` each cycle, so it exits once a client
actually leaves; `run.py` sets `timeout_graceful_shutdown=5` on
`uvicorn.run()` as a bound for the remaining case (client still connected
at shutdown time). `@app.on_event("shutdown")` was kept as-is — no
lifespan migration was needed once the actual blocker was fixed.
**Verified live twice:** with an open `/video/` stream, and without one —
both exit in ~5-6s on a plain `kill`/Ctrl+C, no `SIGKILL`, `ended_at`
written. 5 new tests in `tests/test_video_feed_shutdown.py`.

### D13 — Stuck local-USB-camera recovery: process-restart watchdog, NOT auto index-hopping; Camera-TCC-under-launchd abandoned (2026-09-13)
**Observed live 2026-09-13:** unplugging and replugging the external USB
webcam left `CameraStream` permanently unable to reopen that camera's
index in-process — dozens of reconnect attempts over more than a minute
all failed, while a brand-new `python test_camera.py` process opened the
same index instantly. Confirmed as a real macOS/OpenCV (AVFoundation)
limitation, not a bug in the reconnect loop itself: the loop was already
correctly creating a fresh `cv2.VideoCapture` object on every attempt.
**Option rejected: auto-hop to a different camera index on repeated
failure.** Considered and explicitly rejected — camera index assignment
on macOS can shift on any hot-plug event (not just for the replugged
device), so silently attaching a *different* physical camera to a zone's
fixed identity (`event_entrance` vs `dining_entrance`) risks the worst
failure mode for a counting system: confidently-displayed, silently
*wrong* counts, attributed to the wrong entrance. Staying visibly
OFFLINE is safer than guessing.
**Decision: a stuck-camera watchdog that restarts the whole process.**
`CameraPipeline.seconds_stuck_offline()` / `CameraManager.max_seconds_
stuck_offline()` (`app/camera/manager.py`) track how long a camera that
was PREVIOUSLY online has been continuously non-ONLINE; deliberately
gated on having been online at least once, so a camera that's simply
never reachable (bad config, dead network) never triggers this — that
would restart the whole process forever and repeatedly disrupt every
OTHER camera's pipeline too, for a camera a restart can't help anyway.
`app/main.py`'s `stuck_camera_watchdog()` polls this and, past
`stuck_camera_restart_seconds` (config, default 60s), sends the process
its own SIGTERM — reusing the exact D12-verified graceful-shutdown path
(session `ended_at` written, cameras released, 5s bounded timeout) rather
than a hard `os._exit`. This only self-heals under the launchd supervisor
(`deploy/`), which brings the process back with a fresh camera session
within ~10s.
**Camera permission (TCC) under launchd for local USB webcams: tried and
abandoned, same day.** launchd spawning python directly gets *no* Camera
prompt and *no* entry in System Settings, ever (silent, permanent denial
— same category of issue as the Downloads-folder TCC problem, but with
no known workaround at this tier). Tried wrapping the launch in a minimal
ad-hoc-codesigned `.app` bundle (`deploy/CrowdMonitorLauncher.app`) so
TCC would have a real app to attribute access to, including fixing an
`exec`-vs-subprocess mistake along the way (an `exec`'d process discards
the bundle identity TCC needs; kept the wrapper alive as python's direct
parent instead, forwarding SIGTERM, so "responsible process" resolution
could reach it). Result: the bundle registered as a recognized background
item, but **never produced a Camera entry at all** — modern macOS appears
to require a real Apple Developer ID signature + notarization for this,
not just ad-hoc signing, which is out of scope. **Abandoned; do not
re-attempt without a paid Developer ID.** The bundle and codesign step
were removed; `deploy/com.eventcrowdmonitor.app.plist` launches python
directly again.
**Net effect:** the watchdog is real, general infrastructure that works
today for RTSP cameras under the supervisor (the actual event path — RTSP
never hits Camera TCC at all). Local USB webcam testing under the
supervisor specifically remains unsupported; use a manual
`CROWD_MONITOR_CONFIG=config.local.yaml .venv/bin/python run.py` from a
real Terminal for that instead (see `HANDOVER.md` §12).
**Verified live:** the watchdog's pure tracking logic (7 tests,
`tests/test_stuck_camera_watchdog.py`); separately confirmed
`stuck_camera_watchdog()` itself really fires `os.kill(self, SIGTERM)`
and really terminates the process, using a fake always-stuck manager
(no camera needed) -- exited with code 143 (SIGTERM) as expected. Full
suite 98/98. **NOT yet observed end-to-end with a real camera** going
online-then-stuck under the live supervisor (blocked right now by the
same TCC wall for local USB, and by the demo RTSP camera being
unreachable) -- the two halves (detection math, and the kill-triggers-
graceful-shutdown path already proven separately via D12 and this
session's earlier kill -9 tests) are each verified, just not yet chained
together against real hardware.

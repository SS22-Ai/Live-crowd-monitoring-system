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

### D11 — Occupancy is derived-only and not persisted (OPEN — needs your call)
**Current behaviour:** `OccupancyManager` lives in memory. The DB stores
`sessions` + `crossing_events` only — there is **no occupancy table**. On
restart, occupancy recomputes from `initial_occupancy` (0) for a *new* session;
it does **not** replay the previous session's events.
**Implication for the checklist:** DEPLOYMENT_STATUS Phase 6 "Occupancy records"
= `[ ]`, Phase 5 "Restart/recovery behavior" = `[~]`.
**Options:**
(a) leave as-is — occupancy is a per-session live counter, restart = fresh count (simplest; fine if the app runs for the whole event);
(b) on startup, replay `crossing_events` for the active session to rebuild occupancy (crash-recovery within a session);
(c) add an `occupancy_snapshots` table written every N seconds (history + fast recovery).
**Not decided.** Blocking "deployment-ready" until chosen.

### D12 — SIGTERM does not run the FastAPI shutdown hook (BUG — fix planned)
**Observed 2026-09-08:** killing `run.py` with SIGTERM does not invoke
`@app.on_event("shutdown")`, so `db.end_session()` and `manager.stop_all()`
don't run; sessions are left with `ended_at = NULL`.
**Impact:** cosmetic for data integrity (events are committed as they occur),
but camera threads aren't joined and sessions never close cleanly — bad for a
long-running deployment.
**Decision:** replace the deprecated `@app.on_event("startup"/"shutdown")` with
a `lifespan=` async context manager on the FastAPI app; move
`prime_camera_permissions` + `CameraManager` start into its enter phase and
`stop_all()` + `end_session()` into its exit phase; ensure uvicorn is run so it
propagates SIGTERM/SIGINT to lifespan shutdown. Tracked in TODO.

# TEST_STATUS — Event Crowd Monitor

Every row: **test name · date/time · result · what was tested · evidence · failure reason (if any)**.

Result values: `PASSED` · `FAILED` · `BLOCKED` · `MANUAL` (needs a person/hardware) · `IN PROGRESS`.
**A row is only `PASSED` if the command/test was executed here and its output observed.**

---

## A. Automated suite — `python -m unittest discover -s tests`

| Test | Date/time | Result | What was tested | Evidence | Failure reason |
|---|---|---|---|---|---|
| Full suite (venv, Python 3.9.6) | 2026-09-08 13:41 IST | **PASSED** | all 59 tests (unit + integration + real-YOLO smoke) | `Ran 59 tests in 2.088s` → `OK` | — |
| Full suite (`/usr/bin/python3` 3.9.6) | 2026-09-07 | **PASSED** | same, second interpreter | `Ran 59 tests` → `OK` | — |
| `test_line_counter.py` (12) | 2026-09-08 13:41 | **PASSED** | directional crossing: L→R/R→L, hover, reverse, multi-person, stale-track expiry, direction reversal | in suite `OK` | — |
| `test_occupancy.py` (7) | 2026-09-08 13:41 | **PASSED** | `live = max(0, initial+entries−exits)`; never-below-zero; reset; snapshot | in suite `OK` | — |
| `test_database.py` (8) | 2026-09-08 13:41 | **PASSED** | real temp SQLite: sessions, events, filter-by-camera, invalid event_type rejected, **no biometric columns** | in suite `OK` | — |
| `test_camera_stream.py` (7) | 2026-09-08 13:41 | **PASSED** | reconnect/status FSM vs fake capture backend: exception-on-open, failed-open→OFFLINE, read-failure→RECONNECTING, ONLINE only after real frame, one cam failing ≠ affects another | in suite `OK` | — |
| `test_camera_manager.py` (3) | 2026-09-08 13:41 | **PASSED** | each enabled camera gets its **own** detector instance; factory called once per enabled camera; disabled camera loads no model | in suite `OK` | — |
| `test_detector.py` (13) | 2026-09-08 13:41 | **PASSED** | adapter logic vs FAKE torch/ultralytics: box→`Detection` parse, no-tracks/no-results, id→int cast, person-class restriction, model-load error, MPS/CPU select, torch-missing→cpu | in suite `OK` | — (was FAILED 2026-09-07, fixed — see §D) |
| `test_integration_pipeline.py` (5) | 2026-09-08 13:41 | **PASSED** | real `LineCounter`+`OccupancyManager`+real temp SQLite through README §6 scenarios 1–4 + direction reversal; asserts counts, `live_occupancy`, DB rows | in suite `OK` | — |
| `test_real_yolo_smoke.py` (4) | 2026-09-08 13:41 | **PASSED** | **real** YOLO11n + ByteTrack + MPS on bundled `bus.jpg`: device∈{mps,cpu}, ≥1 person w/ int ids, ids stable across frames, `draw_frame` renders + JPEG-encodes | run alone: `Ran 4 tests in 1.387s OK`; in suite `OK` | — (auto-skips if torch/ultralytics/model absent) |

## B. Real-hardware / integration checks (run by command this session, not in the suite)

| Test | Date/time | Result | What was tested | Evidence | Failure reason |
|---|---|---|---|---|---|
| Real YOLO/ByteTrack/MPS inference | 2026-09-08 13:40 | **PASSED** | `PersonDetector` on Ultralytics `bus.jpg`/`zidane.jpg` | `select_device(): mps`; `bus.jpg: 4 persons; ids=[1,2,3,4]; id types=['int']; stable_2nd_pass=True`; `zidane.jpg: 2 persons; ids=[5,6]` | — |
| Camera hardware access | 2026-09-08 13:40 | **BLOCKED** | `cv2.VideoCapture(0)` open + read | `OpenCV: not authorized to capture video (status 0)`; `index 0: isOpened=False frame_read=False` | macOS TCC: Camera permission not granted to this process; not grantable non-interactively |
| App boot + startup logging | 2026-09-08 13:41 | **PASSED** | `run.py` → uvicorn; log file | log: `Application starting` … `Using device: MPS` … `Model loaded` … `Camera pipelines started` … `Uvicorn running on http://0.0.0.0:8000`; `logs/app.log` = 1475 B | — |
| `GET /api/status` | 2026-09-08 13:41 | **PASSED** | app + camera stats | HTTP 200, `{"app":"event_crowd_monitor","status":"running",...,"cameras":[...]}` | — |
| `GET /api/cameras` | 2026-09-08 13:41 | **PASSED** | per-camera stats | HTTP 200, `event_entrance status=OFFLINE`, `dining_entrance` present | — |
| `GET /api/occupancy` | 2026-09-08 13:41 | **PASSED** | per-camera occupancy snapshot | HTTP 200, `{"event_entrance":{...,"live_occupancy":0},"dining_entrance":{...}}` | — |
| `GET /api/events` | 2026-09-08 13:41 | **PASSED** | event history | HTTP 200, `{"events":[]}` (fresh DB) | — |
| `POST /api/reset` | 2026-09-08 13:41 | **PASSED** | counter reset | `{"ok":true,"message":"Counters reset for all cameras"}` | — |
| `POST /api/session/start` | 2026-09-08 13:41 | **PASSED** | new session + reset | `{"ok":true,"session_id":2}`; earlier run showed increment 1→2→3 | — |
| `GET /video/event_entrance` | 2026-09-08 13:41 | **PASSED** | MJPEG endpoint | HTTP 200, `content-type: multipart/x-mixed-replace; boundary=frame` | — (no frames — camera OFFLINE) |
| `GET /video/<bogus>` | 2026-09-08 13:41 | **PASSED** | unknown-camera error handling | HTTP 404, `{"detail":"Unknown camera_id 'nope'"}` | — |
| `GET /` dashboard HTML | 2026-09-08 13:41 | **PASSED** | dashboard served | HTTP 200, `<title>Event Crowd Monitor</title>` | — |
| Dashboard render + polling | 2026-09-07 | **PASSED** | in-app browser: panels injected from `/api/status`, OFFLINE pill + "no signal" placeholder, stat tiles = 0 | screenshot captured; `read_console_messages(onlyErrors)` → none | — |
| Dashboard Reset button | 2026-09-07 | **PASSED** | click "Reset counts" → POST → toast | screenshot shows "Counters reset" toast; no JS console errors | — |
| DB persistence across restart | 2026-09-08 13:41 | **PASSED** | run → sessions 1,2 → SIGTERM → restart → check | after restart: `sessions: [(1,'open'),(2,'open'),(3,'open')]` — 1 & 2 survived, 3 appended; `/api/status` HTTP 200 | — |
| Graceful shutdown (`end_session` on SIGTERM) | 2026-09-08 13:41 | **FAILED** | shutdown hook runs on SIGTERM | no `Application stopping` log line; sessions remain `ended_at=NULL` | uvicorn/FastAPI `@app.on_event("shutdown")` not invoked on this SIGTERM path; migrate to lifespan handler |
| `draw_frame` over real detections | 2026-09-07 | **PASSED** | annotate a real YOLO result, encode JPEG | `annotated_bus.jpg.png` rendered (line + buffer + boxes + IDs + stats); also asserted in `test_real_yolo_smoke.py` | — |
| Graceful degradation (spec §13) | 2026-09-08 13:41 | **PASSED** | camera unavailable → app keeps serving | server log: 0 tracebacks, `status=RECONNECTING`; `/api/cameras` → `OFFLINE`; `/api/status` → 200 throughout | — |
| Config externalization | 2026-09-08 13:40 | **PASSED** | no hardcoded host/port/paths/URLs in app code | `grep -rnE 'localhost|127\.0\.0\.1|:8000|/Users/|rtsp://' app/ run.py` → only an RTSP example in a docstring | — |
| `py_compile` all sources | 2026-09-08 | **PASSED** | syntax of `app/**`, `tests/*`, `run.py`, `test_camera.py` | `py_compile: OK` | — |

## C. MANUAL — require you + a real webcam (not performed)

| Test | Result | What it will test | What you do |
|---|---|---|---|
| `test_camera.py` live preview | **MANUAL** | webcam opens, preview shows real feed | run from your Terminal, approve TCC prompt, press `q` |
| Live annotated feed on dashboard | **MANUAL** | Camera 1 ONLINE, boxes/IDs/line drawn on live video | `run.py`, open `:8000` |
| §6.1 walk L→R | **MANUAL** | `ENTRY 1 / EXIT 0 / LIVE 1` on a real crossing | walk across mid-frame |
| §6.2 walk back R→L | **MANUAL** | `ENTRY 1 / EXIT 1 / LIVE 0` | walk back |
| §6.3 hover at line | **MANUAL** | no count change on jitter | stand at line, sway |
| §6.4 two people both ways | **MANUAL** | counts ±2, independent IDs drawn | with a second person |
| Live counts tick on dashboard | **MANUAL** | dashboard entry/exit/occupancy update from real events; activity feed populates | watch `:8000` during the walk-through |
| Real physical camera unplug/replug | **MANUAL** | status → RECONNECTING → ONLINE, no crash | unplug USB cam mid-run |
| 4+ hour stability | **MANUAL** | no leak/drift/crash over hours | leave `run.py` running |

## D. Failure history

| Date | Test | Failure | Resolution |
|---|---|---|---|
| 2026-09-07 | `test_falls_back_to_cpu_when_torch_missing_entirely` | Returned `mps` not `cpu` — the test assumed torch absent; this Mac has torch 2.8.0 | Rewrote to `mock.patch.dict(sys.modules, {"torch": None})` so `import torch` raises regardless of host. Re-run: PASSED both interpreters. |
| 2026-09-07 | whole suite when `test_real_yolo_smoke` present | `setUpClass` ERROR: `RuntimeError: Only a single TORCH_LIBRARY can be used to register the namespace triton` | `test_detector.py`'s `uninstall_fakes()` was `pop`-ing the real `torch`. Changed to save/restore the original module objects. Re-run: 59/59 PASSED. |
| 2026-09-08 | Graceful shutdown | `end_session()` not called on SIGTERM | OPEN — tracked in TODO + DECISIONS D12 (lifespan handler). Does not affect data integrity (events are committed as they occur; sessions just lack `ended_at`). |

---

## Update rule
Add a row here **every time a test is run** (or re-run), with the timestamp and
the actual output. Never edit a `PASSED` in without evidence in the Evidence column.

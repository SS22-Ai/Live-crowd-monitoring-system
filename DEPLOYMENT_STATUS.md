# DEPLOYMENT STATUS — Event Crowd Monitor

_Last updated: 2026-09-08 · Host: MacBook Air M2, macOS 15.7.3, Python 3.9.6_

Status key: `[ ]` NOT STARTED · `[~]` IN PROGRESS (implemented, **not** verified) ·
`[✓]` VERIFIED / PASSED (actually executed & observed this environment) ·
`[✗]` FAILED · `[!]` BLOCKED · `[M]` MANUAL TEST REQUIRED (needs a person / hardware I don't have)

**Rule applied:** `[✓]` means a command or automated test was run and its result
observed. Code that merely runs, or logic covered only by a plan, is `[~]`.
"Implemented" ≠ "verified".

---

## ⛔ BLOCKERS

1. **macOS Camera (TCC) permission is not grantable to this process.**
   Every camera call is a child of Claude.app (`com.anthropic.claudefordesktop`);
   `cv2.VideoCapture(0)` returns `OpenCV: not authorized to capture video (status 0)`.
   Re-checked 2026-09-08 — still blocked. This blocks all live-webcam items
   (Phase 2 Camera 1, Phase 4/5/8 live, Phase 12 Camera 1).
   **Fix is yours:** run `.venv/bin/python test_camera.py` from your own
   Terminal/iTerm and approve the prompt (or System Settings → Privacy &
   Security → Camera → enable your terminal app).
2. **No second physical camera** → all "Camera 2 … tested" items and Phase 9
   (two-camera integration) can't be runtime-verified here.
3. **No RTSP stream / real CCTV** → all of Phase 10 is NOT STARTED.
4. **No deployment target exercised** (no Mac mini, no auto-start service, no
   long-running test) → Phase 11 largely NOT STARTED.

---

## ▶ NEXT 5 ACTIONS

1. **(You)** From a real Terminal: `cd ~/event_crowd_monitor && .venv/bin/python test_camera.py` → approve the macOS Camera prompt, confirm the preview shows your webcam, tell me the AVAILABLE indexes.
2. **(You + me)** `.venv/bin/python run.py`, open http://localhost:8000, confirm `event_entrance` goes ONLINE with the annotated live feed (boxes, IDs, line). I'll watch `logs/app.log`.
3. **(You + me)** Physical walk-through on Camera 1 (README §6): L→R = ENTRY, R→L = EXIT, hover = no count, two people = independent. I verify counts vs `logs/app.log` + `/api/events` + dashboard.
4. **(me)** Decide + implement occupancy-on-restart behaviour and whether to add an occupancy table / combined dashboard total (currently derived-only, per-camera-only) — see DECISIONS D11/D12, TODO.
5. **(me)** Add a `/health` endpoint and a lifespan shutdown handler (SIGTERM currently skips `end_session`), then write `DEPLOYMENT.md` runbook + a launchd plist for auto-start.

---

## 🙋 WHAT I NEED FROM YOU

| Need | Why | Command |
|---|---|---|
| Grant macOS Camera permission to your terminal app, then run `test_camera.py` there | Unblocks every live-camera test; I cannot grant TCC or see a GUI prompt | `.venv/bin/python test_camera.py` |
| Physically walk across the webcam view (L→R, R→L, hover at line, with a second person) | Phase 4/5/12 live counting accuracy — needs a real body | app running, watch dashboard + `logs/app.log` |
| A second webcam (USB) **or** an RTSP URL | Phase 2 Camera 2, Phase 9 two-camera, Phase 10 CCTV | set `dining_entrance.enabled: true` + `source:` in `config.yaml` |
| Target machine (Mac mini) + how it should auto-start | Phase 11 deployment | — |
| Run a 4+ hour session once the camera works | Phase 11/12 stability | `.venv/bin/python run.py` and leave it |

---

## CURRENT DEPLOYMENT READINESS

**Verified items: 58 / 108 checkboxes ≈ 54%** (counting only `[✓]`).

But readiness for an actual event is gated by Phases 9–12, which are only
**~20% verified (8 / 41)** — and most of that 8 is logic-level / still-image /
automated, **not** live. **This project is NOT deployment-ready.** What's proven
is the core logic + single-node infrastructure; what's unproven is every form of
*live camera operation*, multi-camera, CCTV, and unattended running.

| Phase | Verified | Notes |
|---|---|---|
| 1 Dev environment | 6/6 ✓ | fully verified |
| 2 Camera input | 2/7 | abstraction + reconnect FSM verified (automated); real webcam BLOCKED |
| 3 AI vision | 7/8 ✓ | real YOLO/ByteTrack/MPS verified on still images; live-video stability = MANUAL |
| 4 Line crossing | 8/10 ✓ | all counting logic verified (unit + integration); on-camera = MANUAL |
| 5 Occupancy | 4/8 | formula/clamp/reset verified; per-camera live + restart behaviour open |
| 6 Database | 8/9 ✓ | sessions/events/persistence/restart verified; no occupancy table (by design?) |
| 7 Backend/API | 6/7 ✓ | all endpoints hit & 200; no dedicated `/health` |
| 8 Dashboard | 9/12 | renders/polls/controls verified in browser; live video + combined total open |
| 9 Two-camera integration | 0/7 | architecture unit-tested only; no runtime dual-camera |
| 10 Real CCTV / RTSP | 0/9 | not started |
| 11 Deployment | 4/13 | config externalized + logging + local dashboard verified; no auto-start/backup/stability |
| 12 Final acceptance | 4/12 | detection/tracking/DB/dashboard verified (logic/automated); live counting + long run + Camera 1/2 open |
| **Total** | **58/108 ≈ 54%** | deployment-critical Phases 9–12: **8/41 ≈ 20%** |

---

## PHASE 1 — DEVELOPMENT ENVIRONMENT

- [✓] Python environment — `.venv` (3.9.6, `--system-site-packages`); `59/59` tests pass; app boots
- [✓] Dependencies installed — fastapi/uvicorn/multipart/lapx into venv; torch 2.8.0 + ultralytics 8.4.87 + opencv 5.0.0 inherited; all imports resolve; real YOLO runs
- [✓] Apple Silicon / MPS detection — `select_device()` → `mps`; model loads `on device mps`; verified by live inference 2026-09-08
- [✓] Configuration system — `app/config.py` + `config.yaml`; typed `CameraConfig`/`AppConfig`; validated by test suite + live boot; `CROWD_MONITOR_CONFIG` env override
- [✓] Logging — `setup_logging()` FileHandler + StreamHandler; `logs/app.log` created on boot (observed, 1475 B); startup lines present
- [✓] Project structure — matches README §1; `py_compile` clean across `app/`, `tests/`, `run.py`, `test_camera.py`

## PHASE 2 — CAMERA INPUT

- [!] MacBook webcam works — BLOCKED: `cv2.VideoCapture(0)` → `not authorized` (re-tested 2026-09-08). Needs your Terminal + TCC grant.
- [✓] Camera abstraction implemented — `app/camera/stream.py` `CameraStream`, injectable `capture_factory`; 7 unit tests pass (`test_camera_stream.py`)
- [!] Camera 1 works — BLOCKED on the same TCC permission; pipeline thread starts, stream stays OFFLINE
- [~] Camera 2 architecture works — per-camera detector/thread isolation **unit-verified** (`test_camera_manager.py` 3/3); no 2nd physical camera for runtime proof
- [✓] Camera disconnect/reconnect handling — reconnect/status FSM verified by 7 automated tests (simulated open/read failures) + observed live (`RECONNECTING` → reconnect loop → `OFFLINE`, server unaffected). Real physical unplug/replug = [M].
- [~] RTSP input support — implemented: any non-numeric `source` string → `cv2.VideoCapture(url)`, same reconnect path; **not run**
- [ ] RTSP stream tested — no stream available

## PHASE 3 — AI VISION

- [✓] YOLO person detection — real `PersonDetector` on Ultralytics `bus.jpg` → 4 persons; `zidane.jpg` → 2 (2026-09-08)
- [✓] Person-only filtering — `classes=[PERSON_CLASS_ID]` in `model.track`; `test_track_call_restricts_to_person_class_only`; real runs returned only persons
- [✓] ByteTrack multi-person tracking — real `tracker="bytetrack.yaml"`, `persist=True`; stable IDs across passes (2026-09-08)
- [✓] Unique temporary track IDs — real IDs `[1,2,3,4]` distinct `int`; `test_track_ids_are_cast_to_int`
- [✓] Multiple people tracked simultaneously — 4 concurrent tracks (bus.jpg), 2 (zidane.jpg), each own bbox+id
- [M] Tracking stability tested — only stable across repeated passes of the **same still frame**. Real moving-person / occlusion stability needs live video (your webcam).
- [✓] CPU fallback — `test_falls_back_to_cpu_when_mps_unavailable` + `test_falls_back_to_cpu_when_torch_missing_entirely` (both pass in the suite)
- [✓] Apple Silicon MPS tested — real inference executed on `device=mps` (2026-09-08); warm latency ~34 ms

## PHASE 4 — LINE CROSSING

- [✓] Virtual line implemented — `LineCounter`, `line_x = frame_width * line_position` from config; 12 unit tests
- [✓] Bottom-center tracking point — `Detection.bottom_center`; `test_bottom_center_computed_correctly_from_real_track_output`; used in `test_integration_pipeline.py`
- [✓] Left → right = ENTRY — `test_single_left_to_right_crossing_is_one_entry` + `test_scenario_1_left_to_right_is_one_entry` (integration)
- [✓] Right → left = EXIT — `test_single_right_to_left_crossing_is_one_exit` + `test_scenario_2_round_trip_entry_then_exit`
- [✓] Duplicate crossing prevention — `test_person_hovering_near_line_does_not_double_count` + `test_scenario_3_jitter_near_line_never_counts` (0 events, 0 DB rows)
- [✓] Dead-zone / hysteresis — LEFT/BUFFER/RIGHT zones + per-track *confirmed side*; `test_standing_still_*`, `_zone_for_x` logic; buffer transitions inert
- [✓] Multiple people crossing simultaneously — `test_multiple_independent_tracks_two_people_entering` + `test_scenario_4_two_people_tracked_independently` (counts + DB rows ×2, ids preserved)
- [✓] Tracking loss handled correctly — `test_stale_tracks_are_expired`, `test_track_disappearing_then_new_id_does_not_retroactively_fire`
- [M] Camera 1 crossing tested — logic verified; needs a real person crossing the real webcam view
- [ ] Camera 2 crossing tested — needs 2nd camera + person

## PHASE 5 — OCCUPANCY

- [~] Camera 1 occupancy — `OccupancyManager` wired into the pipeline; `/api/occupancy` returns it live; **increment from a real crossing** is MANUAL
- [~] Camera 2 occupancy — same code path, no 2nd camera
- [✓] Entry/exit calculations — `test_formula_initial_plus_entries_minus_exits`, `test_entries_and_exits_move_occupancy_up_and_down` + integration
- [✓] Occupancy never goes below zero — `test_never_goes_below_zero`, `test_negative_initial_occupancy_clamped_to_zero`
- [✓] Initial occupancy / reset — `test_reset_restores_initial_state`; live `POST /api/reset` → `{"ok":true}` (2026-09-08)
- [✓] Independent camera state — separate `OccupancyManager` per pipeline; `test_camera_manager.py` isolation
- [~] Restart / recovery behavior — occupancy is **in-memory only**; on restart it recomputes from 0/`initial_occupancy`, it does **not** replay events from the DB. Needs a decision (DECISIONS D11).
- [M] Occupancy accuracy manually tested — needs real crossings

## PHASE 6 — DATABASE

- [✓] SQLite database — `app/database/database.py`; 8 unit tests vs a real temp file; live `data/crowd_monitor.db` created on boot
- [✓] Sessions — `test_start_session_returns_incrementing_id`, `test_latest_session_returns_most_recent`; live sessions 1→2→3 observed
- [✓] Camera IDs — `crossing_events.camera_id`; `test_events_filtered_by_camera`
- [✓] Track IDs — `crossing_events.track_id INTEGER`; `test_record_and_fetch_events`
- [✓] Entry/exit events — `test_record_and_fetch_events`, `test_invalid_event_type_rejected`; `CHECK(event_type IN ('ENTRY','EXIT'))`
- [✓] Timestamps — `crossing_events.timestamp REAL`; asserted in DB tests
- [ ] Occupancy records — **no occupancy table exists.** Occupancy is derived from events at runtime and never persisted. Not implemented (see DECISIONS D11 — is this wanted?).
- [✓] Database persistence tested — file survives process exit; reopened successfully
- [✓] Restart persistence tested — 2026-09-08: ran, created sessions 1–2, killed, restarted → sessions 1–2 still present, new session 3 appended

## PHASE 7 — BACKEND / API

- [✓] FastAPI application — boots via `run.py`; `Application startup complete`; uvicorn on `:8000` (2026-09-08)
- [✓] Camera status API — `GET /api/status` & `GET /api/cameras` → 200, correct JSON (per-camera status/entries/exits/occupancy/fps)
- [✓] Occupancy API — `GET /api/occupancy` → 200, per-camera snapshot
- [✓] Entry/exit statistics API — entries/exits present in `/api/status`, `/api/cameras`, `/api/occupancy` responses
- [✓] Event history API — `GET /api/events` → 200 `{"events":[]}` on fresh DB; `camera_id` + `limit` params implemented; `test_database` covers filtering
- [~] Health endpoint — no dedicated `/health`; `GET /api/status` returns `{"status":"running", ...}` and works as a liveness check. Add a real `/health`.
- [✓] Error handling — `GET /video/<bogus>` → `404 {"detail":"Unknown camera_id 'nope'"}` (observed); pipeline exceptions caught & logged; DB `_cursor` rollback on error

## PHASE 8 — DASHBOARD

- [✓] Dashboard loads — `GET /` → 200, `<title>Event Crowd Monitor</title>`; renders in browser (screenshot 2026-09-08); **no JS console errors**
- [M] Camera 1 live video — `<img src="/video/event_entrance">` present, endpoint streams `multipart/x-mixed-replace`; no frames without webcam
- [ ] Camera 2 live video — needs 2nd camera
- [✓] Camera 1 occupancy — "Live crowd" stat renders (shows `0`) in browser
- [✓] Camera 2 occupancy — `dining_entrance` panel + stats render (disabled camera still shown)
- [✓] Entry count — renders in browser
- [✓] Exit count — renders in browser
- [ ] Total occupancy — dashboard shows **per-camera** occupancy only; there is no combined cross-camera total in the UI
- [✓] Camera online/offline status — status pill renders `OFFLINE` with dot (browser)
- [✓] Recent events — activity list renders; empty state "No crossings recorded yet." verified; populated feed needs real events [M]
- [✓] Reset / session controls — "Reset counts" clicked in browser → `POST /api/reset` fired → "Counters reset" toast; "Start new session" button present, endpoint verified
- [✓] Dashboard tested in browser — yes: in-app browser, screenshot + console-error check, Reset interaction

## PHASE 9 — TWO-CAMERA INTEGRATION

- [~] Camera 1 + Camera 2 run simultaneously — architecture supports it (per-camera thread + own detector); `config.yaml` toggle; **not run** with 2 streams
- [~] Camera 1 failure does not stop Camera 2 — `test_one_camera_failing_does_not_affect_a_second_camera_instance` passes (unit, simulated); no real dual-camera run
- [~] Camera 2 failure does not stop Camera 1 — same (unit only)
- [~] Independent tracking — `test_each_enabled_camera_gets_a_distinct_detector_instance` passes; real dual-stream not run
- [~] Independent occupancy — separate managers; unit-verified; real dual-stream not run
- [~] Combined dashboard — 2 panels render (verified); with 2 real live feeds not tested
- [ ] Long-running stability test — not started

## PHASE 10 — REAL CCTV / RTSP

- [ ] Real Camera 1 connected
- [ ] Real Camera 1 detection tested
- [ ] Real Camera 1 tracking tested
- [ ] Real Camera 1 line crossing calibrated
- [ ] Real Camera 2 connected
- [ ] Real Camera 2 detection tested
- [ ] Real Camera 2 tracking tested
- [ ] Real Camera 2 line crossing calibrated
- [ ] Both real cameras run simultaneously

_(RTSP code path exists — `CameraStream` passes URL strings straight to `cv2.VideoCapture` with the same reconnect logic — but nothing here has been run against a real stream.)_

## PHASE 11 — DEPLOYMENT

- [~] Production configuration — single `config.yaml`; no separate prod profile / secrets handling
- [✓] Camera URLs / config externalized — all camera + app settings in `config.yaml`; `CROWD_MONITOR_CONFIG` env override; verified by inspection
- [✓] No hardcoded development settings — `grep` of `app/` + `run.py` shows no hardcoded host/port/paths/URLs (only an RTSP example in a docstring)
- [ ] Automatic startup — no launchd plist / service unit
- [~] Application restart / recovery — clean start, DB persists (verified); **no supervisor / auto-restart**; SIGTERM currently skips the shutdown hook (`end_session` not called)
- [✓] Logging — file + stdout logging verified (`logs/app.log` written on every run)
- [ ] Database backup / recovery — none
- [ ] Mac mini Apple Silicon tested — tested on a MacBook Air M2, not the deployment box
- [~] Headless operation tested — the server itself runs fine headless here; but macOS camera access needs a GUI login session (TCC) — must be confirmed on the real box
- [✓] Local dashboard accessible — `http://localhost:8000` reachable and rendering (verified)
- [ ] 4+ hour stability test — not started
- [ ] Final end-to-end test — blocked on camera
- [~] Deployment instructions written — README covers dev setup; no dedicated deploy runbook / `DEPLOYMENT.md`

## PHASE 12 — FINAL ACCEPTANCE

- [✓] Person detection verified — real YOLO, still images (2026-09-08). Live webcam = [M].
- [✓] Multi-person tracking verified — real ByteTrack, 4 & 2 simultaneous (still images). Live = [M].
- [~] Entry counting verified — logic `[✓]` (unit + integration); on a real camera = [M]
- [~] Exit counting verified — logic `[✓]`; on a real camera = [M]
- [~] Occupancy verified — formula/clamp/reset `[✓]`; live = [M]
- [!] Camera 1 verified — BLOCKED (webcam TCC permission)
- [ ] Camera 2 verified — not started
- [✓] Database verified — 8 unit tests + live restart-persistence (2026-09-08)
- [✓] Dashboard verified — render / poll / controls / no console errors (browser). Live video = [M].
- [~] Failure recovery verified — simulated `[✓]` (unit); real camera drop / process kill recovery = [M]
- [ ] Long-running test passed — not started
- [✗] Ready for real event deployment — **NO.** Blockers above; Phases 9–12 essentially unproven.

---

## FAILURE LOG

| Date | Item | What happened | Fix / status |
|---|---|---|---|
| 2026-09-07 | `tests/test_detector.py::test_falls_back_to_cpu_when_torch_missing_entirely` | FAILED on real Mac (torch installed → returned `mps`, expected `cpu`) | FIXED — patch `sys.modules` to force `ImportError`; now passes both interpreters |
| 2026-09-07 | `tests/test_detector.py` fakes | `uninstall_fakes()` popped real `torch` from `sys.modules` → later real import crashed (`Only a single TORCH_LIBRARY…`) | FIXED — save/restore original modules |
| 2026-09-08 | Graceful shutdown | `SIGTERM` to `run.py` does not run `@app.on_event("shutdown")` → `end_session()` not called, sessions left `ended_at=NULL` | OPEN — migrate to a lifespan handler (TODO / DECISIONS D12) |
| 2026-09-07→08 | macOS camera | `cv2.VideoCapture(0)` → `not authorized`; no TCC prompt in this process context | BLOCKED — needs user action from a real terminal |

---

## Update rule
Re-check the boxes after every implementation step or test run. Move an item to
`[✓]` **only** with an observed result (command output, test pass, screenshot).
Recompute "CURRENT DEPLOYMENT READINESS" from the `[✓]` count. Log every failure.

# PROGRESS — Event Crowd Monitor

Status legend: `[ ]` NOT STARTED · `[~]` IN PROGRESS · `[✓]` PASSED ·
`[✗]` FAILED · `[!]` BLOCKED · `[M]` MANUAL TEST REQUIRED

_Last updated: 2026-09-08_

> Phase-by-phase deployment checklist + readiness % lives in **DEPLOYMENT_STATUS.md**.
> This file = chronological dev log + milestones.

## Milestones

- [✓] **M0 — Code built & unit-tested in sandbox** (pre-existing; 50 tests)
- [✓] **M1 — Bring-up on real hardware (MacBook Air M2, macOS 15.7.3)**
  - [✓] venv created (`.venv`, `--system-site-packages`, Python 3.9.6)
  - [✓] Missing deps installed: fastapi, uvicorn[standard], python-multipart, lapx
  - [✓] `models/yolo11n.pt` downloaded (5.4 MB)
  - [✓] Unit suite green on this machine (59/59 after additions — see TEST_STATUS.md)
  - [✓] Real YOLO11n + ByteTrack + MPS inference verified (bundled bus.jpg / zidane.jpg)
  - [✓] `python run.py` boots; all `/api/*` + `/video/{id}` endpoints verified
  - [✓] Dashboard renders + polls + Reset button round-trips (browser-checked)
  - [✓] Graceful degradation verified (camera unavailable → OFFLINE, app keeps serving)
  - [✓] Counting → occupancy → SQLite wiring verified end-to-end (integration test)
- [!] **M2 — Live webcam path** — BLOCKED: macOS Camera (TCC) permission not
  grantable to the host process in this environment. Needs the user to run
  `python run.py` from their own Terminal and approve the prompt.
  - [M] `test_camera.py` live preview
  - [M] Live annotated MJPEG feed in the dashboard
  - [M] Physical walk-through: L→R entry, R→L exit, no double-count, multi-person
- [ ] **M3 — Camera 2 (dining_entrance)** — needs a 2nd physical camera
- [ ] **M4 — RTSP / real CCTV** — needs a real stream
- [ ] **M5 — Deployment** — auto-start, backup, headless-on-target, 4h stability, deploy runbook
      (DEPLOYMENT_STATUS.md Phases 9–12 ≈ 8% verified → **not deployment-ready**)

## Implementation log

| Date | Step | Result |
|---|---|---|
| (pre) | Core app built, 50 unit tests written | 50/50 in sandbox |
| 2026-09-07 | venv + deps on M2; `models/yolo11n.pt` fetched | OK |
| 2026-09-07 | Fixed `tests/test_detector.py::test_falls_back_to_cpu_when_torch_missing_entirely` (was env-dependent) | 50/50 |
| 2026-09-07 | Fixed `app/main.py`: added `prime_camera_permissions()` (main-thread TCC prime) | boots clean |
| 2026-09-07 | Verified real YOLO/ByteTrack/MPS via bundled images | PASS |
| 2026-09-07 | Verified FastAPI app + dashboard in a browser | PASS |
| 2026-09-07 | Made `test_detector.py` fakes non-destructive (save/restore sys.modules) | fixed cross-test torch re-import crash |
| 2026-09-07 | Added `tests/test_integration_pipeline.py` (5 tests) | 5/5 PASS |
| 2026-09-07 | Added `tests/test_real_yolo_smoke.py` (4 tests, real stack) | 4/4 PASS |
| 2026-09-07 | Created PROGRESS / TEST_STATUS / ARCHITECTURE / DECISIONS / TODO | — |
| 2026-09-07 | **Final verification pass** — re-ran everything against the 5 tracking files | see below |
| 2026-09-08 | Re-verified suite (59/59), real YOLO/MPS, all endpoints, config externalization | PASS |
| 2026-09-08 | Tested DB restart-persistence (run → kill → restart) | PASS — sessions survive |
| 2026-09-08 | Found: SIGTERM does not run `@app.on_event("shutdown")` → `end_session()` skipped | FAIL — tracked (D12) |
| 2026-09-08 | Re-checked camera hardware access | still BLOCKED (`not authorized`) |
| 2026-09-08 | Created **DEPLOYMENT_STATUS.md** (12-phase checklist, readiness %, blockers, next actions) | — |
| 2026-09-08 | Rewrote TEST_STATUS.md to name/date/result/evidence schema; added DECISIONS D11–D12 | — |

## Final verification (2026-09-07)

Re-proven by command, not asserted:

| Claim | Command | Observed |
|---|---|---|
| Automated suite (venv 3.9.6) | `.venv/bin/python -m unittest discover -s tests` | `Ran 59 tests ... OK` |
| Automated suite (system python3) | `python3 -m unittest discover -s tests` | `Ran 59 tests ... OK` |
| Real-YOLO smoke actually ran | `.venv/bin/python -m unittest tests.test_real_yolo_smoke -v` | 4/4 ok, 0 skipped |
| Real YOLO on MPS | live `PersonDetector` on bundled bus.jpg | `device=mps`, 4 people, int IDs `[1,2,3,4]`, stable across passes, 34 ms warm |
| All REST endpoints | curl `/api/status|cameras|occupancy|events`, POST `/api/reset|session/start` | 200 / valid JSON; session id increments 2→3 |
| MJPEG route | `curl -D- /video/event_entrance` | `content-type: multipart/x-mixed-replace; boundary=frame` |
| Unknown camera | `curl /video/bogus` | `404 {"detail":"Unknown camera_id 'bogus'"}` |
| Dashboard | in-app browser at :8000 | panels render from polling, OFFLINE pills correct, no JS console errors |
| Graceful degradation (§13) | live server log + `/api/cameras` | 0 tracebacks, camera `OFFLINE`, `/api/status` → 200 |
| No biometric columns | `PRAGMA table_info` on live `data/crowd_monitor.db` | sessions/crossing_events only; biometric-ish columns: NONE |
| Everything compiles | `py_compile` app + tests + run.py + test_camera.py | OK |

Not verifiable here (correctly left `[!]`/`[M]`): live webcam open + physical
walk-through — macOS Camera permission is not grantable to this process.

## Update rule
Append a row to the implementation log after every major implementation step,
and re-check the milestone boxes.

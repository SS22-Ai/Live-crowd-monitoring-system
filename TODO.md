# TODO — Event Crowd Monitor

Only genuinely remaining work. Done items live in PROGRESS.md.
Phase numbers refer to DEPLOYMENT_STATUS.md.

Legend: `[ ]` NOT STARTED · `[~]` IN PROGRESS · `[!]` BLOCKED · `[M]` MANUAL (needs you)

_Last updated: 2026-09-08_

---

## BLOCKED ON YOU (nothing proceeds on the live-camera path until this is done)

- [!] Grant macOS Camera permission to the terminal app you'll run Python from,
      then: `.venv/bin/python test_camera.py` from that Terminal. Report the
      AVAILABLE indexes + whether the preview showed your webcam.  *(Phase 2)*

## MANUAL — need you + the webcam once it's unblocked

- [M] Live annotated feed on the dashboard (`run.py` → :8000, `event_entrance` ONLINE).  *(Phase 8)*
- [M] Walk-through §6.1–6.4: L→R entry, R→L exit, hover = no count, two people independent.  *(Phase 4/12)*
- [M] Watch dashboard entry/exit/occupancy + activity feed update from real crossings.  *(Phase 8)*
- [M] Real live-video tracking stability (moving person, brief occlusion).  *(Phase 3)*
- [M] Unplug/replug the webcam mid-run → expect RECONNECTING → ONLINE, no crash.  *(Phase 2)*
- [M] 4+ hour continuous run — watch for leaks / fps drift / crashes.  *(Phase 11/12)*

## CODE — decisions to make (see DECISIONS D11/D12)

- [x] **D11:** RESOLVED 2026-09-12 — crash-recovery via session resume,
      implemented + verified live. See `DECISIONS.md`.
- [x] **D12:** RESOLVED 2026-09-12 — real root cause was the MJPEG stream,
      not `@app.on_event`; fixed without a lifespan migration. See `DECISIONS.md`.

## CODE — features not yet built

- [ ] `GET /health` (or `/healthz`) dedicated liveness/readiness endpoint
      (currently only `/api/status`).  *(Phase 7)*
- [ ] Dashboard: combined cross-camera **total occupancy** tile (today it's
      per-camera only).  *(Phase 8)*
- [ ] Camera 2: enable in `config.yaml` + real `source`; verify two pipelines
      run together, independent tracking/occupancy, one failing ≠ stops the
      other (currently only unit-tested with a fake backend).  *(Phase 9)*
- [ ] RTSP: point a `source` at `rtsp://…`; verify connect + reconnect on
      stream drop; calibrate `line_position` / `line_buffer` for the real view.  *(Phase 10)*
- [ ] Deployment: launchd plist (or equivalent) for auto-start on the Mac mini;
      supervised restart on crash.  *(Phase 11)*
- [ ] Deployment: DB backup/rotation strategy for `data/crowd_monitor.db`.  *(Phase 11)*
- [ ] Write `DEPLOYMENT.md` — target setup, headless/login-session note for
      camera TCC, start/stop, log locations, upgrade steps.  *(Phase 11)*
- [ ] Verify on the actual deployment box (Mac mini Apple Silicon), headless.  *(Phase 11)*

## CLEANUP / NICE-TO-HAVE

- [ ] `session_label` in the dashboard shows the real session id on first load
      (add `session_id` to `/api/status`).
- [ ] MJPEG generator: stop on client disconnect instead of relying on the
      server dropping the coroutine.
- [ ] `frontend` loads Google Fonts from the network — bundle a local fallback
      for fully-offline operation.
- [ ] CI: run `tests/` on push (unit + integration always; real-yolo smoke when
      a model is cached).
- [ ] Optional: WebSocket push to replace 1s/2s polling.
- [ ] Decide whether to keep `.venv --system-site-packages` or pin a hermetic
      venv from `requirements.txt` (DECISIONS D6).

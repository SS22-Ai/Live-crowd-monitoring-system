# Event Crowd Monitor — Developer Handover

_Last updated: 2026-09-13 (added the launchd auto-restart supervisor and
`DEPLOYMENT.md` runbook — see §13 and §14 item 6). Previous update
2026-09-12 (end of day — session persistence model, dashboard redesign, and
CSV reports were all added in the final hour; read §7, §9, §10 and §14 even
if you've seen this file before). If you're picking this project up cold,
read this whole file before touching code — it will save you from
re-discovering things the hard way._

---

## 1. What this project does

A local, on-device system that watches one or two camera feeds pointed at
entrances, counts people walking in and out by detecting a virtual line
crossing, and shows a live occupancy count on a web dashboard.

- **No cloud.** Everything runs on one Mac.
- **No face recognition, no biometrics.** People are anonymous bounding
  boxes with a temporary numeric ID that means nothing once the process
  restarts (this is asserted by an automated test on the database schema).
- **Two zones by default**: `event_entrance` (Camera 1, the main
  entrance) and `dining_entrance` (Camera 2, a second zone) — but the
  code doesn't hardcode "2 cameras"; `config.yaml` can define any number.
- Built for a live event: someone points a camera at a doorway, the app
  tells you how many people are currently inside that zone, in real time.

---

## 2. Architecture

```
   Camera (webcam index OR RTSP URL)
          │
          ▼
   CameraStream            — opens the source, reconnect/status FSM
   (app/camera/stream.py)    (ONLINE / OFFLINE / RECONNECTING)
          │
          ▼
   PersonDetector           — YOLO11n + ByteTrack (Ultralytics),
   (app/vision/detector.py)   device = MPS if available else CPU
          │  Detection(track_id, x1,y1,x2,y2, confidence)
          ▼
   LineCounter              — buckets each detection LEFT/BUFFER/RIGHT
   (app/vision/line_counter.py)  by bbox bottom-center; fires ENTRY/EXIT
          │  CrossingEvent(track_id, ENTRY|EXIT, timestamp)
          ▼
   OccupancyManager         — live = max(0, initial + entries - exits)
   (app/occupancy/manager.py)
          │
          ▼
   Database                 — SQLite: sessions + crossing_events
   (app/database/database.py)
          │
          ▼
   FastAPI routes           — /api/*, /video/{id} (MJPEG)
   (app/api/routes.py)
          │
          ▼
   Dashboard (frontend/)    — polls the API, renders live video + counts
```

All of the above runs **per camera**, in its own thread (`CameraPipeline`
in `app/camera/manager.py`), with its **own** `PersonDetector` instance.
One `CameraManager` (`app/camera/manager.py`) owns all camera pipelines.

### Camera 1 (`event_entrance`) vs Camera 2 (`dining_entrance`)

There is nothing structurally special about "Camera 1" vs "Camera 2" —
they are just two entries in `config.yaml`'s `cameras:` list, each
producing an independent `CameraPipeline`. Each has its own:
- `CameraStream` (own connection, own reconnect state)
- `PersonDetector` (own YOLO model instance — **never shared**, because
  ByteTrack's `persist=True` state lives inside the model object; sharing
  one model across two camera threads would corrupt both trackers)
- `LineCounter` (own entry/exit counts)
- `OccupancyManager` (own live occupancy)

If one camera's source fails (unplugged, RTSP drops), it goes to
`RECONNECTING` → `OFFLINE` independently — the other camera and the rest
of the app (API, dashboard, database) are unaffected. This is both unit
tested (`tests/test_camera_stream.py`, `tests/test_camera_manager.py`)
and has been observed live with real hardware.

---

## 3. Project structure

```
event_crowd_monitor/
├── app/
│   ├── main.py                  # FastAPI app factory: wires everything together,
│   │                             #   camera-permission priming, shutdown hook,
│   │                             #   no-cache middleware for the dashboard
│   ├── config.py                 # loads config.yaml (or $CROWD_MONITOR_CONFIG)
│   │                             #   into typed CameraConfig / AppConfig objects
│   ├── camera/
│   │   ├── stream.py              # CameraStream: open/read one camera,
│   │   │                         #   ONLINE/OFFLINE/RECONNECTING state machine
│   │   ├── frame_reader.py        # LatestFrameReader: fixes RTSP frame staleness
│   │   │                         #   (see §14 — this was a real bug, now fixed)
│   │   └── manager.py             # CameraManager + CameraPipeline: one thread per
│   │                             #   camera, runs detector→counter→occupancy→DB
│   ├── vision/
│   │   ├── detector.py            # PersonDetector: YOLO11n + ByteTrack wrapper,
│   │   │                         #   MPS/CPU device selection
│   │   ├── line_counter.py        # LineCounter: the actual counting algorithm
│   │   └── draw.py                # draws the line/boxes/IDs/stats onto a frame
│   ├── occupancy/
│   │   └── manager.py             # OccupancyManager: the occupancy formula
│   ├── database/
│   │   └── database.py            # Database: SQLite sessions + crossing_events
│   └── api/
│       └── routes.py              # all /api/* and /video/{id} routes
├── frontend/
│   ├── index.html                 # dashboard HTML (summary bar + camera panels)
│   ├── app.js                     # polls /api/status (1s) and /api/events (2s)
│   └── style.css                  # dark-theme styling
├── tests/                         # 74 automated tests, no camera/model needed
│                                  #   except test_real_yolo_smoke.py (auto-skips
│                                  #   if the real stack/model isn't present)
├── models/yolo11n.pt              # YOLO model (gitignored, auto-downloads ~6MB)
├── data/crowd_monitor.db          # SQLite DB (gitignored, created on first run)
├── logs/app.log                   # log file (gitignored, created on first run)
├── config.yaml                    # TRACKED IN GIT — safe, demo-only camera config
├── config.local.yaml              # GITIGNORED — real camera credentials go here
├── requirements.txt
├── run.py                         # entrypoint: uvicorn.run(create_app(), ...)
├── run.sh                         # convenience wrapper: creates venv if missing
├── test_camera.py                 # standalone webcam probe (run before run.py)
├── README.md                      # original quick-start doc (partially historical)
├── HANDOVER.md                    # this file — the up-to-date comprehensive guide
├── ARCHITECTURE.md                # module-level architecture reference
├── DECISIONS.md                   # chronological log of *why* things were built
│                                  #   this way, including both P0 bug writeups
├── DEPLOYMENT_STATUS.md           # the detailed 12-phase deployment checklist
├── DEPLOYMENT.md                  # event-day runbook: install/start/stop/troubleshoot
├── deploy/
│   └── com.eventcrowdmonitor.app.plist  # launchd LaunchAgent: auto-start + crash restart
├── PROGRESS.md / TEST_STATUS.md / TODO.md  # supporting tracking docs
```

**Which doc to read for what:**
- Quick setup steps → `README.md`
- Deep architecture / "why is it built this way" → this file + `DECISIONS.md`
- "Is X actually verified?" → `DEPLOYMENT_STATUS.md`
- "How do I actually run this unattended on event day?" → `DEPLOYMENT.md`
- "What's left to do?" → `TODO.md`

---

## 4. How to run

```bash
cd event_crowd_monitor

# one-time setup
python3 -m venv .venv --system-site-packages   # see DECISIONS.md D6 for why
.venv/bin/python -m pip install fastapi "uvicorn[standard]" python-multipart lapx
# (if you did a plain `python3 -m venv .venv` without --system-site-packages,
#  instead run: .venv/bin/pip install -r requirements.txt)

# test the webcam BEFORE running the full app (macOS will prompt for Camera access)
.venv/bin/python test_camera.py

# run with the default (safe, demo) config — built-in webcam only
.venv/bin/python run.py

# OR run with real camera credentials (see §5)
CROWD_MONITOR_CONFIG=config.local.yaml .venv/bin/python run.py
```

Then open **http://localhost:8000**.

**Stop it** with a plain `Ctrl+C` or `kill <pid>` — as of the 2026-09-12
fix, this exits cleanly within ~5-6 seconds, no force-kill needed (see §14).

---

## 5. Configuration

Two files, same format, different purposes:

| File | Purpose | In git? |
|---|---|---|
| `config.yaml` | Default config — built-in webcam only, safe to commit | **Yes, tracked** |
| `config.local.yaml` | Real camera credentials (RTSP URLs with passwords) | **No, gitignored** |

Select which one to use with the `CROWD_MONITOR_CONFIG` environment
variable (`app/config.py`); if unset, `config.yaml` is used.

**`app:` section** (global settings):
```yaml
app:
  model_path: models/yolo11n.pt
  model_confidence: 0.4      # YOLO detection confidence threshold
  inference_width: 640       # frames are resized to this before YOLO runs
  inference_height: 480
  target_fps: 15             # currently unused/informational — not wired to
                              # any actual frame-rate limiting logic
  frame_skip: 0               # process every Nth frame (0 = every frame)
  db_path: data/crowd_monitor.db
  log_path: logs/app.log
  host: 0.0.0.0
  port: 8000
```

**Per-camera settings** (`cameras:` list, one entry per zone):
```yaml
- id: event_entrance          # internal id, used in API responses/DB rows
  name: Event Entrance        # display name on the dashboard
  source: 0                   # int = webcam index; any other string = RTSP/URL,
                              # passed straight to cv2.VideoCapture(source)
  enabled: true                # false = pipeline not started at all (no model load)
  line_position: 0.50          # counting line at this fraction of frame width
  line_buffer: 20               # +/- px dead-zone around the line (see §6)
  entry_direction: left_to_right   # or right_to_left — which crossing = ENTRY
  initial_occupancy: 0
  reconnect_interval_seconds: 3.0  # how often to retry a dead camera
  track_expiry_seconds: 2.0        # forget a track if unseen this long
```

**Adding an RTSP camera** — see `README.md` §8 for the full walkthrough
(URL-encoding special characters in the password, credential security,
brand-specific URL path formats). Short version:
```yaml
source: rtsp://admin:admin%40123@192.168.1.200:554/cam/realmonitor?channel=1&subtype=0
```

---

## 6. How counting works

**The core file is `app/vision/line_counter.py` — read its docstring, it's short and precise.**

- Each camera has a **vertical line** at `line_position × frame_width`,
  with a `line_buffer`-pixel **dead zone** on either side of it. Every
  frame, each tracked person is bucketed into `LEFT`, `BUFFER`, or `RIGHT`
  based on the **bottom-center point** of their bounding box (more stable
  than the box centroid for a walking person — their feet are the anchor).
- For each track (by ByteTrack's temporary integer ID), the code
  remembers the last **confirmed side** — LEFT or RIGHT, **never**
  BUFFER. Standing in the buffer, or jittering side-to-side within it,
  never changes the confirmed side and never fires an event — **this is
  the entire duplicate-prevention mechanism.**
- An event fires **only** when the confirmed side actually flips
  (LEFT→RIGHT or RIGHT→LEFT). `entry_direction` decides which flip means
  ENTRY vs EXIT:
  - `left_to_right`: LEFT→RIGHT = **ENTRY**, RIGHT→LEFT = **EXIT**
  - `right_to_left`: the reverse
- Tracks not seen for `track_expiry_seconds` are forgotten, so a stale ID
  can't cause a bogus event later (e.g. if ByteTrack reassigns that
  number to someone new).
- **Multiple people** are tracked completely independently — each has
  its own `TrackState` keyed by track ID, so two people crossing at the
  same time produce two independent events with two different IDs.

**Verified:** 12 unit tests (`tests/test_line_counter.py`) + 5 integration
tests (`tests/test_integration_pipeline.py`, which drive the real
`LineCounter` + `OccupancyManager` + real SQLite through all four
scenarios below) all pass.

**NOT yet verified:** a deliberate, controlled real-world crossing test
(walk left-to-right on a real camera and confirm exactly ENTRY+1) has
never actually been done — see §14 and `DEPLOYMENT_STATUS.md`.

---

## 7. Occupancy

`app/occupancy/manager.py` — deliberately tiny:

```python
live_occupancy = max(0, initial_occupancy + entries - exits)
```

- Clamped so it can never go negative (e.g. if an EXIT fires without a
  matching prior ENTRY — a spurious extra exit, or restart with the
  wrong initial value).
- Each camera has its **own** `OccupancyManager` — occupancy for
  `event_entrance` and `dining_entrance` are entirely independent counts.
- **Persists across every restart — clean stop, crash, anything.** There
  is still no `occupancy` table (no new table was needed); instead, on
  startup `app/main.py`'s `resolve_startup_session()` always resumes the
  most recent session (if one exists at all) and `CameraManager` replays
  its `crossing_events` back into each camera's counters via
  `db.count_events()`. This was explicitly requested and changed **twice**
  the same day (`DECISIONS.md` D11): first cut only resumed after a
  crash; broadened a few hours later so an *ordinary* stop/restart also
  resumes, because that's what's actually needed for a real event
  (someone closing the terminal to check something shouldn't lose the
  count).
- **The only thing that actually resets counts to zero for good** is
  clicking **Reset counts** or **Start new session** on the dashboard —
  both go through `begin_fresh_session()` in `app/api/routes.py`, which
  closes the current DB session and opens a new one. This matters:
  without closing the old session, a plain in-memory reset would be
  silently undone the next time the app restarts and replays the old
  (pre-reset) session's events back in. If you ever touch reset/session
  logic, keep this in mind or resets will "come back from the dead."

Verified live (not just tests): injected events, did a **clean** `SIGTERM`
stop (not a crash) → restart → counts persisted, not reset. Then hit
`POST /api/reset` → counts went to 0 and stayed at 0 through *another*
restart (confirming the reset actually stuck). 9 tests in
`tests/test_session_resume.py`; live via `GET /api/occupancy`.

---

## 8. Database

SQLite, file at `data/crowd_monitor.db` (path configurable). Schema
(`app/database/database.py`):

```sql
sessions(
  id INTEGER PRIMARY KEY,
  started_at REAL,
  ended_at REAL NULL,        -- set when the app shuts down cleanly
  notes TEXT NULL
)

crossing_events(
  id INTEGER PRIMARY KEY,
  session_id INTEGER,        -- FK to sessions.id
  timestamp REAL,
  camera_id TEXT,            -- e.g. "event_entrance"
  track_id INTEGER,          -- the ephemeral ByteTrack ID at the time
  event_type TEXT CHECK (event_type IN ('ENTRY', 'EXIT'))
)
```

- **No face data, no embeddings, no identity columns — anywhere.** This
  is enforced by an automated test that inspects the live schema
  (`tests/test_database.py`), not just a design promise.
- `track_id` is meaningless outside the process that generated it —
  ByteTrack can and will reuse small integers across different real
  people once old tracks expire.
- A new `sessions` row is created on the **very first run ever** (empty
  database), and every time someone clicks **Reset counts** or **Start
  new session** on the dashboard. An ordinary app restart does **not**
  create a new row — it resumes the existing one (see §7). `ended_at` is
  therefore no longer "when the process last stopped" in a meaningful
  sense — it's `NULL` for whatever session is currently active (may have
  survived several restarts) and set only once a human explicitly closes
  it via Reset/New session.

Verified: 8 unit tests against a real temp SQLite file; live persistence
across a real restart (2026-09-08, broadened 2026-09-12 to cover clean
restarts too — see §7); live clean session-close via `ended_at` after the
2026-09-12 shutdown fix.

---

## 9. API

All defined in `app/api/routes.py`.

| Endpoint | Method | Returns |
|---|---|---|
| `/api/status` | GET | App status + every camera's stats (status/entries/exits/live_occupancy/fps) |
| `/api/cameras` | GET | Same per-camera stats, without the app-level wrapper |
| `/api/occupancy` | GET | Per-camera occupancy snapshot |
| `/api/events` | GET | Recent crossing events. Query params: `?camera_id=&limit=` |
| `/api/reset` | POST | Closes the current session, opens a new one, resets all counters (see §7 — this is the ONLY durable reset) |
| `/api/session/start` | POST | Same underlying action as `/api/reset` (both call `begin_fresh_session()`) — kept as a separate labeled button/endpoint |
| `/api/reports/interval` | GET | `?interval_minutes=15\|30\|60` (default 30). Buckets the *entire current session* into N-minute windows; per camera: entries, exits, occupancy at the end of that window. Computed from `crossing_events`, nothing new stored. |
| `/api/reports/interval.csv` | GET | Same data as above, as a CSV file download (`Content-Disposition: attachment`) — this is the "download the whole-time report" feature. |
| `/video/{camera_id}` | GET | MJPEG live annotated stream (`multipart/x-mixed-replace`). 404 if `camera_id` is unknown |

- No `/health` endpoint exists — `/api/status` doubles as a liveness check.
- No authentication — fine for a local/LAN-only deployment, not for
  exposing this beyond the venue's own network.
- Live updates are **polling**, not WebSockets: the dashboard fetches
  `/api/status` every 1s and `/api/events` every 2s. This is deliberate
  (simplicity/reliability over V1) — see `DECISIONS.md` D4.

Verified: every endpoint has been hit live repeatedly this project
(200s, correct JSON, correct 404 handling).

---

## 10. Dashboard

`frontend/index.html` + `app.js` + `style.css`, served at `/` and `/static/*`.
Redesigned into **three tabs** on 2026-09-12 (was a single mixed grid before):

- **Top bar** (always visible): title, current session label, "Reset counts"
  and "Start new session" buttons.
- **Summary bar** (always visible, above the tabs): "Total crowd inside
  event area" (`event_entrance.live_occupancy − dining_entrance.entries`,
  clamped at 0 — someone who walked into dining is no longer "in the event
  area") and "Total crowd inside dining" (`dining_entrance.entries`). Both
  computed client-side in `app.js` from `/api/status`. **Hardcoded to
  those two specific camera IDs** — rename/add cameras and `updateSummary()`
  needs updating.
- **Overview tab** (default): numbers only, no video — per-camera status
  pill + Live Crowd / Entry / Exit. This is what most people watching the
  dashboard actually want.
- **Preview tab**: video only, no numbers — per-camera live MJPEG feed
  (counting line/boxes/IDs burned in server-side by `draw.py`) + status pill.
- **Reports tab**: a 15/30/60-minute interval breakdown table per camera
  (from `/api/reports/interval`), a Refresh button, and a **Download CSV**
  link (`/api/reports/interval.csv`) covering the whole current session.
  Loaded on-demand (tab open / Refresh / interval change) — not polled
  continuously, since it's a look-back report, not a live view.
- **Recent activity list** (under Overview): the last ~15 crossing events,
  polled every 2s.

**A real CSS bug was found and fixed while building this — worth knowing
about if tabs ever misbehave again:** `.tab-panel { display: flex }` was
silently overriding the `[hidden]` attribute's `display: none` (same CSS
specificity; an author rule beats the browser's own default for `[hidden]`).
Result: switching tabs updated the JS/DOM state correctly but **both
panels stayed visually stacked on screen**. Fixed with an explicit
`.tab-panel[hidden] { display: none; }` override in `style.css`. If you
ever add a new `display`-setting rule targeting `.tab-panel` (or any
`[hidden]` element), re-add a matching `[hidden]` override or this comes back.

Verified: renders correctly, polls correctly, buttons work, tab switching
confirmed correct in the browser (all three tabs, plus the interval
selector triggering a re-fetch and the CSV download producing correct
headers/content), zero JS console errors — including with a real RTSP
feed. `Cache-Control: no-store` (added 2026-09-12) means a frontend edit
always shows up on a normal refresh, no more stale-cache confusion.

---

## 11. Testing

```bash
# the whole suite — 91 tests, fast, no camera/model needed for 87 of them
.venv/bin/python -m unittest discover -s tests -v

# a single file
.venv/bin/python -m unittest tests.test_line_counter -v
```

| File | Tests | What it covers | Needs real hardware? |
|---|---|---|---|
| `test_line_counter.py` | 12 | Core counting algorithm | No |
| `test_occupancy.py` | 7 | Occupancy formula | No |
| `test_database.py` | 8 | SQLite, incl. no-biometrics check | No |
| `test_camera_stream.py` | 7 | Reconnect/status state machine (fake capture) | No |
| `test_camera_manager.py` | 3 | Per-camera detector isolation | No |
| `test_detector.py` | 13 | Adapter logic vs FAKE torch/ultralytics | No |
| `test_integration_pipeline.py` | 5 | Real LineCounter+Occupancy+SQLite together | No |
| `test_real_yolo_smoke.py` | 4 | **Real** YOLO+ByteTrack+MPS on a bundled image | Needs real torch/ultralytics + the model file (auto-skips otherwise) |
| `test_main_frontend_caching.py` | 5 | No-cache middleware predicate | No |
| `test_video_feed_shutdown.py` | 5 | MJPEG generator stops on disconnect (shutdown fix) | No |
| `test_frame_reader.py` | 5 | RTSP staleness fix (`LatestFrameReader`) | No |
| `test_session_resume.py` | 9 | Resume-on-restart + `begin_fresh_session` reset durability (§7) | No |
| `test_interval_report.py` | 8 | 30-min bucketing math for `/api/reports/interval` | No |

**What automated tests do NOT cover (manual testing required):**
- Anything needing a real physical person: a deliberate walk-through
  crossing, multi-person live crossing, jitter-at-the-line with a real
  body
- Real webcam access (macOS Camera permission is per-launching-process;
  can't be exercised from every context)
- Real RTSP against a specific brand of camera you haven't tried yet
- Multi-hour stability
- Behavior on a different machine (e.g. a Mac mini)

**A passing automated test proves the logic is correct. It does not
prove the real-world behavior is correct** — see `DEPLOYMENT_STATUS.md`
for the honest distinction on every feature.

---

## 12. Troubleshooting

**Camera permission (macOS)**
- Symptom: `OpenCV: not authorized to capture video (status 0)`.
- Fix: run from a real Terminal (not through an automation tool) and
  approve the Camera permission prompt, or enable it manually in System
  Settings → Privacy & Security → Camera for whichever app is actually
  launching Python.
- If you see `can not spin main run loop from other thread`: this is
  already handled by `prime_camera_permissions()` in `app/main.py`
  (opens the camera on the main thread before worker threads touch it).
  If it still happens, try `OPENCV_AVFOUNDATION_SKIP_AUTH=1 python run.py`.

**Camera not found / stuck OFFLINE**
- Check `logs/app.log` for `Camera <id> failed to open` messages.
- For a webcam: run `test_camera.py` to see which indexes are AVAILABLE.
- For RTSP: see the next item.

**RTSP failure**
1. Check basic network reachability first, *before* suspecting the URL:
   ```bash
   ping <camera-ip>              # may fail even if the device is fine — many
                                  #   cameras block ICMP; not conclusive alone
   arp -a | grep <camera-ip>     # should show a real MAC address, not "incomplete"
   nc -z -w3 <camera-ip> 554     # RTSP port reachability
   ```
   An "incomplete" ARP entry means nothing on the network answered at
   all — that's a network/power/topology problem, not a URL problem.
2. Confirm the analysis machine is on the **same local network** as the
   camera/NVR — RTSP over a private IP (`192.168.x.x`) does not work
   from a different network or "just having internet access." See
   `DECISIONS.md` for the full explanation if this needs re-explaining.
3. If reachable but the stream won't open, try alternate URL path
   formats — brand-specific (see README §8).
4. Remember to URL-encode special characters (`@`, etc.) in the password.

**YOLO / model problems**
- `models/yolo11n.pt` missing → Ultralytics auto-downloads it (~6MB) on
  first run, needs network access once.
- Model load failure raises a clear `RuntimeError` naming the path —
  check `cfg.model_path` in whichever config file is actually active.

**MPS problems**
- `select_device()` (`app/vision/detector.py`) falls back to CPU
  automatically if `torch.backends.mps.is_available()` is False — check
  `logs/app.log` for `Using device: MPS` vs `Using device: CPU`.
- CPU-only will work but will be significantly slower.

**Dashboard problems**
- Blank page or old content after an edit: should not happen anymore
  (no-store cache headers added 2026-09-12) — if it does, hard-refresh
  (Cmd+Shift+R) to rule out a browser-level cache from before that fix.
- JS console errors: check `updateSummary()` in `app.js` if you've
  renamed camera IDs — it hardcodes `event_entrance`/`dining_entrance`.

**Database problems**
- `data/crowd_monitor.db` is gitignored and created fresh on first run —
  deleting it is safe (loses history, not code).
- If you need a clean slate: stop the app, delete the `.db` file, restart.

**"[Errno 48] address already in use" on startup**
- Something is already listening on port 8000 — almost always a previous
  `run.py` you (or an assistant/tool) forgot to stop, not a real bug.
  ```bash
  lsof -ti:8000 -sTCP:LISTEN        # shows the PID holding it
  kill -9 $(lsof -ti:8000 -sTCP:LISTEN)
  ```
  This came up repeatedly when both a human and an AI assistant were each
  independently starting/stopping the app in the same session — worth a
  quick "is anything already running?" check before every start if that's
  your workflow too.

**Restart / shutdown problems**
- As of 2026-09-12, `kill <pid>` (SIGTERM) or Ctrl+C should exit cleanly
  within ~5-6 seconds, camera threads stopped, session `ended_at` written.
- If it ever hangs again needing a force-kill, that's a regression —
  see `DECISIONS.md` D12 and `tests/test_video_feed_shutdown.py` for what
  broke it before and how it was fixed (an open MJPEG stream connection
  that never noticed the client had disconnected).

---

## 13. Deployment (to another Mac / a Mac mini)

**Nobody has done this end-to-end yet — this is the untested part.**
Steps, based on what worked on this MacBook:

1. Copy/clone the repository to the target Mac.
2. Check what Python is available: `python3 --version`. 3.9+ works.
3. Create the venv:
   ```bash
   python3 -m venv .venv --system-site-packages
   .venv/bin/python -m pip install fastapi "uvicorn[standard]" python-multipart lapx
   ```
   If the target Mac does **not** already have `torch`/`ultralytics`/`opencv-python`
   installed system-wide (this one did, by luck/prior setup), instead do
   a plain `python3 -m venv .venv` and `pip install -r requirements.txt`
   — this will download torch fresh (~200MB).
4. Confirm MPS: `.venv/bin/python -c "import torch; print(torch.backends.mps.is_available())"`
   should print `True` on any Apple Silicon Mac.
5. Grant Camera permission: run `.venv/bin/python test_camera.py` from a
   real Terminal window on that Mac and approve the prompt.
6. Create `config.local.yaml` with the real camera(s) for that venue
   (never commit it — already gitignored).
7. Run: `CROWD_MONITOR_CONFIG=config.local.yaml .venv/bin/python run.py`,
   open `http://localhost:8000`.
8. **For unattended/event-day running**: as of 2026-09-13, a launchd
   auto-restart supervisor exists — `deploy/com.eventcrowdmonitor.app.plist`
   — with a full install/start/stop/troubleshoot runbook in
   `DEPLOYMENT.md`. It has NOT yet been installed or verified live on any
   machine (installing it is a standing config change on the actual
   deployment box, left for a human to run deliberately, not automated).
   If you move to a different Mac, every absolute path in the plist needs
   updating first — see the comments in that file.

---

## 14. Current known problems

| # | Problem | Status |
|---|---|---|
| 1 | SIGTERM used to hang forever, needed SIGKILL, session never closed | **FIXED** 2026-09-12 (`cc2bf39`) — root cause: an open MJPEG stream kept its connection alive forever, so uvicorn's graceful shutdown (which waits for in-flight requests before calling the app's shutdown hook) never completed. Fixed with client-disconnect detection + a 5s bounded timeout. |
| 2 | RTSP frames could be up to 7s stale, missing fast-moving people | **FIXED** 2026-09-12 (`8d902cd`) — root cause: OpenCV's internal RTSP buffer grows when the pipeline reads slower than frames arrive. Fixed with `LatestFrameReader`, a background thread that always keeps only the freshest frame. Reduced to ~2s (flat, not growing) on the real test camera. |
| 3 | Occupancy not persisted/replayed across a restart | **FIXED** 2026-09-12 (`d464df2`, broadened in `f4f2352`) — now resumes on every restart, resets only via Reset counts / Start new session. See §7 and `DECISIONS.md` D11. |
| 4 | RTSP URL (incl. password) logged in plain text | **OPEN** — not yet masked, low urgency since `logs/` is gitignored |
| 5 | No dedicated `/health` endpoint | **OPEN** — `/api/status` works as a substitute |
| 6 | No automatic startup / crash supervisor | **BUILT, NOT YET INSTALLED** 2026-09-13 — `deploy/com.eventcrowdmonitor.app.plist` (launchd LaunchAgent, `KeepAlive`+`RunAtLoad`) + `DEPLOYMENT.md` runbook added. Installing it (`launchctl bootstrap ...`) is a standing config change on the actual deployment machine, left for the user to run when ready — not yet loaded/verified live on any Mac. |
| 7 | Multi-person tracking never observed live with real people | **UNTESTED** — proven on a still image only |
| 8 | No deliberate real crossing test ever performed | **UNTESTED** — the counting formula is proven, a real walk-through is not |
| 9 | Sparsh camera (client's actual hardware) currently unreachable | **UNRESOLVED** as of 2026-09-12 — network-level failure (ARP incomplete), cause not yet diagnosed |
| 10 | No multi-hour continuous run has ever happened | **UNTESTED** |
| 11 | Never run on anything but this one MacBook Air M2 | **UNTESTED** on other hardware |

---

## 15. Current deployment status

**Not deployment-ready as of 2026-09-12.** Core logic (detection,
tracking, counting, occupancy, database, API, dashboard) is genuinely
solid — proven with 74 passing automated tests plus real hardware
verification (real webcam, real CP Plus RTSP DVR, two real bugs found
and fixed). What's unproven is everything that needs live human testing:
a controlled crossing test, multi-person live tracking, the actual
client camera hardware, and any long-duration run.

See `DEPLOYMENT_STATUS.md` for the full 12-phase checklist with a
computed readiness percentage — **treat that file, not this section, as
the numeric source of truth**, since it's re-verified more frequently
than prose summaries tend to be kept in sync.

---

## 16. Do NOT change (without a very good reason)

- **The confirmed-side-flip counting logic in `line_counter.py`.** It's
  small, subtle, and got the duplicate-prevention behavior exactly
  right through several rounds of testing. Don't refactor it without
  re-running all of `tests/test_line_counter.py` and
  `tests/test_integration_pipeline.py`.
- **One `PersonDetector` (YOLO model) per camera.** Never share a model
  instance across two camera threads — `persist=True` keeps ByteTrack's
  tracker state inside the model object itself; sharing it corrupts
  both cameras' tracking. (This was a real bug once, see `DECISIONS.md` D2.)
- **`prime_camera_permissions()` in `app/main.py`.** It looks unnecessary
  until you remove it and macOS's Camera permission prompt silently
  stops appearing (see `DECISIONS.md` D7).
- **`LatestFrameReader` wiring in `app/camera/manager.py`'s
  `_live_capture_factory`.** Don't revert to a bare `cv2.VideoCapture`
  for real cameras — that's the fixed 7-second RTSP staleness bug coming
  back. `app/camera/stream.py` itself is intentionally untouched by this
  fix (kept simple/testable) — the fix is injected only at the real
  camera construction point.
- **The `request.is_disconnected()` check in `_mjpeg_generator`
  (`app/api/routes.py`) and `timeout_graceful_shutdown=5` in `run.py`.**
  Removing either reintroduces the SIGTERM-hangs-forever bug.
- **`config.local.yaml` must stay gitignored.** Never commit real camera
  credentials into `config.yaml` (which is tracked).
- **The DB schema's lack of identity/biometric columns.** This is a
  privacy guarantee enforced by an automated test — don't add a name,
  face-embedding, or other identity column without a very deliberate,
  separate discussion.
- **`begin_fresh_session()` must be the only path that resets counts.**
  If you add another way to zero a counter, route it through this
  function (or replicate closing-old/opening-new session exactly) — a
  reset that doesn't close the DB session will be silently undone by the
  next restart's resume logic (see §7). This is non-obvious and easy to
  get wrong.
- **`.tab-panel[hidden] { display: none; }` in `style.css`.** Don't
  remove it, and if you add a new rule that sets `display` on
  `.tab-panel` (or any other `[hidden]` element), give it the same
  `[hidden]` override — otherwise a "hidden" panel silently stays
  visible, stacked under the active one (see §10 for the full story).

# Event Crowd Monitor — V1

Local AI crowd monitoring for two camera zones (event entrance, dining
entrance): YOLO person detection + ByteTrack multi-person tracking +
directional line-crossing counting + a live local dashboard. Runs
entirely on-device — no cloud, no face recognition, no biometric storage.

## 📌 Current status (2026-09-12) — read this, not just the section below

The section right after this one ("how this was built") is a **frozen
snapshot from 2026-09-02**, the day this project first ran on real
hardware. A lot has happened since — real RTSP/CCTV tested successfully,
two real bugs found and fixed on real hardware, Camera 2 turned on by
default, 74 automated tests (up from 50). **For the current, accurate
picture of what's working, what's verified, and what's still open, read
[`HANDOVER.md`](HANDOVER.md) and [`DEPLOYMENT_STATUS.md`](DEPLOYMENT_STATUS.md)
instead of trusting dates below.** This README is kept for setup
instructions (still accurate) and build history (now historical).

Headline corrections to the section below:
- **RTSP is no longer untested** — connected live to a real CP Plus DVR
  over RTSP on 2026-09-12 (see §8, rewritten).
- **Camera 2 (`dining_entrance`) is enabled by default now**, not
  disabled (see §7, rewritten).
- **Two real bugs were found on real hardware and fixed**: SIGTERM used
  to hang forever needing a force-kill (fixed), and RTSP frames could be
  up to 7 seconds stale, enough to miss a fast-moving person (fixed,
  reduced to ~2s). Both are in `DECISIONS.md` (D12) and `HANDOVER.md`.
- **50 tests → 74 tests.** `python3 -m unittest discover -s tests` still
  works exactly the same way.

## ⚠️ Historical: how this was built and what's been verified (as of 2026-09-02)

This project was built and code-tested inside a **sandboxed Linux
container with no camera, no macOS, no Apple Silicon, and no network
access** — I could not install `torch`/`ultralytics`/`fastapi` there,
so I could not run YOLO inference or a live server in that environment.

What I *did* verify for real, by writing and executing automated tests
against the actual code (not claims):

| Component | How it was tested | Result |
|---|---|---|
| Line-crossing counting algorithm (`app/vision/line_counter.py`) | 12 unit tests simulating tracked people moving across the line, hovering, reversing, multi-person scenarios | **12/12 pass** |
| Occupancy formula (`app/occupancy/manager.py`) | 7 unit tests incl. the "never below zero" clamp | **7/7 pass** |
| SQLite persistence (`app/database/database.py`) | 8 tests against a real temporary SQLite file, incl. a check that no biometric columns exist | **8/8 pass** |
| Camera reconnect/status state machine (`app/camera/stream.py`) | 7 unit tests against a fake capture backend (simulated failures) — **this caught and fixed a real bug** where status flipped to ONLINE before a frame was actually confirmed readable | **7/7 pass** |
| Frame annotation (`app/vision/draw.py`) | Rendered against a real synthetic OpenCV frame and checked pixel output | **Confirmed working** |
| Config loading (`app/config.py` + `config.yaml`) | Loaded the real config file and verified camera objects parse correctly | **Confirmed working** |
| YOLO/ByteTrack wrapper (`app/vision/detector.py`) — device selection & result parsing | 13 unit tests against **fake** `ultralytics`/`torch` modules shaped like the real API (fake tensors with `.cpu().numpy()`, fake `YOLO.track()` results) — verifies `PersonDetector` correctly turns YOLO output into `Detection` objects, handles "no tracks yet"/"no results", casts IDs to int, restricts to the person class, and raises a clear error on model-load failure | **13/13 pass — but this proves the *adapter code* is correct, NOT that real YOLO/ByteTrack/MPS actually work.** No real `ultralytics` or `torch` package has ever executed in this build; see the row below |
| Real YOLO inference, real ByteTrack, real MPS execution | **Now verified on a MacBook Air M2 (2026-09-02).** `PersonDetector` loaded `models/yolo11n.pt` on `device=MPS`, ran `.track()` on real images with people (Ultralytics' bundled `bus.jpg`/`zidane.jpg`), detected the people, and ByteTrack returned stable integer track IDs across repeated frames. First inference ~2.2 s (MPS warmup), then ~25–500 ms. `draw.py` rendered correctly over the real detections. | **PASS on real hardware** |
| Camera orchestration (`app/camera/manager.py`) — per-camera detector isolation | 3 regression tests using a fake detector factory — confirms each camera gets its OWN detector instance (a real bug: an earlier version shared one YOLO model across all camera threads, which would have corrupted ByteTrack's tracker state once Camera 2 was enabled) | **3/3 pass** |
| FastAPI app, routes, MJPEG streaming, dashboard | **Now runtime-tested on real hardware (2026-09-02).** `python run.py` boots with all expected startup log lines; `/api/status`, `/api/cameras`, `/api/occupancy`, `/api/events`, `POST /api/reset`, `POST /api/session/start` all return correct JSON; `/video/{id}` returns a `multipart/x-mixed-replace` stream and 404s on an unknown id; the dashboard renders in a browser, injects camera panels from polling, the OFFLINE panel/pill render correctly, and the Reset button round-trips (toast shown). No JS console errors. | **PASS on real hardware** (with camera OFFLINE — see next row) |
| Webcam capture + physical walk-through tests | **Blocked, not failed.** macOS did not grant Camera access to the host app in this environment, so `cv2.VideoCapture(0)` returns "not authorized". The app degrades exactly as designed (camera → RECONNECTING → OFFLINE, everything else keeps running). Needs to be run from **your** Terminal, where macOS can show the Camera permission prompt. | **MANUAL TEST REQUIRED — see §3 / §6** |
| Counting + occupancy + DB wiring end-to-end (not just the unit tests) | Drove the real `LineCounter` + `OccupancyManager` + real SQLite `Database` through all four §6 walk-through scenarios with synthetic per-frame positions matching what the detector emits. L→R ⇒ ENTRY, R→L ⇒ EXIT, jitter near the line ⇒ no count, two tracked people ⇒ counts and DB rows ×2. | **PASS on real hardware** |

Run `python3 -m unittest discover -s tests -v` yourself any time to see
all 50 of these tests pass on your machine too.

> **2026-09-02 update:** one test (`test_falls_back_to_cpu_when_torch_missing_entirely`)
> was rewritten. It previously assumed torch was absent from the host; on
> a real Mac where torch *is* installed it wrongly failed. It now forces
> `import torch` to raise via `sys.modules` patching, so it verifies the
> CPU-fallback branch on any machine. **50/50 pass on this MacBook Air M2.**

**Bottom line:** the hardest, most bug-prone logic — the counting
algorithm and the reconnect state machine — has been genuinely exercised
and a real bug was found and fixed. The parts that need YOLO, a webcam,
or macOS have not been run yet, because they can't be from where this
was built. Section "First run on your Mac" below is where that happens.

> **Recommendation:** for the actual on-device debug loop (installing
> deps, opening your webcam, watching for errors, fixing them live),
> this project will go faster in **Claude Code** (terminal, desktop, or
> IDE extension) running directly on your Mac, where Claude can execute
> commands, see camera output, and iterate in real time — rather than in
> this chat interface, which has no access to your machine.

---

## 1. Project structure

> **New to this project? Read [`HANDOVER.md`](HANDOVER.md) first** — it's
> the comprehensive, up-to-date architecture + troubleshooting +
> deployment guide. This README is the original quick-start doc; some of
> its historical sections (marked above) are frozen in time.

```
event_crowd_monitor/
├── app/
│   ├── main.py                # FastAPI app wiring
│   ├── config.py               # config.yaml loader
│   ├── camera/
│   │   ├── stream.py            # single camera: open/read/reconnect
│   │   ├── manager.py           # per-camera pipeline orchestration
│   │   └── frame_reader.py      # RTSP freshness fix (LatestFrameReader)
│   ├── vision/
│   │   ├── detector.py          # YOLO + ByteTrack wrapper
│   │   ├── line_counter.py      # directional crossing engine
│   │   └── draw.py              # bbox/line/stats overlay
│   ├── occupancy/
│   │   └── manager.py           # live_occupancy formula
│   ├── database/
│   │   └── database.py          # SQLite sessions + events
│   └── api/
│       └── routes.py            # /api/*, /video/*
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── tests/                      # unit tests (run without a camera)
├── models/                     # put yolo11n.pt here (auto-downloads)
├── data/                       # SQLite DB lives here
├── logs/                       # app.log lives here
├── config.yaml                 # camera zones, line position, etc.
├── requirements.txt
├── test_camera.py              # standalone webcam probe (run first)
├── run.py / run.sh
└── README.md (this file)
```

## 2. Setup on your Mac (MacBook Air M2)

```bash
cd event_crowd_monitor

python3 --version          # 3.9+ is fine — this project runs on 3.9.6 in practice

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

`torch` from PyPI ships with Apple Silicon MPS support built in — no
special index URL is needed. If `pip install -r requirements.txt` fails
on `lapx` (ByteTrack's assignment solver), try `pip install lap` instead
— either satisfies Ultralytics' tracker dependency.

The first time you run the app, Ultralytics will auto-download
`yolo11n.pt` (~6MB) into `models/` if it isn't already there.

## 3. macOS camera permission (do this before anything else)

The first time a Python process tries to open your webcam, macOS should
prompt you. If it doesn't, or you already denied it once:

1. Open **System Settings**
2. Go to **Privacy & Security → Camera**
3. Find your terminal app in the list (**Terminal**, **iTerm2**, or
   whichever app you're running Python from) and turn the toggle **on**
4. If the app isn't listed at all, run `python3 test_camera.py` once —
   macOS shows the permission prompt the first time `cv2.VideoCapture`
   actually attempts access
5. Re-run `python3 test_camera.py`

If you're running this from inside an IDE (VS Code, PyCharm) rather
than directly from Terminal, permission is usually needed for *that*
app in the same Camera settings pane, not just Terminal.

### macOS threading gotcha (fixed in `app/main.py`)

OpenCV's AVFoundation backend can only *request* camera authorization
from the process **main thread** — it needs the main run loop to show
the TCC prompt. Our camera pipelines run in worker threads, so the very
first `cv2.VideoCapture()` there used to fail with:

```
OpenCV: can not spin main run loop from other thread, set OPENCV_AVFOUNDATION_SKIP_AUTH=1 ...
```

and the permission prompt never appeared. `create_app()` now calls
`prime_camera_permissions()` on the main thread first: it briefly opens
each enabled local-webcam source so macOS resolves the authorization
state (and shows the prompt) *before* any worker thread touches the
camera. It's best-effort and never fatal.

If you still see that error after granting permission, run with
`OPENCV_AVFOUNDATION_SKIP_AUTH=1 python run.py` as a fallback.

## 4. Test the webcam BEFORE running the full app

```bash
python3 test_camera.py
```

Expected output:
```
Scanning camera indexes 0-3...

Camera 0: AVAILABLE  (1280x720)
Camera 1: NOT AVAILABLE
Camera 2: NOT AVAILABLE
Camera 3: NOT AVAILABLE

Using camera index 0 as CAMERA 1 (event_entrance).
Opening a live preview window — press 'q' to close it.
```

A window should open showing your live webcam feed. Press `q` to close it.

**MANUAL TEST REQUIRED** — I cannot run this from here; please run it
yourself and tell me what indexes came back AVAILABLE, and whether the
preview window showed your actual camera.

## 5. Run the full application

```bash
python run.py
# or: ./run.sh
```

Expected startup log lines (also written to `logs/app.log`):
```
Application starting
Database ready at data/crowd_monitor.db
Session started: id=1
Using device: MPS      <- or "Using device: CPU" if MPS isn't available
Model loaded
Camera pipelines started
```

Then open: **http://localhost:8000**

You should see the dashboard with an "Event Entrance" panel showing
your live webcam feed with the counting line, bounding boxes, and
tracking IDs drawn on it. **Both cameras are enabled by default** now
(`config.yaml`) — if you only have one webcam, "Dining Entrance" will
show "Camera offline" simply because `source: 1` doesn't exist on your
machine, not because it's turned off. See §7 to point it at a real
second camera or RTSP stream.

**MANUAL TEST REQUIRED** — please run this and confirm the dashboard
loads and the video feed appears. Send me the terminal output (or a
screenshot) if anything errors and I'll fix it.

## 6. Physical walk-through tests (do these with me watching the logs)

With the app running and the dashboard open:

1. **Stand on the LEFT side of frame**, then walk left → right across
   the middle of the frame.
   Expected: `ENTRY: 1`, `EXIT: 0`, `LIVE CROWD: 1`
2. **Walk back right → left.**
   Expected: `ENTRY: 1`, `EXIT: 1`, `LIVE CROWD: 0`
3. **Stand near the line without crossing** (jitter side to side within
   a few inches). Expected: no count changes — this exact scenario is
   covered by an automated test (`test_person_hovering_near_line_does_not_double_count`)
   but the real webcam / real YOLO detections need your confirmation too.
4. **Two-person test**: have a second person join you, both cross
   left → right together, then both cross back.
   Expected: `ENTRY` and `EXIT` each increase by ~2, with independent
   tracking IDs shown on each person in the video feed.

**MANUAL TEST REQUIRED** for all four — these need a real body in front
of a real webcam, which I cannot do. Please run them and report what
you saw (including anything that looked wrong, like a double-count or
a missed crossing) and I'll debug from there.

## 7. Camera 2 (dining entrance) — already enabled by default

`config.yaml` ships with **both** cameras `enabled: true`. If you only
have one physical webcam, `dining_entrance` (`source: 1`) will just show
"Camera offline" — that's expected, not a bug. To point it at a real
second camera:

```yaml
  - id: dining_entrance
    name: Dining Entrance
    source: 1              # another webcam index, or an RTSP URL (see §8)
    enabled: true
    line_position: 0.50
    line_buffer: 20
    entry_direction: left_to_right
    initial_occupancy: 0
```

No code changes needed — restart the app and it picks it up. Confirmed
working with two cameras running simultaneously with independent counts
(2026-09-11, real hardware).

## 8. RTSP / real CCTV — tested and working (2026-09-12)

**This has been proven against a real RTSP camera** (a CP Plus DVR),
not just implemented. Both channels connected, real YOLO detection ran
on the live feed, and counting worked end-to-end.

```yaml
  - id: dining_entrance
    name: Dining Entrance
    source: rtsp://admin:admin%40123@192.168.1.200:554/cam/realmonitor?channel=1&subtype=0
    enabled: true
    ...
```

The camera abstraction (`app/camera/stream.py`) treats any non-numeric
string `source` as an RTSP/URL source and passes it straight to
`cv2.VideoCapture`; the same reconnect logic applies.

**Three things to know that aren't obvious:**

1. **URL-encode special characters in the password.** An `@` in your
   password (e.g. `admin@123`) must become `%40` in the URL
   (`admin%40123`) — an RTSP URL uses `@` as its own separator, so a raw
   `@` in the password breaks parsing. In Python: `urllib.parse.quote(password, safe="")`.
2. **Never put real camera credentials in `config.yaml`** — it's tracked
   in git. Instead, create a `config.local.yaml` (already gitignored)
   with the real RTSP URL, and run with:
   ```bash
   CROWD_MONITOR_CONFIG=config.local.yaml python run.py
   ```
   `app/config.py` reads this env var to pick the config file.
3. **RTSP URL paths are brand-specific.** The format above
   (`/cam/realmonitor?channel=N&subtype=0`) is the common Dahua-style
   path used by CP Plus and many other Indian-market DVR/NVR brands.
   Others (Hikvision-style: `/Streaming/Channels/101`; ONVIF-generic
   brands like Sparsh) use different paths — if the connection fails,
   check the network is reachable first (`ping`/`arp`/a port check on
   554), then try alternate URL formats before assuming it's broken.

**Known real-hardware issue, already fixed:** `cv2.VideoCapture` buffers
RTSP frames internally, and if the pipeline reads slower than frames
arrive, `.read()` returns increasingly stale frames — measured up to
**7 seconds** of lag on a real stream, enough to miss a fast-moving
person entirely. Fixed in `app/camera/frame_reader.py`
(`LatestFrameReader`) — see `DECISIONS.md`. Reduced to ~2s (normal
network/decode latency, not a growing backlog) after the fix.

## 9. API reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/status` | GET | App status + all camera stats |
| `/api/cameras` | GET | Per-camera stats only |
| `/api/occupancy` | GET | Occupancy snapshot per camera |
| `/api/events` | GET | Recent crossing events (`?camera_id=&limit=`) |
| `/api/reset` | POST | Reset all counters (keeps camera config) |
| `/api/session/start` | POST | Start a new session, reset counters |
| `/video/{camera_id}` | GET | MJPEG live annotated feed |

Live updates use polling (1s for stats, 2s for the activity feed)
rather than WebSockets — a deliberate simplicity/reliability tradeoff
for V1; easy to upgrade to WebSocket push later if needed.

## 10. Testing checklist (spec section 23)

Status key: **PASS (real hw)** = actually executed on a MacBook Air M2 on
2026-09-02. **MANUAL** = still needs you + a real webcam (camera access
was not grantable in the automated environment).

> This table is a historical snapshot from 2026-09-02 (50 tests). The
> suite has since grown to **74 tests** (`python3 -m unittest discover -s tests`),
> and real webcam + real RTSP + two P0 hardware bugs have since been
> tested/fixed on real hardware. For the current, dated status of every
> item below, see `DEPLOYMENT_STATUS.md` and `HANDOVER.md` instead.

| # | Test | Status |
|---|---|---|
| 1 | Application starts | **PASS (real hw)** — boots with all expected log lines, uvicorn serves on :8000 |
| 2 | MPS detected | **PASS (real hw)** — `select_device()` → `mps`, model loads `on device mps`, `Using device: MPS` printed |
| 3 | Webcam opens | **MANUAL** — blocked by macOS Camera permission in the automated env; app degrades to OFFLINE as designed |
| 4 | Person detection works | **PASS (real hw)** on still images (bus.jpg/zidane.jpg → people detected); **MANUAL** for live webcam |
| 5 | Tracking ID appears | **PASS (real hw)** — real ByteTrack returned stable int IDs across frames; **MANUAL** for live webcam |
| 6 | Counting line appears | **PASS (real hw)** — `draw.py` rendered line + buffer + boxes + IDs over real YOLO output; **MANUAL** for the live feed |
| 7 | LEFT→RIGHT creates ENTRY | **Automated PASS** + **PASS (real hw)** via real LineCounter/occupancy/DB walk-through sim; **MANUAL** with real webcam |
| 8 | RIGHT→LEFT creates EXIT | **Automated PASS** + **PASS (real hw)** (same sim); **MANUAL** with real webcam |
| 9 | Same person doesn't repeatedly count | **Automated PASS** + **PASS (real hw)** (jitter-near-line sim → 0 counts); **MANUAL** with real webcam |
| 10 | Multiple people tracked independently | **Automated PASS** + **PASS (real hw)** (two-track sim → counts + DB rows ×2); **MANUAL** with real webcam |
| 11 | Occupancy formula correct | **Automated PASS** |
| 12 | Reset works | **Automated PASS** + **PASS (real hw)** — dashboard "Reset counts" button round-trips `POST /api/reset`, toast shown |
| 13 | Camera failure doesn't crash others | **Automated PASS** + **PASS (real hw)** — camera unavailable → RECONNECTING→OFFLINE, server + API + dashboard keep running |
| 14 | SQLite records events | **Automated PASS** + **PASS (real hw)** — walk-through sim wrote ENTRY/EXIT rows to a real DB file |
| 15 | Dashboard updates live | **PASS (real hw)** — panels injected from polling, status pill + stats update every 1s, no JS console errors; **MANUAL** to see live counts tick from a real crossing |

## 11. Known limitations (updated 2026-09-12 — see `HANDOVER.md` for the full list)

- Live updates use polling, not WebSockets (see section 9) — a
  deliberate V1 simplicity tradeoff.
- No auth on the dashboard/API — fine for local-network use, not for
  exposing beyond your LAN as-is.
- Occupancy is derived live from events, not persisted — a restart
  starts a fresh count rather than replaying history (open decision,
  see `DECISIONS.md` D11).
- The RTSP URL (including the camera password) is currently written to
  `logs/app.log` in plain text when a camera connects — don't share
  that log file. Not yet masked.
- No automatic startup on boot and no crash-supervisor — the app must
  be started manually and isn't auto-restarted if it crashes.
- Multi-person tracking is proven on a still image (automated test) but
  has not yet been observed with 2+ real people crossing together live.
- No run has exceeded roughly tens of minutes continuously — multi-hour
  stability is unverified.
- Only ever run on a MacBook Air M2 — untested on other hardware
  (e.g. a Mac mini) if that's the real deployment target.

## 12. Security / privacy (spec section 29)

No face recognition, no face embeddings, no biometric data, no
identity resolution — verified by an automated test asserting the
SQLite schema contains no such columns. ByteTrack IDs are ephemeral
integers with no meaning beyond the current process.

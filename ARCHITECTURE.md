# ARCHITECTURE — Event Crowd Monitor

_Kept in sync with the actual code. Last verified against source: 2026-09-07._

Local, on-device crowd monitoring for camera "zones" (event entrance, dining
entrance): YOLO person detection → ByteTrack multi-object tracking →
directional line-crossing count → live occupancy → SQLite log → FastAPI
dashboard. No cloud, no face recognition, no biometric storage.

## Runtime topology

```
                 ┌──────────────────────── FastAPI app (app/main.py) ───────────────────────┐
                 │  create_app():                                                           │
                 │   load_config → setup_logging → Database → start_session                 │
                 │   → PersonDetector startup check → prime_camera_permissions (main thread)│
                 │   → CameraManager.start_all()                                            │
                 │   routes: app/api/routes.py   static+dashboard: frontend/                │
                 └───────────────┬─────────────────────────────────────────┬───────────────┘
                                 │                                         │
                    per-camera thread (daemon)                   HTTP (uvicorn, :8000)
                                 │                                         │
   CameraStream.read() ──► cv2.resize ──► PersonDetector.track() ──► LineCounter.update()
   (app/camera/stream.py)                 (app/vision/detector.py)   (app/vision/line_counter.py)
        reconnect/status FSM               YOLO11n + ByteTrack             │ CrossingEvent[]
                                           device = MPS|CPU                ▼
                                                              OccupancyManager (app/occupancy/manager.py)
                                                                           │
                                                              Database.record_event (app/database/database.py)
                                           draw_frame() ──► cv2.imencode(.jpg) ──► CameraPipeline._latest_jpeg
                                           (app/vision/draw.py)                        │
                                                                        GET /video/{id} MJPEG generator
```

## Modules (source of truth = the files)

| File | Responsibility | Key symbols |
|---|---|---|
| `app/config.py` | Load `config.yaml` → typed objects; normalize `source`, validate direction & line position | `CameraConfig`, `AppConfig`, `load_config()` |
| `app/main.py` | Wire everything; FastAPI app factory; **main-thread camera permission prime**; shutdown hook | `create_app()`, `prime_camera_permissions()`, `setup_logging()` |
| `app/camera/stream.py` | One capture device (webcam index or RTSP URL); ONLINE/OFFLINE/RECONNECTING FSM; never raises to caller; ONLINE only after a real frame read | `CameraStream`, `CameraStatus` |
| `app/camera/manager.py` | One pipeline thread per camera; per-camera detector instance; FPS calc; latest-JPEG buffer; stats | `CameraManager`, `CameraPipeline`, `CameraRuntimeStats` |
| `app/vision/detector.py` | YOLO load + `.track(persist=True, classes=[0], tracker='bytetrack.yaml')`; parse boxes→`Detection`; device select | `PersonDetector`, `Detection`, `select_device()`, `PERSON_CLASS_ID=0` |
| `app/vision/line_counter.py` | Bucket each track LEFT/BUFFER/RIGHT by bbox bottom-center; fire ENTRY/EXIT only on confirmed side flip; expire stale tracks | `LineCounter`, `Zone`, `EventType`, `TrackState`, `CrossingEvent` |
| `app/occupancy/manager.py` | `live = max(0, initial + entries − exits)` | `OccupancyManager`, `OccupancySnapshot` |
| `app/database/database.py` | Thread-safe SQLite; `sessions` + `crossing_events` only; CHECK constraint on event_type; **no biometric columns** | `Database`, `SessionRecord`, `EventRecord` |
| `app/api/routes.py` | REST + MJPEG; polling model (no WebSocket) | `/api/status`, `/api/cameras`, `/api/occupancy`, `/api/events`, `/api/reset`, `/api/session/start`, `/video/{camera_id}` |
| `frontend/index.html`,`app.js`,`style.css` | Dashboard; polls `/api/status` (1s) and `/api/events` (2s); MJPEG `<img>` per camera; Reset / New-session buttons | — |
| `run.py` | `uvicorn.run(create_app(), host, port)` | — |

## Data model (SQLite, `data/crowd_monitor.db`)

```
sessions(        id PK, started_at REAL, ended_at REAL NULL, notes TEXT NULL)
crossing_events( id PK, session_id FK, timestamp REAL, camera_id TEXT,
                 track_id INTEGER, event_type TEXT CHECK IN ('ENTRY','EXIT'))
index idx_events_session(session_id), idx_events_camera(camera_id)
```
`track_id` = ephemeral ByteTrack integer, process-lifetime only. No faces,
embeddings, or identity data anywhere (asserted by `test_database.py`).

## Counting algorithm (the load-bearing logic)

- Vertical line at `line_position × frame_width`; dead-zone `± line_buffer` px.
- Per track, remember the last **confirmed side** (LEFT or RIGHT, never BUFFER).
- Entering/leaving BUFFER never fires an event and never changes confirmed side.
- Event fires only when confirmed side flips. `entry_direction` maps L→R / R→L
  onto ENTRY / EXIT. Tracks unseen for `track_expiry_seconds` are dropped.

## Concurrency

- One daemon thread per enabled camera (`CameraPipeline._run`), each with its
  **own** `PersonDetector` (ByteTrack state lives in the model object; sharing
  would cross-contaminate track IDs).
- `Database` guards a single `sqlite3` connection (`check_same_thread=False`)
  with one `threading.Lock`.
- `CameraPipeline._latest_jpeg` guarded by a per-pipeline lock; the MJPEG route
  reads it every ~50 ms.
- Any exception in a pipeline is caught + logged; one camera cannot crash another
  or the server.

## Platform notes

- Device: `select_device()` → `"mps"` if `torch.backends.mps.is_available()`
  else `"cpu"`. Never CUDA.
- macOS: OpenCV/AVFoundation can only request Camera authorization on the
  process main thread, so `create_app()` calls `prime_camera_permissions()`
  (main-thread open of each enabled webcam) before starting camera threads.
- `config.yaml` drives everything; string sources that are all digits are
  coerced to int webcam indices, otherwise treated as RTSP/URL.

## Known gaps (as of 2026-09-08 — see DEPLOYMENT_STATUS.md / DECISIONS.md)

- **Occupancy is derived-only, not persisted.** No occupancy table; on restart
  it recomputes from `initial_occupancy` for a new session and does not replay
  prior `crossing_events`. (DECISIONS D11 — open.)
- **Shutdown hook doesn't run on SIGTERM.** `@app.on_event("shutdown")` (→
  `stop_all()`, `end_session()`) is skipped when `run.py` gets SIGTERM; sessions
  stay `ended_at=NULL`. Fix = migrate to a `lifespan` handler. (DECISIONS D12.)
- **No dedicated `/health`.** `/api/status` doubles as the liveness check.
- **Dashboard shows per-camera occupancy only** — no combined cross-camera total.
- **No auto-start / supervisor / DB backup** — deployment infra not built.

## Not implemented (by design, V1)

WebSocket push (polling instead) · dashboard/API auth · multi-host ·
Camera 2 & RTSP are configured-but-unverified paths.

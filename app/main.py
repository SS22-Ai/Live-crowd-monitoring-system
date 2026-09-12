"""
Application entrypoint. Wires together config, the YOLO detector, the
per-camera pipelines, the database, and the FastAPI app + dashboard.

Run via `python run.py` (see repo root), which just calls this module's
`create_app()` and starts uvicorn.
"""
from __future__ import annotations

import logging
import os
import sys

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.routes import router as api_router  # noqa: E402
from app.camera.manager import CameraManager  # noqa: E402
from app.config import load_config  # noqa: E402
from app.database.database import Database  # noqa: E402
from app.vision.detector import PersonDetector  # noqa: E402

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


def is_uncached_frontend_path(path: str) -> bool:
    """True for the dashboard's own HTML/JS/CSS ("/" and "/static/*"), which
    should never be browser-cached since they're edited in place with no
    build step. False for everything else (in particular /api/* and
    /video/*, which must not get a blanket no-store)."""
    return path == "/" or path.startswith("/static/")


def resolve_startup_session(db) -> tuple[int, bool]:
    """Decide whether to resume the previous session or start a fresh one.

    Data must survive ANY restart -- a clean stop, a crash, closing the
    terminal, anything -- and only go back to zero when the user explicitly
    clicks "Reset counts" or "Start new session" (see begin_fresh_session()
    in app/api/routes.py, which is the only thing that actually closes a
    session). So: if any session exists at all, resume it and replay its
    counts, regardless of whether on_shutdown() got to run last time
    (ended_at is now purely informational -- "when did the process last
    stop", not a signal to start over). Only the very first run, with no
    sessions in the database yet, starts a new one.

    Returns (session_id, resumed).
    """
    latest = db.latest_session()
    if latest is not None:
        return latest.id, True
    return db.start_session(), False


def setup_logging(log_path: str):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)],
    )


def prime_camera_permissions(camera_configs, logger):
    """macOS/OpenCV quirk: the AVFoundation backend can only *request*
    camera authorization from the process main thread — it needs the main
    run loop to present the TCC prompt. Our camera pipelines each run in a
    worker thread, so the very first `cv2.VideoCapture()` there fails with
    "can not spin main run loop from other thread" and the permission
    prompt never appears.

    Fix: on macOS, briefly open each enabled local-webcam source here on
    the main thread (create_app runs on the main thread) so the TCC prompt
    is shown / the authorization state is resolved *before* any worker
    thread touches the camera. Best-effort and never fatal — a real
    failure still degrades to OFFLINE via the normal reconnect path.
    """
    if sys.platform != "darwin":
        return
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return
    for cfg in camera_configs:
        if not getattr(cfg, "enabled", False):
            continue
        if not isinstance(cfg.source, int):
            continue  # RTSP/URL sources don't go through the TCC camera prompt
        try:
            cap = cv2.VideoCapture(cfg.source)
            ok = bool(cap and cap.isOpened())
            frame_ok = False
            if ok:
                for _ in range(5):
                    ret, _frame = cap.read()
                    if ret and _frame is not None:
                        frame_ok = True
                        break
            if cap is not None:
                cap.release()
            if frame_ok:
                logger.info(
                    "Camera permission primed on main thread for source %s", cfg.source
                )
            else:
                logger.warning(
                    "Main-thread camera prime for source %s could not read a frame. "
                    "If macOS did not show a Camera prompt, grant Camera access to "
                    "this app in System Settings > Privacy & Security > Camera, then "
                    "restart.",
                    cfg.source,
                )
        except Exception as exc:  # noqa: BLE001 - never fatal
            logger.warning("Main-thread camera prime for source %s errored: %s", cfg.source, exc)


def create_app() -> FastAPI:
    cfg = load_config()
    setup_logging(cfg.log_path)
    logger = logging.getLogger("crowd_monitor.main")
    logger.info("Application starting")

    os.makedirs(os.path.dirname(cfg.db_path), exist_ok=True)
    db = Database(cfg.db_path)
    logger.info("Database ready at %s", cfg.db_path)

    session_id, resumed = resolve_startup_session(db)
    session_state = {"session_id": session_id}
    if resumed:
        logger.info(
            "Resuming session id=%s from a previous run — camera counts will be "
            "replayed from its recorded events. Use Reset counts / Start new "
            "session on the dashboard to start over.",
            session_id,
        )
    else:
        logger.info("Session started: id=%s", session_state["session_id"])

    if not os.path.exists(cfg.model_path):
        logger.warning(
            "Model file not found at %s. Ultralytics will attempt to auto-download "
            "yolo11n.pt on first use if this is a bare model name.",
            cfg.model_path,
        )

    try:
        # Load once up front to fail fast if the model/device is broken,
        # before spinning up camera threads. Each camera pipeline gets
        # its OWN detector instance (see CameraManager) — this first
        # load is just a startup sanity check.
        PersonDetector(model_path=cfg.model_path, confidence=cfg.model_confidence)
        logger.info("Model loaded (startup check)")
    except Exception as exc:
        logger.error("FATAL: could not load YOLO model: %s", exc)
        raise

    def detector_factory():
        return PersonDetector(model_path=cfg.model_path, confidence=cfg.model_confidence)

    prime_camera_permissions(cfg.cameras, logger)

    manager = CameraManager(
        camera_configs=cfg.cameras,
        detector_factory=detector_factory,
        db=db,
        session_id_getter=lambda: session_state.get("session_id"),
        inference_width=cfg.inference_width,
        inference_height=cfg.inference_height,
        frame_skip=cfg.frame_skip,
        resume_session_id=session_id if resumed else None,
    )
    manager.start_all()
    logger.info("Camera pipelines started")

    app = FastAPI(title="Event Crowd Monitor")
    app.state.config = cfg
    app.state.db = db
    app.state.camera_manager = manager
    app.state.session_state = session_state

    app.include_router(api_router)

    @app.get("/")
    def dashboard():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.middleware("http")
    async def no_cache_frontend(request, call_next):
        response = await call_next(request)
        if is_uncached_frontend_path(request.url.path):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.on_event("shutdown")
    def on_shutdown():
        logger.info("Application stopping")
        manager.stop_all()
        db.end_session(session_state["session_id"])
        db.close()
        logger.info("Application stopped")

    return app

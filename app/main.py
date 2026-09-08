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

    session_state = {"session_id": db.start_session()}
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

    @app.on_event("shutdown")
    def on_shutdown():
        logger.info("Application stopping")
        manager.stop_all()
        db.end_session(session_state["session_id"])
        db.close()
        logger.info("Application stopped")

    return app

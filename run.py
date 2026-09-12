#!/usr/bin/env python3
"""
Start the Event Crowd Monitor.

Usage:
    python run.py
"""
import uvicorn

from app.config import load_config
from app.main import create_app

app = create_app()

if __name__ == "__main__":
    cfg = load_config()
    uvicorn.run(
        app,
        host=cfg.host,
        port=cfg.port,
        log_level="info",
        # An open MJPEG stream (/video/{camera_id}) is a long-lived request
        # that never completes on its own. Without a bound, uvicorn's graceful
        # shutdown waits *forever* for it on SIGTERM, so the process never
        # exits and the app-level shutdown hook (which ends the DB session
        # and releases the cameras) never runs. This forces any lingering
        # connection closed after 5s so shutdown always completes.
        timeout_graceful_shutdown=5,
    )

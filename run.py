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
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")

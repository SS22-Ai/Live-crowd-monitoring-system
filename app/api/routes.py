"""
API routes (spec section 16/17). Lightweight polling is used for live
dashboard updates (simple + reliable) rather than WebSockets, per the
"otherwise use lightweight polling" fallback in the spec — this keeps
the first working version robust before adding WebSocket push later.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter()


def _manager(request: Request):
    return request.app.state.camera_manager


def _db(request: Request):
    return request.app.state.db


def _session_state(request: Request):
    return request.app.state.session_state


@router.get("/api/status")
def get_status(request: Request):
    manager = _manager(request)
    return {
        "app": "event_crowd_monitor",
        "status": "running",
        "time": time.time(),
        "cameras": [asdict(s) for s in manager.all_stats()],
    }


@router.get("/api/cameras")
def get_cameras(request: Request):
    manager = _manager(request)
    return {"cameras": [asdict(s) for s in manager.all_stats()]}


@router.get("/api/occupancy")
def get_occupancy(request: Request):
    manager = _manager(request)
    result = {}
    for cam_id, pipeline in manager.pipelines.items():
        snap = pipeline.occupancy.snapshot()
        result[cam_id] = asdict(snap)
    return result


@router.get("/api/events")
def get_events(request: Request, camera_id: Optional[str] = None, limit: int = 100):
    db = _db(request)
    session_state = _session_state(request)
    events = db.get_events(session_id=session_state.get("session_id"), camera_id=camera_id, limit=limit)
    return {"events": [asdict(e) for e in events]}


@router.post("/api/reset")
def reset_counts(request: Request):
    manager = _manager(request)
    manager.reset_all()
    return {"ok": True, "message": "Counters reset for all cameras"}


@router.post("/api/session/start")
def start_session(request: Request):
    db = _db(request)
    session_state = _session_state(request)
    session_id = db.start_session()
    session_state["session_id"] = session_id
    manager = _manager(request)
    manager.reset_all()
    return {"ok": True, "session_id": session_id}


async def _mjpeg_generator(pipeline, request: Request):
    """Yields one MJPEG frame at a time. Exits as soon as the client
    disconnects, instead of looping forever — an MJPEG stream is a
    long-lived request, and one that never notices the client is gone
    keeps its connection "in flight" forever, which makes uvicorn's
    graceful shutdown (which waits for in-flight requests to finish
    before it will invoke the app's shutdown hook) hang indefinitely.
    See run.py's timeout_graceful_shutdown for the bound that catches the
    remaining case (client still connected when the server is stopped)."""
    boundary = b"--frame"
    while not await request.is_disconnected():
        jpeg = pipeline.latest_jpeg()
        if jpeg is not None:
            yield (
                boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
            )
        await asyncio.sleep(0.05)


@router.get("/video/{camera_id}")
async def video_feed(camera_id: str, request: Request):
    manager = _manager(request)
    pipeline = manager.get(camera_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Unknown camera_id '{camera_id}'")
    return StreamingResponse(
        _mjpeg_generator(pipeline, request),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )

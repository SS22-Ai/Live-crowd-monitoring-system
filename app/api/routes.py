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


MAX_REPORT_BUCKETS = 1000  # safety cap: bounds response size / processing time
                           # for a pathologically small interval over a long session


def bucket_events_by_interval(events, session_started_at, now, interval_minutes, initial_occupancy):
    """Pure bucketing logic behind /api/reports/interval — no DB/HTTP
    involved, so it's directly unit-testable.

    `events`: iterable of objects/dicts with .timestamp/["timestamp"] and
    .event_type/["event_type"] ('ENTRY' or 'EXIT'), any order.
    Returns a list of {start, end, entries, exits, occupancy_at_end} dicts
    covering [session_started_at, now) in interval_minutes-wide windows.
    occupancy_at_end is the running total through the end of that window,
    using the same max(0, initial + entries - exits) formula as live
    occupancy (app/occupancy/manager.py) — this is a historical
    reconstruction from stored events, not a new stored value.
    """
    interval_minutes = max(1, interval_minutes)
    interval_seconds = interval_minutes * 60

    def ts(e):
        return e["timestamp"] if isinstance(e, dict) else e.timestamp

    def etype(e):
        return e["event_type"] if isinstance(e, dict) else e.event_type

    events_sorted = sorted(events, key=ts)

    bucket_starts = []
    t = session_started_at
    while t < now and len(bucket_starts) < MAX_REPORT_BUCKETS:
        bucket_starts.append(t)
        t += interval_seconds
    if not bucket_starts:
        bucket_starts = [session_started_at]

    buckets = []
    cum_entries = 0
    cum_exits = 0
    idx = 0
    n = len(events_sorted)
    for b_start in bucket_starts:
        b_end = b_start + interval_seconds
        bucket_entries = 0
        bucket_exits = 0
        while idx < n and ts(events_sorted[idx]) < b_end:
            if etype(events_sorted[idx]) == "ENTRY":
                bucket_entries += 1
                cum_entries += 1
            else:
                bucket_exits += 1
                cum_exits += 1
            idx += 1
        buckets.append({
            "start": b_start,
            "end": b_end,
            "entries": bucket_entries,
            "exits": bucket_exits,
            "occupancy_at_end": max(0, initial_occupancy + cum_entries - cum_exits),
        })
    return buckets


@router.get("/api/reports/interval")
def get_interval_report(request: Request, interval_minutes: int = 30):
    db = _db(request)
    session_state = _session_state(request)
    manager = _manager(request)
    session_id = session_state.get("session_id")

    session = db.get_session(session_id) if session_id is not None else None
    if session is None:
        return {"interval_minutes": interval_minutes, "session_id": session_id, "cameras": {}}

    now = time.time()
    cameras = {}
    for camera_id, pipeline in manager.pipelines.items():
        events = db.get_events(session_id=session_id, camera_id=camera_id, limit=100000)
        buckets = bucket_events_by_interval(
            events, session.started_at, now, interval_minutes, pipeline.cfg.initial_occupancy
        )
        cameras[camera_id] = {"name": pipeline.cfg.name, "buckets": buckets}

    return {
        "interval_minutes": max(1, interval_minutes),
        "session_id": session_id,
        "session_started_at": session.started_at,
        "generated_at": now,
        "cameras": cameras,
    }


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

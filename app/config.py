"""
Configuration loader for the event crowd monitor.

Reads config.yaml and exposes strongly-typed CameraConfig objects.
Nothing here is hard-coded — every camera's source, line position,
buffer, and direction comes from config.yaml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Union

import yaml

CONFIG_PATH = os.environ.get(
    "CROWD_MONITOR_CONFIG",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"),
)


@dataclass
class CameraConfig:
    id: str
    name: str
    source: Union[int, str]  # webcam index (int) or RTSP URL (str)
    enabled: bool = True
    line_position: float = 0.50       # fraction of frame width, 0.0-1.0
    line_buffer: int = 20             # dead-zone in pixels around the line
    entry_direction: str = "left_to_right"  # "left_to_right" or "right_to_left"
    initial_occupancy: int = 0
    reconnect_interval_seconds: float = 3.0
    track_expiry_seconds: float = 2.0  # forget a track if unseen this long

    def __post_init__(self):
        # Normalize source: numeric strings from YAML ("0") should behave as
        # webcam indices, not string RTSP-like sources.
        if isinstance(self.source, str) and self.source.strip().lstrip("-").isdigit():
            self.source = int(self.source)
        if self.entry_direction not in ("left_to_right", "right_to_left"):
            raise ValueError(
                f"camera '{self.id}': entry_direction must be 'left_to_right' or "
                f"'right_to_left', got {self.entry_direction!r}"
            )
        if not (0.0 < self.line_position < 1.0):
            raise ValueError(f"camera '{self.id}': line_position must be between 0 and 1")


@dataclass
class AppConfig:
    cameras: List[CameraConfig] = field(default_factory=list)
    model_path: str = "models/yolo11n.pt"
    model_confidence: float = 0.4
    inference_width: int = 640
    inference_height: int = 480
    target_fps: int = 15
    frame_skip: int = 0  # process every Nth frame (0 = process every frame)
    db_path: str = "data/crowd_monitor.db"
    log_path: str = "logs/app.log"
    host: str = "0.0.0.0"
    port: int = 8000
    # A camera that was previously ONLINE and has been stuck OFFLINE/
    # RECONNECTING for this many seconds triggers a full process restart
    # (see app/main.py's watchdog and CameraPipeline.seconds_stuck_offline)
    # -- works around a real macOS/OpenCV limitation where a USB camera
    # lost mid-session can't be reopened in-process. 0 disables it.
    stuck_camera_restart_seconds: int = 60

    def camera_by_id(self, camera_id: str) -> CameraConfig:
        for cam in self.cameras:
            if cam.id == camera_id:
                return cam
        raise KeyError(f"No camera with id {camera_id!r} in config")


def load_config(path: str = CONFIG_PATH) -> AppConfig:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found at {path}. Copy config.yaml.example or create one."
        )
    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    cameras = [CameraConfig(**c) for c in raw.get("cameras", [])]
    app_section = raw.get("app", {})

    return AppConfig(
        cameras=cameras,
        model_path=app_section.get("model_path", "models/yolo11n.pt"),
        model_confidence=app_section.get("model_confidence", 0.4),
        inference_width=app_section.get("inference_width", 640),
        inference_height=app_section.get("inference_height", 480),
        target_fps=app_section.get("target_fps", 15),
        frame_skip=app_section.get("frame_skip", 0),
        db_path=app_section.get("db_path", "data/crowd_monitor.db"),
        log_path=app_section.get("log_path", "logs/app.log"),
        host=app_section.get("host", "0.0.0.0"),
        port=app_section.get("port", 8000),
        stuck_camera_restart_seconds=app_section.get("stuck_camera_restart_seconds", 60),
    )

"""
Drawing helpers for the annotated video feed: counting line + buffer zone,
bounding boxes, track IDs, and a small stats overlay (spec section 10/12).
"""
from __future__ import annotations

from typing import List

import cv2
import numpy as np

from app.vision.detector import Detection

COLOR_LINE = (0, 255, 255)      # yellow
COLOR_BUFFER = (0, 165, 255)    # orange, semi-transparent
COLOR_BOX = (0, 220, 0)         # green
COLOR_TEXT = (255, 255, 255)    # white
COLOR_TEXT_BG = (0, 0, 0)


def draw_frame(
    frame: np.ndarray,
    detections: List[Detection],
    line_x: int,
    line_buffer: int,
    camera_name: str,
    entries: int,
    exits: int,
    live_occupancy: int,
    status: str,
) -> np.ndarray:
    h, w = frame.shape[:2]

    # Buffer zone (semi-transparent)
    overlay = frame.copy()
    cv2.rectangle(overlay, (line_x - line_buffer, 0), (line_x + line_buffer, h), COLOR_BUFFER, -1)
    frame = cv2.addWeighted(overlay, 0.15, frame, 0.85, 0)

    # Counting line
    cv2.line(frame, (line_x, 0), (line_x, h), COLOR_LINE, 2)

    # Bounding boxes + IDs
    for det in detections:
        p1 = (int(det.x1), int(det.y1))
        p2 = (int(det.x2), int(det.y2))
        cv2.rectangle(frame, p1, p2, COLOR_BOX, 2)
        bc = det.bottom_center
        cv2.circle(frame, (int(bc[0]), int(bc[1])), 4, (0, 0, 255), -1)
        label = f"ID {det.track_id}"
        cv2.putText(frame, label, (p1[0], max(0, p1[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_BOX, 2)

    # Stats overlay
    lines = [
        camera_name.upper(),
        f"ENTRY: {entries}   EXIT: {exits}",
        f"LIVE CROWD: {live_occupancy}",
        f"CAMERA: {status}",
    ]
    y0 = 24
    for i, text in enumerate(lines):
        y = y0 + i * 26
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
        cv2.rectangle(frame, (8, y - th - 6), (12 + tw, y + 6), COLOR_TEXT_BG, -1)
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, COLOR_TEXT, 2)

    return frame

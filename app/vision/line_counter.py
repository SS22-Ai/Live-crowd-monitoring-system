"""
Directional line-crossing engine.

Design (per spec section 4 & 26):
  - Each camera has a vertical line at `line_position` (fraction of width)
    with a `line_buffer` (pixels) dead zone around it.
  - Every tracked person is bucketed into LEFT / BUFFER / RIGHT each frame
    using the bottom-center point of their bounding box.
  - We maintain, per track_id, the last CONFIRMED side (LEFT or RIGHT).
    Entering/leaving the BUFFER does not change the confirmed side and
    does NOT fire an event by itself — this prevents a person standing
    near the line from generating repeated events.
  - An event fires ONLY when the confirmed side actually flips
    (LEFT -> RIGHT or RIGHT -> LEFT). Exactly one event per genuine
    crossing. The track must legitimately cross back to count again.
  - Tracks not seen for `track_expiry_seconds` are forgotten so IDs
    don't leak memory or cause stale events if ByteTrack reassigns them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Zone(Enum):
    LEFT = "LEFT"
    BUFFER = "BUFFER"
    RIGHT = "RIGHT"


class EventType(Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


@dataclass
class TrackState:
    track_id: int
    confirmed_side: Optional[Zone] = None   # LEFT or RIGHT only, never BUFFER
    current_zone: Optional[Zone] = None
    last_seen: float = field(default_factory=time.time)
    last_position: Optional[Tuple[float, float]] = None
    crossing_count: int = 0


@dataclass
class CrossingEvent:
    track_id: int
    event_type: EventType
    timestamp: float
    position: Tuple[float, float]


class LineCounter:
    """
    One LineCounter instance per camera. Feed it detections every frame via
    `update()`; it returns any crossing events generated this frame.
    """

    def __init__(
        self,
        frame_width: int,
        line_position: float,
        line_buffer: int,
        entry_direction: str = "left_to_right",
        track_expiry_seconds: float = 2.0,
    ):
        if frame_width <= 0:
            raise ValueError("frame_width must be positive")
        self.frame_width = frame_width
        self.line_position = line_position
        self.line_buffer = max(0, line_buffer)
        self.entry_direction = entry_direction
        self.track_expiry_seconds = track_expiry_seconds
        self.line_x = frame_width * line_position

        self.tracks: Dict[int, TrackState] = {}
        self.entries = 0
        self.exits = 0

    def set_frame_width(self, frame_width: int):
        """Recompute line_x if the actual capture resolution differs from config."""
        self.frame_width = frame_width
        self.line_x = frame_width * self.line_position

    def _zone_for_x(self, x: float) -> Zone:
        left_edge = self.line_x - self.line_buffer
        right_edge = self.line_x + self.line_buffer
        if x < left_edge:
            return Zone.LEFT
        if x > right_edge:
            return Zone.RIGHT
        return Zone.BUFFER

    def _direction_to_event(self, from_side: Zone, to_side: Zone) -> Optional[EventType]:
        if from_side == to_side:
            return None
        crossed_l2r = from_side == Zone.LEFT and to_side == Zone.RIGHT
        crossed_r2l = from_side == Zone.RIGHT and to_side == Zone.LEFT
        if not (crossed_l2r or crossed_r2l):
            return None
        if self.entry_direction == "left_to_right":
            return EventType.ENTRY if crossed_l2r else EventType.EXIT
        else:
            return EventType.ENTRY if crossed_r2l else EventType.EXIT

    def update(
        self, detections: List[Tuple[int, float, float]], now: Optional[float] = None
    ) -> List[CrossingEvent]:
        """
        detections: list of (track_id, bottom_center_x, bottom_center_y)
        Returns: list of CrossingEvent generated this frame.
        """
        now = now if now is not None else time.time()
        events: List[CrossingEvent] = []
        seen_ids = set()

        for track_id, x, y in detections:
            seen_ids.add(track_id)
            zone = self._zone_for_x(x)
            state = self.tracks.get(track_id)

            if state is None:
                # First time we've seen this track. Only set a confirmed
                # side if it's unambiguously on one side; if it first
                # appears inside the buffer we wait for a real side.
                confirmed = zone if zone != Zone.BUFFER else None
                state = TrackState(
                    track_id=track_id,
                    confirmed_side=confirmed,
                    current_zone=zone,
                    last_seen=now,
                    last_position=(x, y),
                )
                self.tracks[track_id] = state
                continue

            state.current_zone = zone
            state.last_seen = now
            state.last_position = (x, y)

            if zone == Zone.BUFFER:
                # Just passing through — no event, confirmed_side unchanged.
                continue

            if state.confirmed_side is None:
                # First time this track resolves to a definite side.
                state.confirmed_side = zone
                continue

            if zone != state.confirmed_side:
                event_type = self._direction_to_event(state.confirmed_side, zone)
                state.confirmed_side = zone
                if event_type is not None:
                    state.crossing_count += 1
                    events.append(CrossingEvent(track_id, event_type, now, (x, y)))
                    if event_type == EventType.ENTRY:
                        self.entries += 1
                    else:
                        self.exits += 1
            # else: same side as before -> no event

        self._expire_stale_tracks(now, seen_ids)
        return events

    def _expire_stale_tracks(self, now: float, seen_ids: set):
        stale = [
            tid
            for tid, st in self.tracks.items()
            if tid not in seen_ids and (now - st.last_seen) > self.track_expiry_seconds
        ]
        for tid in stale:
            del self.tracks[tid]

    def reset_counts(self):
        self.entries = 0
        self.exits = 0
        self.tracks.clear()

    def active_track_count(self) -> int:
        return len(self.tracks)

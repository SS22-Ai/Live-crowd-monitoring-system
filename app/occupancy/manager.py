"""
Occupancy manager: live_occupancy = initial_occupancy + entries - exits,
clamped so it never goes below zero (spec section 2).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OccupancySnapshot:
    camera_id: str
    initial_occupancy: int
    entries: int
    exits: int
    live_occupancy: int


class OccupancyManager:
    def __init__(self, camera_id: str, initial_occupancy: int = 0):
        self.camera_id = camera_id
        self.initial_occupancy = max(0, initial_occupancy)
        self.entries = 0
        self.exits = 0

    def record_entry(self):
        self.entries += 1

    def record_exit(self):
        self.exits += 1

    @property
    def live_occupancy(self) -> int:
        raw = self.initial_occupancy + self.entries - self.exits
        return max(0, raw)

    def snapshot(self) -> OccupancySnapshot:
        return OccupancySnapshot(
            camera_id=self.camera_id,
            initial_occupancy=self.initial_occupancy,
            entries=self.entries,
            exits=self.exits,
            live_occupancy=self.live_occupancy,
        )

    def reset(self, initial_occupancy: int = 0):
        self.initial_occupancy = max(0, initial_occupancy)
        self.entries = 0
        self.exits = 0

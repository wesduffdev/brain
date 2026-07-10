"""Simulation — the deep module that wires the pieces into one being and steps
it through time.

This is the public surface for the whole engine core: construct it from a
ConfigService, call `tick()` to advance one step, read `state()` for a
snapshot. Callers (a demo today, an API loop tomorrow) never touch the
services directly. Everything variable lives in config; everything structural
lives behind this one interface.
"""
from __future__ import annotations

from typing import Dict

from app.config_service import ConfigService
from app.domain.being_state import BeingState
from app.services.emotion_service import EmotionService
from app.services.need_service import NeedService
from app.services.perception_service import PerceptionService
from app.services.tick_service import TickService


class Simulation:
    def __init__(self, config: ConfigService, being_id: str = "being_001"):
        self._clock = TickService()
        self._needs = NeedService(config.need_policies())
        self._emotion = EmotionService(config.emotion_rules(), config.default_emotion())
        self._perception = PerceptionService(config.object_catalog())
        self._room = config.room()

        needs = config.initial_needs()
        self.being = BeingState(
            being_id=being_id,
            needs=needs,
            emotion=self._emotion.derive(needs),
        )

    @property
    def current_tick(self) -> int:
        return self._clock.current_tick

    def tick(self) -> Dict:
        """Advance one step: time moves, needs drift, emotion is re-derived.
        Returns the fresh state snapshot."""
        tick = self._clock.advance()
        self.being.needs = self._needs.apply(self.being.needs, tick)
        self.being.emotion = self._emotion.derive(self.being.needs)
        return self.state()

    def state(self) -> Dict:
        """A snapshot of the being plus what it currently perceives of its room.
        The `perceived` block is the being's view of the world, produced by the
        PerceptionService — never the true world state (ADR 0002)."""
        snapshot = self.being.snapshot(self._clock.current_tick)
        snapshot["perceived"] = self._perception.perceive(self._room)
        return snapshot

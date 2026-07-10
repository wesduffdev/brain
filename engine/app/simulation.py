"""Simulation — the deep module that wires the pieces into one being and steps
it through time.

This is the public surface for the whole engine core: construct it from a
ConfigService, call `tick()` to advance one step, read `state()` for a
snapshot. Callers (a demo today, an API loop tomorrow) never touch the
services directly. Everything variable lives in config; everything structural
lives behind this one interface.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, Optional

from app.config_service import ConfigService
from app.domain.being_state import BeingState
from app.services.emotion_service import EmotionService
from app.services.environment_service import EnvironmentService
from app.services.need_service import NeedService
from app.services.perception_service import PerceptionService
from app.services.tick_service import TickService


class Simulation:
    def __init__(self, config: ConfigService, being_id: str = "being_001"):
        self._clock = TickService()
        self._needs = NeedService(config.need_policies())
        self._environment = EnvironmentService(
            config.environment_policy(), config.need_policies()
        )
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
        """Advance one step: time moves, needs drift on their own, the room's
        environmental conditions push the contextual needs, and the emotion is
        re-derived from the result. Returns the fresh state snapshot."""
        tick = self._clock.advance()
        self.being.needs = self._needs.apply(self.being.needs, tick)
        self.being.needs = self._environment.apply(self.being.needs, self._room, tick)
        self.being.emotion = self._emotion.derive(self.being.needs)
        return self.state()

    def change_environment(
        self,
        *,
        light: Optional[str] = None,
        sound: Optional[str] = None,
        temperature: Optional[str] = None,
    ) -> None:
        """Change the room's environmental conditions — a world event, not an
        action of the being. Only the named dimensions change; the rest keep
        their current category. The push lands on the next `tick()`."""
        self._room = replace(
            self._room,
            light=light if light is not None else self._room.light,
            sound=sound if sound is not None else self._room.sound,
            temperature=temperature if temperature is not None else self._room.temperature,
        )

    def state(self) -> Dict:
        """A snapshot of the being plus what it currently perceives of its room.
        The `perceived` block is the being's view of the world, produced by the
        PerceptionService — never the true world state (ADR 0002)."""
        snapshot = self.being.snapshot(self._clock.current_tick)
        snapshot["perceived"] = self._perception.perceive(self._room)
        return snapshot

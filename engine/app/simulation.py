"""Simulation — the deep module that wires the pieces into one being and steps
it through time.

This is the public surface for the whole engine core: construct it from a
ConfigService, call `tick()` to advance one step, read `state()` for a
snapshot, and `interactions()` for the in-memory log of what the being has done.
Callers (a demo today, an API loop tomorrow) never touch the services directly.
Everything variable lives in config; everything structural lives behind this one
interface.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional

from app.config_service import ConfigService
from app.domain.being_state import BeingState
from app.domain.interaction_event import InteractionEvent
from app.ports.predictor import PredictorPort
from app.ports.repositories import PredictionRecordRepository
from app.repositories import InMemoryPredictionRecordRepository
from app.services.decision_service import DecisionService
from app.services.emotion_service import EmotionService
from app.services.environment_service import EnvironmentService
from app.services.need_service import NeedService
from app.services.perception_service import PerceptionService
from app.services.prediction_service import PredictionService
from app.services.safety_service import SafetyService
from app.services.tick_service import TickService


class Simulation:
    def __init__(
        self,
        config: ConfigService,
        being_id: str = "being_001",
        *,
        predictor: Optional[PredictorPort] = None,
        prediction_repository: Optional[PredictionRecordRepository] = None,
    ):
        self._clock = TickService()
        self._needs = NeedService(config.need_policies())
        self._environment = EnvironmentService(
            config.environment_policy(), config.need_policies()
        )
        self._emotion = EmotionService(config.emotion_rules(), config.default_emotion())
        self._catalog = config.object_catalog()
        self._perception = PerceptionService(self._catalog)
        self._room = config.room()

        self._actions = config.action_policies()
        self._decision = DecisionService(self._actions, SafetyService(config.safety_rules()))
        # Per-action timing gate: the tick an action may next be taken.
        self._cooldown_until: Dict[str, int] = {}
        self._events: List[InteractionEvent] = []
        self._current_action: Optional[Dict] = None

        # Shadow mode (ADR 0011): if a predictor was loaded, run it alongside the
        # rule layer and record each prediction. With no predictor, there is no
        # PredictionService and nothing is recorded — behavior is unchanged.
        self._prediction_repo: Optional[PredictionRecordRepository] = None
        self._prediction: Optional[PredictionService] = None
        if predictor is not None:
            self._prediction_repo = prediction_repository or InMemoryPredictionRecordRepository()
            self._prediction = PredictionService(
                predictor, self._prediction_repo, threshold=config.prediction_threshold()
            )

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
        environmental conditions push the contextual needs, the emotion is
        re-derived, and then the being decides on and performs one action toward
        an object (safety permitting). Returns the fresh state snapshot."""
        tick = self._clock.advance()
        self.being.needs = self._needs.apply(self.being.needs, tick)
        self.being.needs = self._environment.apply(self.being.needs, self._room, tick)
        self.being.emotion = self._emotion.derive(self.being.needs)
        self._act(tick)
        return self.state()

    def _act(self, tick: int) -> None:
        """Decide on one action from the current perception and state, obey the
        safety guardrail, and — if an action is chosen — perform it: record the
        InteractionEvent, start its cooldown, and remember it as the current
        action. Nothing selectable (no object, or all blocked/resting) leaves the
        being idle this tick."""
        perceived = self._perception.perceive(self._room)["objects"]
        on_cooldown = {name for name, until in self._cooldown_until.items() if tick <= until}
        emotion_before = self.being.emotion

        decision = self._decision.decide(
            needs=self.being.needs,
            emotion=emotion_before,
            perceived=perceived,
            on_cooldown=on_cooldown,
        )
        if decision is None:
            self._current_action = None
            return

        policy = self._actions[decision.action]
        perceived_props = next(
            (obj["properties"] for obj in perceived if obj["objectId"] == decision.target_id),
            (),
        )
        true_props = self._catalog[decision.target_id].properties

        # The action has no effect on needs in this slice, so the emotion after is
        # re-derived from the (unchanged) needs — the field is honest and will
        # diverge once actions move needs.
        emotion_after = self._emotion.derive(self.being.needs)

        event = InteractionEvent(
            being_id=self.being.being_id,
            tick=tick,
            object_id=decision.target_id,
            action=decision.action,
            expected_outcome=policy.outcomes_for(perceived_props),
            observed_outcome=policy.outcomes_for(true_props),
            emotion_before=emotion_before,
            emotion_after=emotion_after,
        )
        self._events.append(event)
        self._cooldown_until[decision.action] = (
            tick + policy.duration_ticks + policy.cooldown_ticks
        )
        self._current_action = decision.as_current_action()

        # Shadow mode: record what the learned model would have predicted for
        # this same interaction, from what the being perceived. The model's
        # action vocabulary is object affordances, so an action is encoded by its
        # affordance (`observe` -> `look`); a free action has none. Purely
        # observational — nothing above this line reads the prediction.
        if self._prediction is not None:
            self._prediction.record(
                event, properties=perceived_props, action=policy.affordance or ""
            )

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

    def interactions(self) -> List[Dict]:
        """The in-memory log of InteractionEvents the being has produced, oldest
        first, as plain snapshots. Persisting these to Postgres is a later slice
        (V0-7); for now the record lives only here."""
        return [event.snapshot() for event in self._events]

    def predictions(self) -> List[Dict]:
        """The shadow-mode prediction records the being has produced, oldest
        first, as plain snapshots — each pairing the model's predicted outcome
        with the rule's expected outcome and the actual observed outcome (ADR
        0011). Empty when no predictor is loaded (shadow mode off)."""
        if self._prediction_repo is None:
            return []
        return [record.snapshot() for record in self._prediction_repo.all()]

    def state(self) -> Dict:
        """A snapshot of the being plus what it currently perceives of its room.
        The `perceived` block is the being's view of the world, produced by the
        PerceptionService — never the true world state (ADR 0002). When the being
        took an action this tick, `currentAction` carries it ({type, targetId,
        reason}); it is absent at birth and on any idle tick."""
        snapshot = self.being.snapshot(self._clock.current_tick)
        snapshot["perceived"] = self._perception.perceive(self._room)
        if self._current_action is not None:
            snapshot["currentAction"] = dict(self._current_action)
        return snapshot

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
from app.domain.training_example import TrainingExample
from app.ml.encode_features import Example, FeatureEncoder
from app.ports.predictor import EnsemblePredictor, PredictorPort, RuleBasedPredictor
from app.db.unit_of_work import NullUnitOfWork
from app.ports.repositories import (
    InteractionEventRepository,
    PredictionRecordRepository,
    TrainingExampleRepository,
    UnitOfWork,
)
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
        event_repo: Optional[InteractionEventRepository] = None,
        training_repo: Optional[TrainingExampleRepository] = None,
        predictor: Optional[PredictorPort] = None,
        prediction_repository: Optional[PredictionRecordRepository] = None,
        unit_of_work: Optional[UnitOfWork] = None,
    ):
        # Persistence seam (ADR 0007/0012): each interaction is written through
        # these ports as it happens, and a training example is derived per event.
        # Both default to None — the pure model tests need no store, and nothing
        # below the seam ever touches SQLAlchemy. The encoder is only built when
        # training examples are actually derived.
        self._event_repo = event_repo
        self._training_repo = training_repo
        # Transaction boundary (ADR 0017): one interaction's writes — its event,
        # the derived training example, the shadow prediction — commit together as
        # one unit. Defaults to the no-op in-memory unit, so a sim with no database
        # runs unchanged; the Postgres path injects a session-backed unit.
        self._uow = unit_of_work or NullUnitOfWork()
        self._encoder = (
            FeatureEncoder.from_config(config) if training_repo is not None else None
        )

        self._clock = TickService()
        self._needs = NeedService(config.need_policies(), config.outcome_effects())
        self._environment = EnvironmentService(
            config.environment_policy(), config.need_policies()
        )
        self._emotion = EmotionService(config.emotion_rules(), config.default_emotion())
        self._catalog = config.object_catalog()
        self._perception = PerceptionService(self._catalog)
        self._room = config.room()

        self._actions = config.action_policies()
        safety = SafetyService(config.safety_rules())
        # Per-action timing gate: the tick an action may next be taken.
        self._cooldown_until: Dict[str, int] = {}
        self._events: List[InteractionEvent] = []
        self._current_action: Optional[Dict] = None

        # Prediction (ADR 0011, extended by card v3). The flip is config:
        # `prediction.neural_enabled`. Off (the default), prediction is
        # OBSERVATIONAL — shadow mode records what the model would have predicted
        # beside the rule layer and the actual outcome, and never touches the
        # decision (behavior byte-identical predictor on vs off). On, prediction is
        # ACTIVE — a rule-based baseline blended with the injected neural predictor
        # (absent -> rules only) drives the decision, so the being anticipates and
        # avoids harm within the safety floor; the decision consumes it directly,
        # so shadow recording steps aside.
        blend = config.prediction_policy()
        self._prediction_repo: Optional[PredictionRecordRepository] = None
        self._prediction: Optional[PredictionService] = None
        if blend.neural_enabled:
            ensemble = EnsemblePredictor(
                rule=RuleBasedPredictor(self._actions, config.outcome_labels()),
                neural=predictor,
                policy=blend,
            )
            self._decision = DecisionService(
                self._actions,
                safety,
                predictor=ensemble,
                outcome_effects=config.outcome_effects(),
            )
        else:
            self._decision = DecisionService(self._actions, safety)
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
        observed_outcome = policy.outcomes_for(true_props)

        # The action's observed outcome lands its felt consequence on the being's
        # needs (ADR 0014): touching a hot object produces `causes_pain`, which
        # spikes pain and drops felt safety/comfort — real, possibly-lasting harm
        # instead of a hard block. The emotion after is then re-derived from the
        # changed needs, so `emotionBefore`/`emotionAfter` diverge exactly when an
        # action mattered (closing the deferral in ADR 0009).
        self.being.needs = self._needs.apply_outcomes(self.being.needs, observed_outcome)
        emotion_after = self._emotion.derive(self.being.needs)
        self.being.emotion = emotion_after

        event = InteractionEvent(
            being_id=self.being.being_id,
            tick=tick,
            object_id=decision.target_id,
            action=decision.action,
            expected_outcome=policy.outcomes_for(perceived_props),
            observed_outcome=observed_outcome,
            emotion_before=emotion_before,
            emotion_after=emotion_after,
        )
        self._events.append(event)
        # One unit of work per interaction (ADR 0017): the event, its derived
        # training example, and the shadow prediction record all persist together
        # or not at all. Shadow-mode recording is inside the unit but stays purely
        # observational — nothing here reads the prediction back into the being.
        with self._uow.begin():
            self._record(event, true_props, policy)
            # The model's action vocabulary is object affordances, so an action is
            # encoded by its affordance (`observe` -> `look`); a free action has
            # none.
            if self._prediction is not None:
                self._prediction.record(
                    event, properties=perceived_props, action=policy.affordance or ""
                )
        self._cooldown_until[decision.action] = (
            tick + policy.duration_ticks + policy.cooldown_ticks
        )
        self._current_action = decision.as_current_action()

    def _record(self, event: InteractionEvent, true_props, policy) -> None:
        """Persist the event through its port (when one is injected) and derive a
        training example from it (when a training port is injected). The example
        encodes the object's true properties + the affordance taken + context via
        the ADR 0008 contract, paired with the observed outcomes. Free actions
        (approach/withdraw) carry no affordance, so they are recorded as events
        but are not object→outcome interactions the predictor models — no example
        is derived for them."""
        if self._event_repo is not None:
            self._event_repo.add(event)
        if self._training_repo is None or policy.affordance is None:
            return
        example = Example(
            properties=tuple(true_props),
            action=policy.affordance,
            context=(),  # the room has no surface dimension yet; the slot stays 0
            outcomes=tuple(event.observed_outcome),
        )
        self._training_repo.add(
            TrainingExample(
                event_id=event.event_id,
                input_features=self._encoder.encode_features(example),
                output_labels=self._encoder.encode_labels(example),
            )
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
        first, as plain snapshots. When a repository is injected each event is
        also persisted through the event port as it happens (V0-7b, ADR 0012);
        this log is always kept regardless."""
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

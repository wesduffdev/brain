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
    BeliefRepository,
    ConceptRepository,
    InteractionEventRepository,
    MemoryRepository,
    PredictionRecordRepository,
    SimilarityRepository,
    TrainingExampleRepository,
    UnitOfWork,
)
from app.repositories import InMemoryPredictionRecordRepository
from app.services.belief_service import BeliefService
from app.services.concept_service import ConceptService
from app.services.curiosity_service import CuriosityService
from app.services.decision_service import DecisionService
from app.services.emotion_service import EmotionService
from app.services.environment_service import EnvironmentService
from app.services.exploration_policy_service import ExplorationPolicyService
from app.services.memory_service import MemoryService
from app.services.need_service import NeedService
from app.services.perception_service import PerceptionService
from app.services.prediction_service import PredictionService
from app.services.safety_service import SafetyService
from app.services.similarity_service import SimilarityService
from app.services.surprise_service import SurpriseService
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
        memory_repository: Optional[MemoryRepository] = None,
        concept_repository: Optional[ConceptRepository] = None,
        belief_repository: Optional[BeliefRepository] = None,
        similarity_repository: Optional[SimilarityRepository] = None,
        unit_of_work: Optional[UnitOfWork] = None,
    ):
        # Persistence seam (ADR 0007/0012): each interaction is written through
        # these ports as it happens, and a training example is derived per event.
        # Both default to None — the pure model tests need no store, and nothing
        # below the seam ever touches SQLAlchemy. The encoder is only built when
        # training examples are actually derived.
        self._event_repo = event_repo
        self._training_repo = training_repo
        # Memory seam (card v1): when a memory port is injected, every interaction
        # forms one durable Memory — an object snapshot + outcome + emotion +
        # prediction error, scored with a config-driven salience. Staged inside
        # the interaction's unit of work below, so it commits with the event.
        self._memory_repo = memory_repository
        self._memory = (
            MemoryService(memory_repository, config.memory_priority_policy())
            if memory_repository is not None
            else None
        )
        # Cognitive seam (card v2): when a concept port is injected, every
        # interaction forms/strengthens CONCEPT SCHEMAS keyed on the object's
        # PERCEIVED properties, the being forms BELIEFS about the object from those
        # concepts, and it records how SIMILAR the object is to the others it
        # perceives. All three stage inside the interaction's unit of work below,
        # so they commit with the event; like memory, they are side effects of
        # living, never read back into this tick's decision.
        self._concept_repo = concept_repository
        self._belief_repo = belief_repository
        self._similarity_repo = similarity_repository
        self._concepts = (
            ConceptService(concept_repository, config.concept_learning_policy())
            if concept_repository is not None
            else None
        )
        self._beliefs = (
            BeliefService(self._concepts, belief_repository)
            if belief_repository is not None and self._concepts is not None
            else None
        )
        self._similarity = (
            SimilarityService(similarity_repository)
            if similarity_repository is not None
            else None
        )
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
        # Exploration (card v4): curiosity toward what the being cannot yet predict
        # (novelty + uncertainty + recent surprise − familiarity) and the recorded
        # surprise it decays. Always present — curiosity/surprise are exposed every
        # tick — but the decision only shifts when the config gives a non-zero
        # exploration weight (the default is a purely utility-driven being).
        self._exploration = ExplorationPolicyService(
            config.exploration_policy(),
            CuriosityService(config.curiosity_weights()),
            SurpriseService(config.surprise_policy()),
        )
        # Per-object curiosity / recent surprise for the render frame, refreshed
        # each tick from the being's perception.
        self._curiosity_view: Dict[str, float] = {}
        self._surprise_view: Dict[str, float] = {}
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
                exploration=self._exploration,
            )
        else:
            self._decision = DecisionService(self._actions, safety, exploration=self._exploration)
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

        # Curiosity toward each perceived object (from prior ticks' familiarity and
        # recent surprise) steers the decision toward what the being cannot yet
        # predict; it is also exposed on the render frame.
        self._curiosity_view = self._exploration.curiosity_map(perceived=perceived, tick=tick)
        self._surprise_view = self._exploration.surprise_map(perceived=perceived, tick=tick)

        decision = self._decision.decide(
            needs=self.being.needs,
            emotion=emotion_before,
            perceived=perceived,
            on_cooldown=on_cooldown,
            curiosity=self._curiosity_view,
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
        # training example, the shadow prediction record, and the durable memory
        # all persist together or not at all. Shadow-mode recording is inside the
        # unit but stays purely observational — nothing here reads the prediction
        # back into the being; forming the memory is likewise a side effect of the
        # interaction, never an input to this tick's decision.
        with self._uow.begin():
            self._record(event, true_props, policy)
            # The model's action vocabulary is object affordances, so an action is
            # encoded by its affordance (`observe` -> `look`); a free action has
            # none. Capture the prediction so the memory can carry its error.
            prediction = (
                self._prediction.record(
                    event, properties=perceived_props, action=policy.affordance or ""
                )
                if self._prediction is not None
                else None
            )
            if self._memory is not None:
                self._memory.remember(
                    event, perceived_properties=perceived_props, prediction=prediction
                )
            # Concept learning (card v2): distil the interaction into concept
            # schemas keyed on perceived properties, form beliefs about the object
            # from them, and record its similarity to the other perceived objects.
            if self._concepts is not None:
                self._concepts.observe(
                    being_id=self.being.being_id,
                    tick=tick,
                    object_id=decision.target_id,
                    action=decision.action,
                    perceived_properties=perceived_props,
                    observed_outcomes=observed_outcome,
                )
            if self._beliefs is not None:
                self._beliefs.believe(
                    being_id=self.being.being_id,
                    tick=tick,
                    object_id=decision.target_id,
                    perceived_properties=perceived_props,
                    action=decision.action,
                )
            if self._similarity is not None:
                self._similarity.record(
                    being_id=self.being.being_id,
                    tick=tick,
                    object_id=decision.target_id,
                    perceived_properties=perceived_props,
                    peers=[
                        (obj["objectId"], obj["properties"])
                        for obj in perceived
                        if obj["objectId"] != decision.target_id
                    ],
                )
        self._cooldown_until[decision.action] = (
            tick + policy.duration_ticks + policy.cooldown_ticks
        )
        self._current_action = decision.as_current_action()

        # Learn from the interaction: how surprising its outcome was (expected vs.
        # observed) and that the acted-on object's properties are now more familiar
        # — so next tick's curiosity reflects what the being just experienced. Then
        # refresh the recent-surprise view so the render frame shows this tick's.
        self._exploration.observe_interaction(
            object_id=decision.target_id,
            tick=tick,
            expected=event.expected_outcome,
            observed=event.observed_outcome,
            perceived_properties=perceived_props,
        )
        self._surprise_view = self._exploration.surprise_map(perceived=perceived, tick=tick)

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

    def memories(self) -> List[Dict]:
        """The durable memories the being has formed, oldest first, as plain
        snapshots — each an object snapshot (as perceived), the action, expected
        vs. observed outcome, emotion before/after, prediction error, and a
        config-driven priority (card v1). Empty when no memory port is injected."""
        if self._memory_repo is None:
            return []
        return [memory.snapshot() for memory in self._memory_repo.all()]

    def concepts(self) -> List[Dict]:
        """The concept schemas the being has learned (card v2), as plain
        snapshots — each a perceived feature + action + outcome with a confidence
        that rose as interactions confirmed it. Empty when no concept port is
        injected."""
        if self._concept_repo is None:
            return []
        return [concept.snapshot() for concept in self._concept_repo.all()]

    def beliefs(self) -> List[Dict]:
        """The beliefs the being has formed about perceived objects (card v2),
        oldest first — each a per-object prediction inherited from its concepts.
        Empty when no belief port is injected."""
        if self._belief_repo is None:
            return []
        return [belief.snapshot() for belief in self._belief_repo.all()]

    def similarities(self) -> List[Dict]:
        """The object-similarity records the being has laid down (card v2), oldest
        first — how alike, by perceived properties, each acted-on object is to the
        others in the room. Empty when no similarity port is injected."""
        if self._similarity_repo is None:
            return []
        return [record.snapshot() for record in self._similarity_repo.all()]

    def state(self) -> Dict:
        """A snapshot of the being plus what it currently perceives of its room.
        The `perceived` block is the being's view of the world, produced by the
        PerceptionService — never the true world state (ADR 0002). When the being
        took an action this tick, `currentAction` carries it ({type, targetId,
        reason}); it is absent at birth and on any idle tick. `curiosity` and
        `surprise` carry, per perceived object, how strongly the being wants to
        explore it and how recently it surprised the being (card v4) — empty until
        the first tick and on a tick with nothing to perceive."""
        snapshot = self.being.snapshot(self._clock.current_tick)
        snapshot["perceived"] = self._perception.perceive(self._room)
        snapshot["curiosity"] = dict(self._curiosity_view)
        snapshot["surprise"] = dict(self._surprise_view)
        if self._current_action is not None:
            snapshot["currentAction"] = dict(self._current_action)
        return snapshot

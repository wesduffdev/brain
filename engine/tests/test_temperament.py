"""Behavior: the being's instinct becomes ADAPTIVE — its reaction sensitivity drifts
from experience (INS-TEMPERAMENT, ADR 0031).

Identical stimuli provoke DIFFERENT reactions as the being accrues experience:

- HABITUATION — a startle that fires and proves HARMLESS (the being's `pain` did not
  rise) slowly raises that reaction's effective threshold, so a repeated harmless
  startle gradually STOPS triggering.
- SENSITIZATION — a HARMFUL outcome (the being's `pain` spiked) lowers every
  threshold, so the being is jumpier: a previously sub-threshold stimulus NOW fires.

The drift is slow, config-driven, and never touches the safety floor — it only
reshapes which REACTION fires. With the drift rates 0 the effective thresholds stay
exactly the static ones (byte-identical to the pre-slice consumer).

Every test asserts through a public surface — `TemperamentService`, the
`InstinctService` reaction stream on the bus, and `Simulation.tick()` /
`Simulation.reaction_thresholds()` — torch-free (a fake `InstinctPredictorPort`) and
broker-free (the in-memory bus).
"""
from __future__ import annotations

from typing import List

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.domain.instinct import REACTION_LABELS
from app.ml.instinct_encoder import InstinctFeatureEncoder, InstinctSpec, Stimulus
from app.outbox_relay import drain_outbox
from app.policies import MOTION_FEATURE_NAMES, InstinctRuntimePolicy, ReactionTemperamentPolicy
from app.ports.instinct import InstinctPrediction as PortPrediction
from app.repositories import (
    InMemoryEventLogRepository,
    InMemoryInstinctPredictionRepository,
    InMemoryInstinctReactionRepository,
    InMemoryOutboxRepository,
)
from app.services.instinct_service import (
    INSTINCT_REACTIONS_TOPIC,
    PERCEPTION_TOPIC,
    InstinctService,
)
from app.services.temperament_service import TemperamentService
from app.db.unit_of_work import NullUnitOfWork
from app.simulation import Simulation


# --- fakes / helpers ----------------------------------------------------------


class FixedInstinctPredictor:
    """Torch-free `InstinctPredictorPort` that returns a FIXED flinch probability
    regardless of the stimulus — so a test can place a stimulus precisely above or
    below a threshold and watch the temperament move that threshold across it."""

    def __init__(self, flinch: float = 0.7) -> None:
        self._flinch = flinch

    def predict_reactions(self, stimulus: Stimulus) -> PortPrediction:
        reactions = {label: 0.0 for label in REACTION_LABELS}
        reactions["flinch"] = self._flinch
        reactions["ignore"] = 1.0 - self._flinch
        return PortPrediction(reactions=reactions, intensity=self._flinch)


def _encoder() -> InstinctFeatureEncoder:
    return InstinctFeatureEncoder(
        InstinctSpec(feature_order=MOTION_FEATURE_NAMES, label_vocab=REACTION_LABELS)
    )


def _runtime_policy(**overrides) -> InstinctRuntimePolicy:
    defaults = dict(thresholds={"flinch": 0.5}, cooldowns={"flinch": 0}, shadow=True)
    defaults.update(overrides)
    return InstinctRuntimePolicy(**defaults)


def _service(bus, *, predictor, temperament):
    service = InstinctService(
        consumer=bus,
        publisher=bus,
        predictor=predictor,
        encoder=_encoder(),
        policy=_runtime_policy(),
        being_id="being_001",
        predictions=InMemoryInstinctPredictionRepository(),
        reactions=InMemoryInstinctReactionRepository(),
        outbox=(outbox := InMemoryOutboxRepository()),
        unit_of_work=NullUnitOfWork(),
        temperament=temperament,
    )
    return service, outbox


def _approach(tick: int) -> DomainEvent:
    features = {name: 0.0 for name in MOTION_FEATURE_NAMES}
    return DomainEvent.create(
        event_type="being.perception.object_approached",
        event_version=1,
        source_service="perception-service",
        being_id="being_001",
        payload={"objectId": "obj_1", "tick": tick, "features": features},
    )


def _drain(bus, outbox):
    drain_outbox(outbox=outbox, event_log=InMemoryEventLogRepository(), publisher=bus)


def _recorder(bus, topic):
    seen: List[DomainEvent] = []
    bus.subscribe(topic, seen.append)
    return seen


# --- TemperamentService: the drift math, through its public surface -----------


def test_a_harmless_startle_habituates_that_labels_threshold_upward():
    t = TemperamentService(
        ReactionTemperamentPolicy(habituate_rate=0.2), base_thresholds={"flinch": 0.5}
    )
    t.record_reaction("flinch")
    t.settle(harm=False)  # the startle proved harmless — habituate

    assert t.threshold("flinch") > 0.5  # less reactive now


def test_a_harmful_outcome_sensitizes_every_threshold_downward():
    t = TemperamentService(
        ReactionTemperamentPolicy(sensitize_rate=0.3),
        base_thresholds={"flinch": 0.5, "withdraw": 0.6},
    )
    t.settle(harm=True)  # the being was hurt — sensitize (no firing required)

    assert t.threshold("flinch") < 0.5
    assert t.threshold("withdraw") < 0.6  # jumpier across the board


def test_zero_rates_leave_thresholds_exactly_static():
    t = TemperamentService(ReactionTemperamentPolicy(), base_thresholds={"flinch": 0.5})
    t.record_reaction("flinch")
    t.settle(harm=False)
    t.settle(harm=True)

    assert t.threshold("flinch") == 0.5  # byte-identical to the static threshold


def test_habituation_is_gradual_and_saturating():
    t = TemperamentService(
        ReactionTemperamentPolicy(habituate_rate=0.1), base_thresholds={"flinch": 0.5}
    )
    t.record_reaction("flinch")
    t.settle(harm=False)
    after_one = t.threshold("flinch")
    for _ in range(10):
        t.record_reaction("flinch")
        t.settle(harm=False)
    after_many = t.threshold("flinch")

    assert 0.5 < after_one < 0.6           # one startle barely moves it
    assert after_many > after_one          # a life of them moves it much more
    assert after_many <= 1.0               # bounded by the ceiling


def test_a_harmful_tick_does_not_habituate_a_reaction_that_fired_that_tick():
    # harm takes precedence: a startle that fired on a tick the being was HURT
    # sensitizes, it does not habituate — the being got jumpier, not calmer.
    t = TemperamentService(
        ReactionTemperamentPolicy(habituate_rate=0.5, sensitize_rate=0.3),
        base_thresholds={"flinch": 0.5},
    )
    t.record_reaction("flinch")
    t.settle(harm=True)

    assert t.threshold("flinch") < 0.5  # sensitized, never raised


def test_only_the_label_that_fired_habituates():
    t = TemperamentService(
        ReactionTemperamentPolicy(habituate_rate=0.3),
        base_thresholds={"flinch": 0.5, "withdraw": 0.6},
    )
    t.record_reaction("flinch")
    t.settle(harm=False)

    assert t.threshold("flinch") > 0.5      # the startle that fired habituated
    assert t.threshold("withdraw") == 0.6   # the one that did not is untouched


# --- InstinctService + temperament: the adaptive gate, through the bus --------


def test_repeated_harmless_flinches_eventually_stop_triggering():
    bus = InMemoryEventBus()
    reactions = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    temperament = TemperamentService(
        ReactionTemperamentPolicy(habituate_rate=0.3), base_thresholds={"flinch": 0.5}
    )
    service, outbox = _service(bus, predictor=FixedInstinctPredictor(0.7), temperament=temperament)

    for tick in range(1, 13):
        bus.publish(PERCEPTION_TOPIC, _approach(tick))
        _drain(bus, outbox)
        temperament.settle(harm=False)  # every startle proved harmless

    triggered = [r.payload["tick"] for r in reactions if r.payload.get("triggered")]
    assert 1 in triggered            # it flinched at first
    assert 12 not in triggered       # the same approach no longer triggers a flinch
    assert temperament.threshold("flinch") > 0.7  # the effective threshold rose past it


def test_a_previously_sub_threshold_stimulus_triggers_after_sensitization():
    bus = InMemoryEventBus()
    reactions = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    temperament = TemperamentService(
        ReactionTemperamentPolicy(sensitize_rate=0.3), base_thresholds={"flinch": 0.5}
    )
    # a mild stimulus BELOW the static flinch threshold (0.45 < 0.5)
    service, outbox = _service(bus, predictor=FixedInstinctPredictor(0.45), temperament=temperament)

    bus.publish(PERCEPTION_TOPIC, _approach(tick=1))
    _drain(bus, outbox)
    assert not reactions[-1].payload.get("triggered")  # sub-threshold: no reaction

    for _ in range(4):
        temperament.settle(harm=True)  # the being is hurt, again and again — sensitize

    bus.publish(PERCEPTION_TOPIC, _approach(tick=2))
    _drain(bus, outbox)
    assert reactions[-1].payload.get("triggered")  # the SAME stimulus now triggers


# --- Simulation end-to-end: the being visibly habituates ----------------------


def _sim_config(*, habituate_rate=0.0, sensitize_rate=0.0, flinch_threshold=0.5):
    tick_rates = {
        "tick": {"duration_ms": 1000},
        "needs": {
            "pain": {"direction": "decrease", "amount": 2, "every_ticks": 4,
                     "min": 0, "max": 100, "start": 0},
        },
    }
    emotions = {"rules": [{"emotion": "scared", "need": "safety", "op": "<=", "value": 30}],
                "default": "calm"}
    rooms = {"room": {"id": "room_001", "contains": ["obj_mover"]}}
    objects = {
        "properties": ["round"],
        "affordances": ["look"],
        "objects": {"obj_mover": {"developerLabel": "M", "properties": ["round"],
                                  "affordances": ["look"]}},
    }
    actions = {
        "actions": {
            "observe": {"affordance": "look", "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                        "expected_outcomes": ["pleasant"], "reason": "a careful look"},
        }
    }
    # A slow, dead-on approach that keeps closing for many ticks (distance 50, speed 0.5).
    motion = {
        "normalization": {"max_distance": 10.0, "max_speed": 5.0, "max_acceleration": 5.0,
                          "max_time_to_contact": 10.0, "max_size": 1.0, "max_size_change_rate": 1.0},
        "approach": {"min_closing_speed": 0.0},
        "objects": {"obj_mover": {"position": [50.0, 0.0], "velocity": [-0.5, 0.0], "size": 0.3}},
    }
    instinct = {
        "feature_order": list(MOTION_FEATURE_NAMES),
        "labels": list(REACTION_LABELS),
        "runtime": {"enabled": True},
        "reaction": {
            "shadow": True,
            "thresholds": {"flinch": flinch_threshold},
            "cooldowns": {"flinch": 0},
            "visual_only": True,
            "temperament": {"habituate_rate": habituate_rate, "sensitize_rate": sensitize_rate},
        },
    }
    return ConfigService.from_dict(
        tick_rates, emotions, rooms=rooms, objects=objects, actions=actions,
        safety={"rules": []}, outcome={"labels": ["pleasant"], "context_features": []},
        instinct=instinct, motion=motion,
    )


def _run_wired(config, *, predictor, ticks):
    from app.bootstrap import build_simulation

    bus = InMemoryEventBus()
    reactions = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    with build_simulation(config, env={}, event_publisher=bus, event_consumer=bus,
                          instinct_predictor=predictor) as sim:
        for _ in range(ticks):
            sim.tick()
        thresholds = sim.reaction_thresholds()
    triggered_ticks = [r.payload["tick"] for r in reactions if r.payload.get("triggered")]
    return triggered_ticks, thresholds


def test_a_being_habituates_to_a_repeated_harmless_approach():
    # the headline outcome: the SAME harmless approach that startles the being at
    # first stops triggering a flinch as the being learns it is nothing to fear.
    triggered, thresholds = _run_wired(
        _sim_config(habituate_rate=0.2), predictor=FixedInstinctPredictor(0.7), ticks=12
    )

    assert triggered, "the being should flinch at the fast approach at first"
    assert min(triggered) <= 2               # startled early
    assert max(triggered) < 10               # then habituated — no late flinches
    assert thresholds["flinch"] > 0.7        # the effective threshold climbed past the stimulus


def test_zero_drift_config_keeps_the_reaction_firing_like_static_thresholds():
    # with the drift rates 0, the SAME harmless approach keeps triggering every tick —
    # byte-identical to today's static thresholds (no habituation, no drift).
    triggered, thresholds = _run_wired(
        _sim_config(habituate_rate=0.0), predictor=FixedInstinctPredictor(0.7), ticks=12
    )

    assert len(triggered) == 12              # fires on every single tick, forever
    assert thresholds["flinch"] == 0.5       # threshold never moved


def test_a_being_with_no_instinct_chain_exposes_no_reaction_thresholds():
    sim = Simulation(_sim_config(habituate_rate=0.2))  # no predictor -> no chain
    sim.tick()
    assert sim.reaction_thresholds() == {}


# --- config plumbing ----------------------------------------------------------


def test_config_yields_the_temperament_policy():
    policy = _sim_config(habituate_rate=0.15, sensitize_rate=0.25).reaction_temperament_policy()
    assert policy.habituate_rate == 0.15
    assert policy.sensitize_rate == 0.25


def test_absent_temperament_config_is_zero_drift():
    config = ConfigService.from_dict(
        {"tick": {"duration_ms": 100}, "needs": {}},
        {"rules": [], "default": "calm"},
        instinct={"feature_order": list(MOTION_FEATURE_NAMES), "labels": list(REACTION_LABELS)},
    )
    policy = config.reaction_temperament_policy()
    assert policy.habituate_rate == 0.0
    assert policy.sensitize_rate == 0.0

"""Behavior: the DEPLOYED runtime (bootstrap/main) drives the perception ->
instinct -> reaction chain LIVE, in shadow (RUNTIME-WIRE).

The event-instinct layer already runs end-to-end when a caller hands `Simulation`
a shared bus + an instinct predictor (EVT-VALID). The gap this slice closes: the
deployed engine assembled by `build_simulation` never built a bus, so a running
being — even with a trained artifact — never fired instinct. These tests pin the
bootstrap's new contract through its public surface (`build_simulation` ->
`Simulation.tick()`/`.state()` and the events on the shared bus):

- given an instinct predictor, the bootstrap builds a shared EventBus and wires
  the chain, so a moving object drives a reaction the being surfaces (proven with
  the activation flag on) -- WITHOUT any caller-injected bus;
- in shadow (flags off, the shipped default) the wired chain really fires yet the
  being's state()/decisions are byte-identical to an un-wired being;
- with no predictor (no torch / no artifact -> None) the chain is inert and the
  being is byte-identical, so the lean runtime and the whole suite are untouched.

A torch-free fake instinct predictor stands in for the trained model; no broker,
no database.
"""
from __future__ import annotations

import os

from typing import List

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.bootstrap import build_simulation
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.domain.instinct import REACTION_LABELS
from app.ml.instinct_encoder import Stimulus
from app.policies import MOTION_FEATURE_NAMES
from app.ports.instinct import InstinctPrediction as PortPrediction
from app.services.instinct_service import INSTINCT_REACTIONS_TOPIC
from app.services.reaction_response_service import ACTION_INTERRUPTED
from app.simulation import Simulation


_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class FakeInstinctPredictor:
    """Torch-free `InstinctPredictorPort`: the being flinches at a fast, body-bound
    approach -- flinch probability and intensity both track velocity*trajectory."""

    def predict_reactions(self, stimulus: Stimulus) -> PortPrediction:
        threat = _clamp(stimulus.velocity * stimulus.trajectory_toward_body)
        reactions = {label: 0.0 for label in REACTION_LABELS}
        reactions["flinch"] = threat
        reactions["ignore"] = 1.0 - threat
        return PortPrediction(reactions=reactions, intensity=threat)


def _config(*, visual_only=False, allow_interrupt=False, runtime_enabled=True,
            interruptible=("observe",), threshold=0.5, safety_rules=None):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": {}}
    emotions = {
        "rules": [{"emotion": "scared", "need": "safety", "op": "<=", "value": 30}],
        "default": "calm",
    }
    rooms = {"room": {"id": "room_001", "contains": ["obj_mover"]}}
    objects = {
        "properties": ["round"],
        "affordances": ["look"],
        "objects": {
            "obj_mover": {"developerLabel": "M", "properties": ["round"], "affordances": ["look"]},
        },
    }
    actions = {
        "actions": {
            "observe": {
                "affordance": "look",
                "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                "expected_outcomes": ["pleasant"],
                "reason": "taking a careful look",
            },
        }
    }
    # A fast object heading dead-on at the body (velocity -4 over distance 8).
    motion = {
        "normalization": {
            "max_distance": 10.0,
            "max_speed": 5.0,
            "max_acceleration": 5.0,
            "max_time_to_contact": 10.0,
            "max_size": 1.0,
            "max_size_change_rate": 1.0,
        },
        "approach": {"min_closing_speed": 0.0},
        "objects": {"obj_mover": {"position": [8.0, 0.0], "velocity": [-4.0, 0.0], "size": 0.3}},
    }
    instinct = {
        "feature_order": list(MOTION_FEATURE_NAMES),
        "labels": list(REACTION_LABELS),
        "runtime": {"enabled": runtime_enabled},
        "reaction": {
            "shadow": True,
            "thresholds": {"flinch": 0.5},
            "cooldowns": {"flinch": 0},
            "visual_only": visual_only,
            "allow_interrupt": allow_interrupt,
            "emotion_bias": {"flinch": {"safety": -60}},
            "interrupt": {
                "intensity_threshold": threshold,
                "interruptible_actions": list(interruptible),
                "protective_action": "withdraw",
            },
        },
    }
    return ConfigService.from_dict(
        tick_rates,
        emotions,
        rooms=rooms,
        objects=objects,
        actions=actions,
        safety={"rules": list(safety_rules or [])},
        outcome={"labels": ["pleasant"], "context_features": []},
        instinct=instinct,
        motion=motion,
    )


def _recorder(bus, topic):
    seen: List[DomainEvent] = []
    bus.subscribe(topic, seen.append)
    return seen


# --- the bootstrap builds the bus and drives the live chain -------------------


def test_bootstrap_drives_the_instinct_chain_live_with_a_predictor_and_no_injected_bus():
    # No bus is injected: only the bootstrap can supply the shared EventBus the
    # chain needs. With the visual_only flag on, a moving object must drive a
    # reaction the being surfaces and feels -- proof the deployed wiring fired the
    # whole perception->instinct->reaction chain in-process.
    with build_simulation(
        _config(visual_only=True),
        env={},
        instinct_predictor=FakeInstinctPredictor(),
    ) as sim:
        sim.tick()          # stimulus -> instinct reaction, drained onto the bus
        state = sim.tick()  # the between-ticks reaction now surfaces

        assert state["reaction"]["type"] == "flinch"
        assert state["emotion"] == "scared"


# --- shadow (flags off): the wired chain fires yet changes NO behaviour --------


def test_bootstrap_shadow_chain_fires_but_state_is_byte_identical_to_an_unwired_being():
    bus = InMemoryEventBus()
    reactions = _recorder(bus, INSTINCT_REACTIONS_TOPIC)
    with build_simulation(
        _config(),  # flags default off (shadow)
        env={},
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    ) as wired, build_simulation(
        _config(runtime_enabled=False),  # no chain at all
        env={},
    ) as baseline:
        for _ in range(4):
            a = wired.tick()
            b = baseline.tick()
            assert a == b
            assert "reaction" not in a

    # the chain genuinely fired a triggered reaction on the bus -- yet nothing in
    # the being's observable state moved (true shadow).
    assert any(r.payload.get("triggered") for r in reactions)


# --- None-safe: no predictor => inert => byte-identical (lean runtime) ---------


def test_bootstrap_without_a_predictor_wires_no_chain_and_is_byte_identical():
    # The runtime enable flag is on, but the artifact path does not exist, so the
    # predictor loads as None and the chain stays out entirely -- the lean-runtime
    # path (no torch / no artifact). The being is byte-identical to a plain one.
    plain = Simulation(_config())
    with build_simulation(
        _config(),
        env={"INSTINCT_MODEL_PATH": "/nonexistent/instinct.pt"},
    ) as sim:
        for _ in range(4):
            a = sim.tick()
            b = plain.tick()
            assert a == b
            assert "reaction" not in a
        assert sim.instinct_lag() == 0


# --- the runtime-enable flag (config seam) ------------------------------------


def test_runtime_instinct_is_enabled_by_default_and_config_can_disable_it():
    assert _config().instinct_runtime_enabled() is True
    assert _config(runtime_enabled=False).instinct_runtime_enabled() is False
    # An instinct config with no runtime block at all still defaults on.
    cfg = ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": {}},
        {"rules": [], "default": "calm"},
        instinct={"feature_order": list(MOTION_FEATURE_NAMES), "labels": list(REACTION_LABELS)},
    )
    assert cfg.instinct_runtime_enabled() is True


# --- the SHIPPED config, end to end: a legible flinch that INTERRUPTS -----------


def test_shipped_config_interrupts_the_beings_action_on_a_flinch_at_the_ball():
    # INTERRUPT-ON, the slice outcome on the SHIPPED config + shipped world motion:
    # the red ball is a fast, body-bound approach; with the shipped flags ON
    # (visual_only + allow_interrupt) and an instinct predictor wired, the flinch it
    # triggers CANCELS the being's chosen action -- its outcome never lands, the being
    # still reads `scared`, and an ActionInterrupted is emitted on the durable action
    # topic. A no-instinct baseline (no predictor) never interrupts and keeps acting.
    # Next-action semantics: the reaction to a tick's approach interrupts the FOLLOWING
    # tick's action (reactions arrive between ticks and latch at begin_tick). Torch-free
    # (a fake predictor stands in for models/instinct.pt), so this holds in the
    # artifact-free canonical suite too.
    config = ConfigService.from_files(_CONFIG_ROOT).with_room_contents(["obj_red_ball"])

    bus = InMemoryEventBus()
    action_events = _recorder(bus, "being.action.events")
    baseline = Simulation(config)  # no predictor -> instinct chain inert, never interrupts
    interrupted_tick = None
    scared_when_interrupted = False
    with build_simulation(
        config,
        env={},
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    ) as wired:
        for _ in range(4):
            a = wired.tick()
            b = baseline.tick()
            if a.get("reaction") is not None and "currentAction" not in a:
                # an interrupt tick: the wired being's action was broken off, yet the
                # baseline (same world, no instinct) still acted -> proof the outcome
                # did not land and instinct alone caused the divergence.
                interrupted_tick = a["tick"]
                scared_when_interrupted = a["emotion"] == "scared"
                assert b.get("currentAction") is not None

    interrupted = [e for e in action_events if e.event_type == ACTION_INTERRUPTED]
    assert interrupted, "the fast body-bound ball should have interrupted the being"
    assert interrupted[0].payload["reaction"] == "flinch"
    assert interrupted[0].payload["action"] in {"observe", "approach", "touch", "grab", "push"}
    assert interrupted_tick is not None and scared_when_interrupted
    # the being performed strictly FEWER actions than the no-instinct baseline -- the
    # interrupted action's outcome never landed on the being.
    assert len(wired.interactions()) < len(baseline.interactions())


# --- the LIVE chain, controlled: the CRUX interrupt timing, proven --------------


def test_allow_interrupt_cancels_the_action_live_through_the_wired_chain():
    # THE CRUX end to end: through the LIVE bootstrap chain (shared bus + instinct
    # predictor), a fast body-bound approach on tick 1 drives a flinch that is latched
    # between ticks and CANCELS the being's action on tick 2 -- its outcome never
    # lands, the being reads `scared` (visual bias still applies on the interrupt
    # tick), and one ActionInterrupted is emitted on the durable action topic. A
    # no-instinct baseline acts on BOTH ticks, so the wired being ends with strictly
    # fewer interactions.
    bus = InMemoryEventBus()
    action_events = _recorder(bus, "being.action.events")
    baseline = Simulation(_config())  # no predictor -> never interrupts
    with build_simulation(
        _config(visual_only=True, allow_interrupt=True),
        env={},
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    ) as wired:
        wired.tick()          # tick 1: approach seen; reaction drained AFTER the action
        baseline.tick()
        second = wired.tick()  # tick 2: flinch latched -> the decided action is cancelled
        baseline.tick()

    assert "currentAction" not in second          # tick 2's action was broken off
    assert second["emotion"] == "scared"          # emotion still biased on the interrupt tick
    assert second["reaction"]["type"] == "flinch"
    interrupted = [e for e in action_events if e.event_type == ACTION_INTERRUPTED]
    assert len(interrupted) == 1
    assert interrupted[0].payload["tick"] == 2
    assert interrupted[0].payload["action"] == "observe"
    # the outcome never landed: the wired being acted once (tick 1), the baseline twice.
    assert len(wired.interactions()) == 1
    assert len(baseline.interactions()) == 2


def test_a_floor_forbidden_interruption_is_suppressed_live_and_the_being_keeps_acting():
    # SAFETY FLOOR: the invariant floor forbids the protective response (withdraw) on
    # the approaching object, so the interruption the flinch would trigger is
    # SUPPRESSED -- the being COMPLETES its action, no ActionInterrupted is forced, and
    # the floor is never bypassed. Instinct proposes; the floor disposes.
    floor = [{"action": "withdraw", "blocked_property": "round", "reason": "breaking off here is invalid"}]
    bus = InMemoryEventBus()
    action_events = _recorder(bus, "being.action.events")
    with build_simulation(
        _config(visual_only=True, allow_interrupt=True, safety_rules=floor),
        env={},
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    ) as wired:
        for _ in range(2):
            state = wired.tick()

    assert state["currentAction"]["type"] == "observe"  # completed, not cancelled
    assert len(wired.interactions()) == 2               # both actions landed
    assert [e for e in action_events if e.event_type == ACTION_INTERRUPTED] == []
    # the being still SURFACED the flinch and felt it -- suppression is of the
    # INTERRUPTION only, not of the reaction/emotion (visual-only remains live).
    assert state["reaction"]["type"] == "flinch"
    assert state["emotion"] == "scared"


def test_an_action_absent_from_interruptible_actions_is_not_interrupted_live():
    # A strong flinch on an action the config does not list as interruptible changes
    # nothing: `observe` is withheld from the interruptible set, so the being completes
    # it every tick. Instinct cannot break off an action the config does not offer it.
    bus = InMemoryEventBus()
    action_events = _recorder(bus, "being.action.events")
    with build_simulation(
        _config(visual_only=True, allow_interrupt=True, interruptible=("touch",)),
        env={},
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    ) as wired:
        for _ in range(2):
            state = wired.tick()

    assert state["currentAction"]["type"] == "observe"
    assert len(wired.interactions()) == 2
    assert [e for e in action_events if e.event_type == ACTION_INTERRUPTED] == []


def test_a_below_threshold_reaction_does_not_interrupt_live():
    # With the interrupt threshold raised ABOVE the flinch intensity (0.8), the strong
    # reaction still SURFACES and colours emotion (visual-only) but never interrupts --
    # the being keeps acting. Only reactions at/above the threshold break an action off.
    bus = InMemoryEventBus()
    action_events = _recorder(bus, "being.action.events")
    with build_simulation(
        _config(visual_only=True, allow_interrupt=True, threshold=0.95),
        env={},
        event_publisher=bus,
        event_consumer=bus,
        instinct_predictor=FakeInstinctPredictor(),
    ) as wired:
        for _ in range(2):
            state = wired.tick()

    assert state["reaction"]["type"] == "flinch"          # surfaced (visual-only)
    assert state["currentAction"]["type"] == "observe"    # but NOT interrupted
    assert len(wired.interactions()) == 2
    assert [e for e in action_events if e.event_type == ACTION_INTERRUPTED] == []

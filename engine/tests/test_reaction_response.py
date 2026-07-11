"""Behaviors of the INS-ACT active-instinct integration: a triggered instinct
reaction, arriving on `being.instinct.reactions`, can BIAS the being's DERIVED
emotion and INTERRUPT its current action — staged behind two config flags that
both default to the prior (byte-identical) behavior (ADR 0029).

Everything is asserted through the public surface only — `Simulation.tick()`,
`Simulation.state()`, `Simulation.interactions()`, and the events published on the
in-memory bus (`being.state.events` / `being.action.events`). A fake reaction
event stands in for the upstream INS-RT consumer; no torch, no broker, no DB.

Invariants pinned here:
- emotion is DERIVED (never assigned): a flinch nudges the being toward `scared`
  by feeding a TRANSIENT affect signal into the same needs->emotion derivation —
  the stored `safety` need is left untouched.
- the SafetyService floor is inviolable: an interruption whose protective response
  the floor forbids is SUPPRESSED, not forced.
- both flags off => byte-identical (a reaction has zero observable effect).
"""
from __future__ import annotations

from app.adapters.in_memory_event_bus import InMemoryEventBus
from app.config_service import ConfigService
from app.domain.event import DomainEvent
from app.simulation import Simulation
from app.services.reaction_response_service import (
    ACTION_EVENTS_TOPIC,
    ACTION_INTERRUPTED,
    EMOTION_BIAS_APPLIED,
    INSTINCT_REACTIONS_TOPIC,
    REACTION_TRIGGERED,
    STATE_EVENTS_TOPIC,
)

# --- fear when felt safety is low; the reaction pushes the being under it -------
_EMOTIONS = {
    "rules": [
        {"emotion": "scared", "need": "safety", "op": "<=", "value": 30},
        {"emotion": "curious", "need": "curiosity", "op": ">=", "value": 70},
    ],
    "default": "calm",
}

_OBJECTS = {
    "properties": ["soft", "hard"],
    "affordances": ["look", "touch"],
    "objects": {
        "obj_soft": {"developerLabel": "Soft Thing", "properties": ["soft"], "affordances": ["look", "touch"]},
    },
}

# observe dominates utility, so the being's action each tick is deterministic and
# interruptible.
_ACTIONS = {
    "actions": {
        "observe": {
            "affordance": "look",
            "utility": {"base": 10.0, "needs": {}, "emotions": {}},
            "expected_outcomes": ["pleasant"],
            "reason": "taking a careful look",
        },
    }
}


def _needs(**overrides):
    levels = {"curiosity": 40, "safety": 80, "comfort": 70, "hunger": 30, "sleep": 30, "warmth": 50}
    levels.update(overrides)
    needs = {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }
    needs["pain"] = {"direction": "decrease", "amount": 2, "every_ticks": 4, "min": 0, "max": 100, "start": 0}
    return needs


def _reaction_block(*, visual_only=False, allow_interrupt=False):
    return {
        "labels": ["flinch", "freeze", "orient", "withdraw", "ignore"],
        "reaction": {
            "thresholds": {"flinch": 0.5},
            "cooldowns": {"flinch": 5},
            "shadow": True,
            "visual_only": visual_only,
            "allow_interrupt": allow_interrupt,
            "emotion_bias": {"flinch": {"safety": -60}},
            "interrupt": {
                "intensity_threshold": 0.7,
                "interruptible_actions": ["observe", "touch"],
                "protective_action": "withdraw",
            },
        },
    }


def _config(*, contains=(), visual_only=False, allow_interrupt=False, safety=None):
    return ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": _needs()},
        _EMOTIONS,
        rooms={"room": {"id": "room_001", "contains": list(contains)}},
        objects=_OBJECTS,
        outcome={"labels": ["pleasant"], "context_features": []},
        actions=_ACTIONS,
        safety=safety if safety is not None else {"rules": []},
        instinct=_reaction_block(visual_only=visual_only, allow_interrupt=allow_interrupt),
    )


def _sim(config):
    bus = InMemoryEventBus()
    sim = Simulation(config, event_publisher=bus, event_consumer=bus)
    return sim, bus


def _recorder(bus, topic):
    seen = []
    bus.subscribe(topic, seen.append)
    return seen


def _flinch(*, intensity=0.9, triggered=True, object_id="obj_soft", tick=1):
    return DomainEvent.create(
        event_type=REACTION_TRIGGERED,
        event_version=1,
        source_service="instinct-service",
        being_id="being_001",
        payload={
            "objectId": object_id,
            "tick": tick,
            "reaction": "flinch",
            "intensity": intensity,
            "triggered": triggered,
        },
    )


# --- default: both flags off => byte-identical --------------------------------


def test_with_both_flags_off_a_reaction_has_no_observable_effect():
    # Two beings on the same flags-off config: one receives a flinch, one does not.
    # Their states after a tick must be identical, and no reaction/bias/interrupt
    # surfaces anywhere.
    with_reaction, bus_a = _sim(_config(contains=()))
    state_events = _recorder(bus_a, STATE_EVENTS_TOPIC)
    action_events = _recorder(bus_a, ACTION_EVENTS_TOPIC)
    bus_a.publish(INSTINCT_REACTIONS_TOPIC, _flinch())
    after_reaction = with_reaction.tick()

    baseline, _ = _sim(_config(contains=()))
    after_baseline = baseline.tick()

    assert after_reaction == after_baseline
    assert "reaction" not in after_reaction
    assert after_reaction["emotion"] == "calm"
    assert state_events == [] and action_events == []


# --- visual_only: emotion bias via derivation + reaction surfaced -------------


def test_visual_only_biases_the_derived_emotion_toward_scared():
    sim, bus = _sim(_config(contains=(), visual_only=True))
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.9))

    state = sim.tick()

    assert state["emotion"] == "scared"
    # derived, NOT assigned: the stored safety need is untouched by the transient bias
    assert state["needs"]["safety"] == 80


def test_visual_only_surfaces_the_reaction_field_for_the_renderer():
    sim, bus = _sim(_config(contains=(), visual_only=True))
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.75))

    state = sim.tick()

    assert state["reaction"] == {"type": "flinch", "intensity": 0.75}


def test_visual_only_emits_an_emotion_bias_applied_state_event():
    sim, bus = _sim(_config(contains=(), visual_only=True))
    state_events = _recorder(bus, STATE_EVENTS_TOPIC)
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.9))

    sim.tick()

    assert len(state_events) == 1
    event = state_events[0]
    assert event.event_type == EMOTION_BIAS_APPLIED
    assert event.payload["reaction"] == "flinch"


def test_visual_only_does_not_interrupt_the_current_action():
    sim, bus = _sim(_config(contains=("obj_soft",), visual_only=True))
    action_events = _recorder(bus, ACTION_EVENTS_TOPIC)
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.99))

    state = sim.tick()

    # the being still completed its action — nothing was cancelled
    assert state["currentAction"]["type"] == "observe"
    assert sim.interactions()[-1]["action"] == "observe"
    assert action_events == []


def test_a_reaction_fades_after_one_tick_when_none_follows():
    sim, bus = _sim(_config(contains=(), visual_only=True))
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.9))

    first = sim.tick()
    assert first["emotion"] == "scared" and "reaction" in first

    second = sim.tick()  # no new reaction arrived
    assert second["emotion"] == "calm"
    assert "reaction" not in second


# --- allow_interrupt: safety-gated cancellation -------------------------------


def test_allow_interrupt_cancels_a_safe_interruptible_action():
    sim, bus = _sim(_config(contains=("obj_soft",), visual_only=True, allow_interrupt=True))
    action_events = _recorder(bus, ACTION_EVENTS_TOPIC)
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.95))

    state = sim.tick()

    # the action was broken off: no currentAction, and its interaction never landed
    assert "currentAction" not in state
    assert sim.interactions() == []
    assert len(action_events) == 1
    event = action_events[0]
    assert event.event_type == ACTION_INTERRUPTED
    assert event.payload["action"] == "observe"
    assert event.payload["reaction"] == "flinch"


def test_an_unsafe_interruption_is_suppressed_not_forced():
    # The invariant floor forbids the protective response (`withdraw`) on a `soft`
    # object, so the interruption would produce a floor-forbidden state: it is
    # SUPPRESSED — the being completes its action rather than being forced into an
    # unsafe break-off. The safety floor is never bypassed.
    floor = {"rules": [{"action": "withdraw", "blocked_property": "soft", "reason": "breaking off here is invalid"}]}
    sim, bus = _sim(
        _config(contains=("obj_soft",), visual_only=True, allow_interrupt=True, safety=floor)
    )
    action_events = _recorder(bus, ACTION_EVENTS_TOPIC)
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.99))

    state = sim.tick()

    assert state["currentAction"]["type"] == "observe"   # completed, not cancelled
    assert sim.interactions()[-1]["action"] == "observe"
    assert action_events == []                             # no ActionInterrupted forced


def test_a_low_intensity_reaction_does_not_interrupt():
    sim, bus = _sim(_config(contains=("obj_soft",), visual_only=True, allow_interrupt=True))
    action_events = _recorder(bus, ACTION_EVENTS_TOPIC)
    bus.publish(INSTINCT_REACTIONS_TOPIC, _flinch(intensity=0.5))  # below 0.7 threshold

    state = sim.tick()

    assert state["currentAction"]["type"] == "observe"
    assert action_events == []


# --- config plumbing ----------------------------------------------------------


def test_config_yields_the_reaction_response_policy_defaulting_off():
    config = ConfigService.from_dict(
        {"tick": {"duration_ms": 100}, "needs": {}},
        {"rules": [], "default": "calm"},
        instinct=_reaction_block(),
    )
    policy = config.reaction_response_policy()
    assert policy.visual_only is False
    assert policy.allow_interrupt is False


def test_config_reads_the_two_activation_flags():
    config = ConfigService.from_dict(
        {"tick": {"duration_ms": 100}, "needs": {}},
        {"rules": [], "default": "calm"},
        instinct=_reaction_block(visual_only=True, allow_interrupt=True),
    )
    policy = config.reaction_response_policy()
    assert policy.visual_only is True
    assert policy.allow_interrupt is True


def test_the_shipped_config_activates_visual_only_and_keeps_interrupt_off():
    # VISUAL-ON: the shipped being SURFACES reactions and biases its DERIVED
    # emotion (visual_only ON), but no action is ever interrupted (allow_interrupt
    # stays OFF this slice). The flags-off SAFE DEFAULT for an unset reaction block
    # is covered by test_config_yields_the_reaction_response_policy_defaulting_off.
    import os

    root = os.path.join(os.path.dirname(__file__), "..", "..", "config")
    policy = ConfigService.from_files(root).reaction_response_policy()
    assert policy.visual_only is True
    assert policy.allow_interrupt is False

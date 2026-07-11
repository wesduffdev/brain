"""Behavior: the being grows an individual PERSONALITY from what it lives (v6).

Two slow traits drift from repeated experience — a CAUTION tendency and a
CURIOSITY tendency — so a being that keeps getting hurt grows wary and a being that
keeps exploring safely grows bolder. The drift is slow by construction: one
interaction barely moves the being; a life of them settles into a temperament. How
fast each trait forms, and how strongly it steers behaviour, is tuned in
`config/traits.yaml` alone.

Every test asserts through a public surface: `Simulation.tick()` /
`Simulation.traits()` / `Simulation.state()` and the `TraitService` interface.
"""
from __future__ import annotations

from app.config_service import ConfigService
from app.policies import OutcomeEffectPolicy, TraitDriftPolicy, TraitPolicy
from app.services.trait_service import TraitService
from app.simulation import Simulation

_OBJECTS = {
    "properties": ["hot", "hard", "soft", "round"],
    "affordances": ["look", "touch"],
    "objects": {
        "obj_stove": {"developerLabel": "Stove", "properties": ["hot", "hard"], "affordances": ["look", "touch"]},
        "obj_pillow": {"developerLabel": "Pillow", "properties": ["soft", "round"], "affordances": ["look", "touch"]},
    },
}

# touch dominates and carries no emotion dependence, so the being keeps reaching out
# tick after tick — the repetition the slow traits need. The emotion table has no
# `scared` rule, so a crashing felt-safety never flips it off touch.
_ACTIONS = {
    "actions": {
        "observe": {"affordance": "look", "utility": {"base": 1.0, "needs": {}, "emotions": {}},
                    "expected_outcomes": ["pleasant"], "reason": "look"},
        "touch": {"affordance": "touch", "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                  "expected_outcomes": ["pleasant"],
                  "property_outcomes": {"hot": ["causes_pain", "scary"], "soft": ["pleasant"]},
                  "reason": "touch"},
    }
}
_OUTCOME = {"labels": ["pleasant", "causes_pain", "scary"]}
_OUTCOME_EFFECTS = {"effects": {"causes_pain": {"safety": -40, "comfort": -20}, "scary": {"safety": -10},
                                "pleasant": {"comfort": 5}}}
_EMOTIONS = {"rules": [], "default": "calm"}


def _traits_config(*, caution_rate=0.05, curiosity_rate=0.05):
    return {
        "traits": {
            "caution": {"start": 0.2, "drift_rate": caution_rate, "decision_gain": 1.0},
            "curiosity": {"start": 0.2, "drift_rate": curiosity_rate, "decision_gain": 0.0},
        }
    }


def _needs():
    levels = {"curiosity": 40, "safety": 80, "comfort": 70}
    return {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }


def _sim(*, contains, traits):
    return Simulation(
        ConfigService.from_dict(
            {"tick": {"duration_ms": 1000}, "needs": _needs()},
            _EMOTIONS,
            rooms={"room": {"id": "room_001", "contains": list(contains)}},
            objects=_OBJECTS,
            actions=_ACTIONS,
            safety={"rules": []},
            outcome=_OUTCOME,
            outcome_effects=_OUTCOME_EFFECTS,
            traits=traits,
        )
    )


# --- drift: repeated experience shapes the two traits -------------------------


def test_repeated_negative_surprise_raises_the_caution_trait_slowly():
    sim = _sim(contains=["obj_stove"], traits=_traits_config())
    before = sim.traits()["caution"]

    for _ in range(20):
        sim.tick()  # reaches out, is burned worse than it expected, every tick

    assert sim.traits()["caution"] > before


def test_repeated_positive_exploration_raises_the_curiosity_trait_slowly():
    sim = _sim(contains=["obj_pillow"], traits=_traits_config())
    before = sim.traits()["curiosity"]

    for _ in range(20):
        sim.tick()  # touches something soft and pleasant, again and again

    assert sim.traits()["curiosity"] > before


def test_a_single_interaction_moves_a_trait_only_slightly():
    sim = _sim(contains=["obj_stove"], traits=_traits_config())
    start = sim.traits()["caution"]

    sim.tick()
    after_one = sim.traits()["caution"]
    for _ in range(19):
        sim.tick()
    after_many = sim.traits()["caution"]

    # one interaction nudges caution up a little; a life of them moves it much more
    assert 0.0 < after_one - start < 0.1
    assert after_many > after_one


def test_a_harmful_experience_does_not_raise_curiosity():
    # being hurt shapes caution, not curiosity — the two traits track different
    # experiences, so a life of harm does not read as a life of happy exploration.
    sim = _sim(contains=["obj_stove"], traits=_traits_config())
    before = sim.traits()["curiosity"]

    for _ in range(20):
        sim.tick()

    assert sim.traits()["curiosity"] == before


# --- retuning trait drift is config-only --------------------------------------


def test_retuning_trait_drift_is_config_only():
    slow = _sim(contains=["obj_stove"], traits=_traits_config(caution_rate=0.02))
    fast = _sim(contains=["obj_stove"], traits=_traits_config(caution_rate=0.20))

    for _ in range(20):
        slow.tick()
        fast.tick()

    # the SAME twenty burns leave a more cautious being purely because config said so
    assert fast.traits()["caution"] > slow.traits()["caution"]


# --- traits steer behaviour: a wary being heeds its bad memories more ---------


def test_a_more_cautious_being_amplifies_its_aversion_to_a_bad_memory():
    bias = {("obj_kettle", "touch"): -10.0}

    def caution(start):
        policy = TraitPolicy(
            caution=TraitDriftPolicy(start=start, decision_gain=1.0),
            curiosity=TraitDriftPolicy(),
        )
        return TraitService(policy).modulate(bias)[("obj_kettle", "touch")]

    wary = caution(0.9)
    bold = caution(0.1)

    # both hold the being back, but the warier being drops the risky score further
    assert wary < bold < 0.0


def test_caution_drift_lifts_how_strongly_a_bad_memory_is_heeded():
    # drive drift through the public service, then read the modulation it produces
    service = TraitService(TraitPolicy(caution=TraitDriftPolicy(start=0.1, drift_rate=0.3, decision_gain=1.0)))
    effects = OutcomeEffectPolicy(effects={"causes_pain": {"safety": -40}})
    before = service.modulate({("o", "touch"): -10.0})[("o", "touch")]

    for _ in range(5):
        service.observe_interaction(expected=("pleasant",), observed=("causes_pain",), outcome_effects=effects)

    after = service.modulate({("o", "touch"): -10.0})[("o", "touch")]
    assert after < before < 0.0  # grown wary, the being now heeds the same memory more


# --- traits are observable on the being's state -------------------------------


def test_the_being_exposes_its_traits_on_the_state_snapshot():
    sim = _sim(contains=["obj_pillow"], traits=_traits_config())

    state = sim.tick()

    assert set(state["traits"]) == {"caution", "curiosity"}
    assert state["traits"] == sim.traits()

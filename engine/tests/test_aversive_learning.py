"""Behaviors: one-shot AVERSIVE concept learning, and the concept-derived BELIEF
feeding the being's decision (card AVERSIVE-LEARN).

Two gaps this pins closed, both observable through public surfaces:

- **Emotional-intensity-weighted concept confidence.** A confirming interaction
  the being felt intensely (a burn: high salience — emotional intensity and/or
  prediction error) contributes MORE to a concept's confidence, so ONE hot touch
  lifts `hot -> touch -> causes_pain` past a floor after a SINGLE piece of
  evidence (trauma-like one-shot learning) — where an ordinary, low-salience
  interaction still lands only the seed. Diminishing returns for ordinary
  repetition are preserved. Tuned in `config/learning_rates.yaml` only.

- **Beliefs feed the default decision path.** Even with the neural predictor OFF,
  the concept-derived belief that `touch` on a `hot` thing `causes_pain` raises
  that action's anticipated-discomfort cost in the decision, so a NEVER-SEEN hot
  object is avoided COGNITIVELY (with fear held constant — the being is calm, not
  scared — so the aversion is the belief, not the emotion). The belief bias
  composes with the v6 remembered-preference bias (it adds, never replaces), and
  it NEVER buys a blocked action past the safety floor.
"""
from __future__ import annotations

import pytest

from app.config_service import ConfigService
from app.domain.concept import ConceptSchema
from app.domain.memory import Memory
from app.repositories import (
    InMemoryBeliefRepository,
    InMemoryConceptRepository,
    InMemoryMemoryRepository,
)
from app.services.concept_service import ConceptService
from app.simulation import Simulation

_BEING = "being_001"


# --- one-shot aversive concept learning (ConceptService public surface) -------


def _learning_policy(*, seed=0.3, reinforce=0.2, intensity_gain=0.0):
    """A ConceptLearningPolicy resolved purely from config, so these tests pin the
    intensity-weighted curve to explicit values, not the shipped file."""
    return ConfigService.from_dict(
        tick_rates={},
        emotions={},
        learning_rates={
            "concept": {
                "learning": {
                    "seed_confidence": seed,
                    "reinforce_rate": reinforce,
                    "intensity_gain": intensity_gain,
                }
            }
        },
    ).concept_learning_policy()


def _burn_once(service: ConceptService, *, intensity: float) -> float:
    """Touch a hot thing ONCE at the given felt intensity; return the confidence of
    the learned `hot -> touch -> causes_pain` concept."""
    concepts = service.observe(
        being_id=_BEING,
        tick=1,
        object_id="obj_lamp",
        action="touch",
        perceived_properties=("hot",),
        observed_outcomes=("causes_pain",),
        intensity=intensity,
    )
    return next(c.confidence for c in concepts if c.outcome == "causes_pain")


def test_a_high_intensity_burn_clears_a_confidence_floor_after_one_evidence():
    service = ConceptService(InMemoryConceptRepository(), _learning_policy(intensity_gain=2.0))

    confidence = _burn_once(service, intensity=1.0)  # a scared-level, high-salience burn

    # one intense burn is learned in one shot — well past the 0.30 seed it would
    # freeze at today.
    assert confidence > 0.6


def test_an_ordinary_intensity_interaction_stays_at_the_seed_after_one_evidence():
    service = ConceptService(InMemoryConceptRepository(), _learning_policy(intensity_gain=2.0))

    confidence = _burn_once(service, intensity=0.0)  # a flat, low-salience interaction

    # with no felt intensity the being learns exactly as before: the seed only.
    assert confidence == pytest.approx(0.3)


def test_a_more_intense_experience_teaches_more_from_one_evidence():
    hi = _burn_once(
        ConceptService(InMemoryConceptRepository(), _learning_policy(intensity_gain=2.0)),
        intensity=1.0,
    )
    lo = _burn_once(
        ConceptService(InMemoryConceptRepository(), _learning_policy(intensity_gain=2.0)),
        intensity=0.2,
    )

    assert hi > lo


def test_ordinary_repetition_keeps_its_diminishing_returns():
    # intensity-blind (gain 0) repetition is byte-identical to the pre-slice curve:
    # confidence rises monotonically with a shrinking step.
    service = ConceptService(InMemoryConceptRepository(), _learning_policy(intensity_gain=2.0))
    steps = [_burn_once_repeat(service, tick) for tick in range(1, 5)]

    gains = [b - a for a, b in zip(steps, steps[1:])]
    assert steps == sorted(steps)  # monotonic
    assert gains == sorted(gains, reverse=True)  # each confirming step adds less


def _burn_once_repeat(service: ConceptService, tick: int) -> float:
    concepts = service.observe(
        being_id=_BEING,
        tick=tick,
        object_id=f"obj_ball_{tick}",
        action="push",
        perceived_properties=("round",),
        observed_outcomes=("rolls",),
        intensity=0.0,
    )
    return next(c.confidence for c in concepts if c.outcome == "rolls")


# --- config for the Simulation-level behaviors --------------------------------

_OBJECTS = {
    "properties": ["hot", "hard", "soft", "round", "red"],
    "affordances": ["look", "touch"],
    "objects": {
        "obj_hot": {
            "developerLabel": "Hot Lamp",
            "properties": ["hot", "hard"],
            "affordances": ["look", "touch"],
        },
        "obj_hot_new": {
            "developerLabel": "Strange Hot Thing",
            "properties": ["hot", "red"],
            "affordances": ["look", "touch"],
        },
    },
}

_OUTCOME_LABELS = {"labels": ["causes_pain", "scary", "pleasant", "rolls", "makes_noise"]}

_OUTCOME_EFFECTS = {
    "effects": {
        "causes_pain": {"pain": 45, "safety": -40, "comfort": -20},
        "scary": {"safety": -20},
    }
}

_EMOTIONS = {"rules": [{"emotion": "scared", "need": "safety", "op": "<=", "value": 30}], "default": "calm"}


def _needs(**overrides):
    levels = {"curiosity": 40, "safety": 80, "comfort": 70, "pain": 0}
    levels.update(overrides)
    return {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }


def _learning_rates(*, intensity_gain=2.0, discomfort_weight=0.0):
    return {
        "memory": {
            "priority": {
                "baseline": 0.0,
                "prediction_error_weight": 1.0,
                "emotion_intensity_weight": 1.0,
                "emotion_intensity": {"calm": 0.0, "scared": 1.0},
            }
        },
        "concept": {"learning": {"seed_confidence": 0.3, "reinforce_rate": 0.2, "intensity_gain": intensity_gain}},
        "belief": {"decision": {"discomfort_weight": discomfort_weight}},
    }


def _config(*, actions, room, safety=None, discomfort_weight=0.0, traits=None, needs=None):
    return ConfigService.from_dict(
        {"tick": {"duration_ms": 1000}, "needs": needs or _needs()},
        _EMOTIONS,
        rooms={"room": room},
        objects=_OBJECTS,
        actions=actions,
        safety=safety or {"rules": []},
        outcome=_OUTCOME_LABELS,
        outcome_effects=_OUTCOME_EFFECTS,
        learning_rates=_learning_rates(discomfort_weight=discomfort_weight),
        traits=traits,
    )


# --- Simulation one-shot: a single burn in a real run -------------------------


def test_a_single_burn_in_a_run_lifts_hot_causes_pain_past_the_floor():
    # touch dominates utility, so the being touches the hot lamp on tick 1; the
    # burn crashes felt safety into `scared`, a high-salience moment.
    actions = {
        "actions": {
            "touch": {
                "affordance": "touch",
                "utility": {"base": 5.0, "needs": {}, "emotions": {}},
                "property_outcomes": {"hot": ["causes_pain", "scary"]},
                "reason": "reaching out to touch",
            },
            "observe": {
                "affordance": "look",
                "utility": {"base": 1.0, "needs": {}, "emotions": {}},
                "expected_outcomes": ["pleasant"],
                "reason": "taking a look",
            },
        }
    }
    sim = Simulation(
        _config(actions=actions, room={"id": "room_001", "contains": ["obj_hot"]}),
        concept_repository=InMemoryConceptRepository(),
    )

    first = sim.tick()
    assert first["currentAction"]["type"] == "touch"  # it did touch (and got burned)
    assert first["emotion"] == "scared"  # the burn was felt intensely

    learned = next(
        c for c in sim.concepts() if c["feature"] == "hot" and c["outcome"] == "causes_pain"
    )
    assert learned["evidenceCount"] == 1  # a SINGLE burn
    assert learned["confidence"] > 0.6  # yet the concept is already strong


# --- belief -> decision: a never-seen hot object avoided cognitively ----------


def _seed_hot_concept(confidence: float) -> InMemoryConceptRepository:
    repo = InMemoryConceptRepository()
    repo.save(
        ConceptSchema(
            being_id=_BEING,
            feature="hot",
            action="touch",
            outcome="causes_pain",
            confidence=confidence,
            evidence_count=1,
        )
    )
    return repo


_TOUCH_TOP = {
    "actions": {
        "touch": {
            "affordance": "touch",
            "utility": {"base": 4.0, "needs": {}, "emotions": {}},
            "property_outcomes": {"hot": ["causes_pain", "scary"]},
            "reason": "reaching out to touch",
        },
        "observe": {
            "affordance": "look",
            "utility": {"base": 1.0, "needs": {}, "emotions": {}},
            "expected_outcomes": ["pleasant"],
            "reason": "taking a look instead",
        },
    }
}


def test_a_never_seen_hot_object_is_avoided_by_the_decision_via_belief():
    # The being has a strong `hot -> touch -> causes_pain` concept but has never met
    # THIS object. Fear held constant: safety is high, so it is calm (not scared) —
    # any avoidance is cognition, not emotion.
    sim = Simulation(
        _config(
            actions=_TOUCH_TOP,
            room={"id": "room_001", "contains": ["obj_hot_new"]},
            discomfort_weight=0.1,
        ),
        concept_repository=_seed_hot_concept(0.9),
        belief_repository=InMemoryBeliefRepository(),
    )

    assert sim.state()["emotion"] == "calm"  # the being decides while calm — fear held constant
    state = sim.tick()

    assert state["currentAction"]["type"] == "observe"  # touch was avoided cognitively


def test_without_the_belief_feed_the_same_object_is_touched():
    # Identical setup and identical (calm) emotion, only the belief feed turned OFF
    # (config discomfort_weight 0): touch's raw utility wins. This isolates the
    # belief's effect from everything else.
    sim = Simulation(
        _config(
            actions=_TOUCH_TOP,
            room={"id": "room_001", "contains": ["obj_hot_new"]},
            discomfort_weight=0.0,
        ),
        concept_repository=_seed_hot_concept(0.9),
        belief_repository=InMemoryBeliefRepository(),
    )

    assert sim.state()["emotion"] == "calm"  # decides under the same calm as the belief-on case
    state = sim.tick()

    assert state["currentAction"]["type"] == "touch"


def test_the_belief_feed_never_buys_a_blocked_touch_past_the_safety_floor():
    # touch has overwhelming utility AND a strong aversive belief — but a safety
    # rule hard-blocks touch on a hot surface. Neither utility nor belief can move
    # the floor: touch is never chosen and the block is visible in the reason.
    huge_touch = {
        "actions": {
            "touch": {
                "affordance": "touch",
                "utility": {"base": 50.0, "needs": {}, "emotions": {}},
                "property_outcomes": {"hot": ["causes_pain", "scary"]},
                "reason": "reaching out to touch",
            },
            "observe": {
                "affordance": "look",
                "utility": {"base": 1.0, "needs": {}, "emotions": {}},
                "expected_outcomes": ["pleasant"],
                "reason": "taking a look instead",
            },
        }
    }
    sim = Simulation(
        _config(
            actions=huge_touch,
            room={"id": "room_001", "contains": ["obj_hot_new"]},
            safety={"rules": [{"action": "touch", "blocked_property": "hot", "reason": "a hot surface would burn"}]},
            discomfort_weight=0.1,
        ),
        concept_repository=_seed_hot_concept(0.9),
        belief_repository=InMemoryBeliefRepository(),
    )

    state = sim.tick()

    assert state["currentAction"]["type"] == "observe"
    assert "block" in state["currentAction"]["reason"].lower()
    assert all(e["action"] != "touch" for e in sim.interactions())


def test_belief_avoidance_composes_with_a_remembered_burn_without_replacing_it():
    # touch leads observe by a wide utility margin. A remembered burn alone is not
    # enough to overturn it, and the concept-derived belief alone is not enough
    # either — but TOGETHER they are. Proves the two learned pulls compose (SUM)
    # rather than one masking the other.
    big_touch = {
        "actions": {
            "touch": {
                "affordance": "touch",
                "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                "property_outcomes": {"hot": ["causes_pain", "scary"]},
                "reason": "reaching out to touch",
            },
            "observe": {
                "affordance": "look",
                "utility": {"base": 1.0, "needs": {}, "emotions": {}},
                "expected_outcomes": ["pleasant"],
                "reason": "taking a look instead",
            },
        }
    }
    room = {"id": "room_001", "contains": ["obj_hot_new"]}
    memory = Memory(
        being_id=_BEING,
        tick=0,
        object_id="obj_hot_new",
        action="touch",
        perceived_properties=("hot", "red"),
        observed_outcome=("causes_pain",),
        emotion_before="calm",
        emotion_after="scared",
        priority=1.0,
    )
    # A remembered-preference weight and a belief-discomfort weight each sized to
    # about HALF the touch->observe utility gap, so each pulls touch down but leaves
    # it the winner on its own — only their sum crosses over.
    traits = {"preference": {"weight": 0.167}}

    def _tick(*, remember: bool, believe: bool):
        memory_repo = None
        if remember:
            memory_repo = InMemoryMemoryRepository()
            memory_repo.add(memory)
        sim = Simulation(
            _config(
                actions=big_touch,
                room=room,
                discomfort_weight=0.0926 if believe else 0.0,
                traits=traits,
            ),
            concept_repository=_seed_hot_concept(0.9),
            belief_repository=InMemoryBeliefRepository(),
            memory_repository=memory_repo,
        )
        return sim.tick()["currentAction"]["type"]

    assert _tick(remember=True, believe=False) == "touch"  # the burn alone: still touches
    assert _tick(remember=False, believe=True) == "touch"  # the belief alone: still touches
    assert _tick(remember=True, believe=True) == "observe"  # together they tip it over

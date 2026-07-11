"""Behaviors of curiosity, surprise, and the exploration policy (card v4).

The being preferentially explores what it cannot yet predict: curiosity toward a
perceived object rises with how NOVEL and UNCERTAIN it is and how recently it
SURPRISED the being, and falls with how FAMILIAR it has become. That exploration
signal then nudges the decision's action scoring — but only WITHIN the safety
floor (a learned/exploration score never rescues an action a safety rule blocks).

Everything is asserted through public surfaces: the `CuriosityService`,
`SurpriseService`, and `ExplorationPolicyService`; the `ConfigService`
(decision-weights are config-only); and end-to-end through `Simulation.state()`
/ `tick()` / `interactions()` and the `RenderStateService` frame. The seam is
ADR 0020 (extending the decision/utility + safety seam of ADR 0009).
"""
from __future__ import annotations

from app.config_service import ConfigService
from app.policies import CuriosityWeights, ExplorationPolicy, SurprisePolicy
from app.services.curiosity_service import CuriosityService
from app.services.exploration_policy_service import ExplorationPolicyService
from app.services.render_state_service import RenderStateService
from app.services.surprise_service import SurpriseService
from app.simulation import Simulation


# --- CuriosityService: novelty pulls curiosity up, familiarity pulls it down --


def _curiosity(**overrides) -> CuriosityService:
    weights = CuriosityWeights(
        novelty=1.0, uncertainty=0.6, recent_surprise=1.0, familiarity=0.8, familiarity_rate=0.3
    )
    return CuriosityService(weights)


def test_a_novel_object_draws_more_curiosity_than_a_familiar_one():
    service = _curiosity()
    # the being acts on a `round`/`red` object many times — it becomes familiar
    for _ in range(12):
        service.learn(("round", "red"))

    familiar = service.curiosity(perceived_properties=("round", "red"))
    novel = service.curiosity(perceived_properties=("square", "wooden"))  # never encountered

    assert novel > familiar


def test_recent_surprise_raises_curiosity():
    service = _curiosity()

    calm = service.curiosity(perceived_properties=("round",), recent_surprise=0.0)
    surprised = service.curiosity(perceived_properties=("round",), recent_surprise=1.0)

    assert surprised > calm


def test_retuning_curiosity_weights_is_config_only():
    # Same never-seen object, same code — only the novelty weight differs, and the
    # curiosity the being feels changes. Retuning temperament is a config change.
    def curiosity_for(novelty_weight: float) -> float:
        weights = CuriosityWeights(novelty=novelty_weight, uncertainty=0.6, recent_surprise=1.0, familiarity=0.8)
        return CuriosityService(weights).curiosity(perceived_properties=("square",))

    assert curiosity_for(2.0) > curiosity_for(0.5)


# --- SurpriseService: expected-as-observed is unsurprising; surprise decays ----


def test_an_outcome_exactly_as_predicted_is_unsurprising():
    service = SurpriseService(SurprisePolicy(decay=0.7))

    as_predicted = service.surprise(("rolls",), ("rolls",))
    a_mismatch = service.surprise(("pleasant",), ("causes_pain", "scary"))

    assert as_predicted == 0.0
    assert a_mismatch > 0.0


def test_recent_surprise_decays_over_ticks():
    service = SurpriseService(SurprisePolicy(decay=0.5))
    # a surprising interaction at tick 10 leaves a fresh trace ...
    service.record(object_id="obj_x", tick=10, expected=("pleasant",), observed=("causes_pain",))
    fresh = service.recent("obj_x", 10)
    later = service.recent("obj_x", 13)

    assert fresh > 0.0
    assert 0.0 <= later < fresh  # it fades as ticks pass


def test_retuning_surprise_decay_is_config_only():
    def recent_after(decay: float) -> float:
        service = SurpriseService(SurprisePolicy(decay=decay))
        service.record(object_id="o", tick=0, expected=("pleasant",), observed=("scary",))
        return service.recent("o", 5)

    # a slower decay keeps more of the surprise five ticks on — config only
    assert recent_after(0.9) > recent_after(0.3)


# --- ExplorationPolicyService: curiosity boosts, discomfort penalizes ---------


def _exploration(policy: ExplorationPolicy) -> ExplorationPolicyService:
    return ExplorationPolicyService(policy, _curiosity(), SurpriseService(SurprisePolicy()))


def test_higher_curiosity_boosts_an_actions_score():
    svc = _exploration(ExplorationPolicy(curiosity_weight=1.0, action_weights={"observe": 1.0}))

    low = svc.adjustment(action="observe", curiosity=0.1)
    high = svc.adjustment(action="observe", curiosity=0.9)

    assert high > low


def test_high_anticipated_discomfort_penalizes_touch():
    svc = _exploration(
        ExplorationPolicy(
            curiosity_weight=1.0, discomfort_weight=1.0, action_weights={"observe": 1.0, "touch": 1.0}
        )
    )

    observe = svc.adjustment(action="observe", curiosity=0.5, anticipated_discomfort=0.0)
    touch_hurts = svc.adjustment(action="touch", curiosity=0.5, anticipated_discomfort=5.0)
    touch_safe = svc.adjustment(action="touch", curiosity=0.5, anticipated_discomfort=0.0)

    # anticipated discomfort strictly lowers touch, and pushes it below observing
    assert touch_hurts < touch_safe
    assert touch_hurts < observe


def test_retuning_exploration_weight_is_config_only():
    def bonus(curiosity_weight: float) -> float:
        svc = _exploration(ExplorationPolicy(curiosity_weight=curiosity_weight, action_weights={"observe": 1.0}))
        return svc.adjustment(action="observe", curiosity=0.8)

    assert bonus(2.0) > bonus(0.5)


# --- ConfigService: the decision-weights section loads into typed policies -----


def test_decision_weights_load_into_typed_policies():
    config = ConfigService.from_dict(
        tick_rates={},
        emotions={},
        decision_weights={
            "curiosity": {"novelty": 2.0, "familiarity_rate": 0.4},
            "surprise": {"decay": 0.6},
            "exploration": {"curiosity_weight": 0.5, "action_weights": {"observe": 1.0}},
        },
    )

    assert config.curiosity_weights().novelty == 2.0
    assert config.curiosity_weights().familiarity_rate == 0.4
    assert config.surprise_policy().decay == 0.6
    assert config.exploration_policy().curiosity_weight == 0.5
    assert config.exploration_policy().action_weight("observe") == 1.0


def test_absent_decision_weights_make_exploration_inert():
    # No decision-weights section -> a purely utility-driven being (the pre-v4
    # baseline): the exploration adjustment is zero for every action.
    config = ConfigService.from_dict(tick_rates={}, emotions={})

    policy = config.exploration_policy()
    assert policy.curiosity_weight == 0.0
    assert policy.action_weight("observe") == 0.0


# --- end-to-end: exploration shifts the being toward what it understands least -

# two objects that share NO perceived property, so acting on one never makes the
# OTHER familiar; each affords only `look` (observe) plus the free approach.
_OBJECTS = {
    "properties": ["round", "square", "red", "wooden"],
    "affordances": ["look", "touch"],
    "objects": {
        "obj_round": {"developerLabel": "Round", "properties": ["round", "red"], "affordances": ["look"]},
        "obj_square": {"developerLabel": "Square", "properties": ["square", "wooden"], "affordances": ["look"]},
    },
}

_ACTIONS = {
    "actions": {
        "observe": {
            "affordance": "look",
            "utility": {"base": 2.0, "needs": {}, "emotions": {}},
            "expected_outcomes": ["pleasant"],
            "reason": "taking a look",
        },
    }
}

_EMOTIONS = {"rules": [], "default": "calm"}


def _needs():
    levels = {"curiosity": 40, "safety": 80, "comfort": 70}
    return {
        name: {"direction": "contextual", "amount": 0, "every_ticks": 1, "min": 0, "max": 100, "start": val}
        for name, val in levels.items()
    }


def _sim(*, contains, decision_weights, actions=_ACTIONS, objects=_OBJECTS, safety=None):
    tick_rates = {"tick": {"duration_ms": 1000}, "needs": _needs()}
    return Simulation(
        ConfigService.from_dict(
            tick_rates,
            _EMOTIONS,
            rooms={"room": {"id": "room_001", "contains": list(contains)}},
            objects=objects,
            actions=actions,
            safety=safety or {"rules": []},
            decision_weights=decision_weights,
        )
    )


_EXPLORING = {
    "curiosity": {"novelty": 1.0, "uncertainty": 0.6, "recent_surprise": 1.0, "familiarity": 0.8, "familiarity_rate": 0.5},
    "surprise": {"decay": 0.7},
    "exploration": {"curiosity_weight": 4.0, "action_weights": {"observe": 1.0}},
}
_UTILITY_ONLY = dict(_EXPLORING, exploration={"curiosity_weight": 0.0, "action_weights": {"observe": 1.0}})


def test_a_curious_being_spreads_its_attention_across_both_objects():
    sim = _sim(contains=["obj_round", "obj_square"], decision_weights=_EXPLORING)

    for _ in range(30):
        sim.tick()

    touched = {event["objectId"] for event in sim.interactions()}
    # curiosity pulls the being off the one it has come to understand and onto the
    # one it still cannot predict — so it engages BOTH, not just the first.
    assert touched == {"obj_round", "obj_square"}


def test_without_the_exploration_weight_the_being_fixates_on_one_object():
    # Same being, same objects — only the exploration weight is zeroed. The being
    # falls back to pure utility + deterministic tie-break and never leaves the
    # first object. Proves the shift is config-only.
    sim = _sim(contains=["obj_round", "obj_square"], decision_weights=_UTILITY_ONLY)

    for _ in range(30):
        sim.tick()

    touched = {event["objectId"] for event in sim.interactions()}
    assert touched == {"obj_round"}


def test_curiosity_never_buys_an_action_past_the_safety_floor():
    # A hot object the being is maximally curious about — yet a floor rule forbids
    # touching it. No curiosity bonus can rescue the blocked action.
    hot_objects = {
        "properties": ["hot", "hard"],
        "affordances": ["look", "touch"],
        "objects": {
            "obj_hot": {"developerLabel": "Hot", "properties": ["hot", "hard"], "affordances": ["look", "touch"]},
        },
    }
    touch_top = {
        "actions": {
            "touch": {
                "affordance": "touch",
                "utility": {"base": 10.0, "needs": {}, "emotions": {}},
                "property_outcomes": {"hot": ["causes_pain"]},
                "reason": "reaching out to touch",
            },
            "observe": {
                "affordance": "look",
                "utility": {"base": 1.0, "needs": {}, "emotions": {}},
                "expected_outcomes": ["pleasant"],
                "reason": "looking instead",
            },
        }
    }
    safety = {"rules": [{"action": "touch", "blocked_property": "hot", "reason": "a hot surface would cause pain"}]}
    sim = _sim(
        contains=["obj_hot"],
        decision_weights=_EXPLORING,
        actions=touch_top,
        objects=hot_objects,
        safety=safety,
    )

    for _ in range(20):
        sim.tick()

    # curiosity re-ranked the SAFE options, but the hot object is never touched
    assert sim.interactions()
    assert all(event["action"] != "touch" for event in sim.interactions())


# --- the render frame exposes curiosity and surprise --------------------------


def test_the_render_frame_exposes_curiosity_and_surprise():
    sim = _sim(contains=["obj_round", "obj_square"], decision_weights=_EXPLORING)
    hints = ConfigService.from_dict({}, {}, render_hints={"intensity_default": 0.5, "default": {}}).render_hints()
    renderer = RenderStateService(hints)

    sim.tick()
    frame = renderer.render(sim.state())

    assert "curiosity" in frame and isinstance(frame["curiosity"], dict)
    assert "surprise" in frame and isinstance(frame["surprise"], dict)
    # the being reports a curiosity toward each object it currently perceives
    assert set(frame["curiosity"]) == {"obj_round", "obj_square"}

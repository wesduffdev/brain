"""Behaviors of RenderStateService: mapping the domain state() snapshot onto the
ADR-0004 `being_state_update` frame.

Observable through the service's public `render()`. It adds the presentation-only
envelope (the frame `type`, a `visual` draw-hint block, a neutral `intensity`)
and makes NO psychology decision — the emotion is already derived upstream, and
the visual is a pure config lookup keyed by that emotion. The frame is
forward-compatible: unknown/future fields pass through and absent-until-later
fields (`pose`/`action`) stay absent (ADR 0004).
"""
from __future__ import annotations

from app.config_service import ConfigService
from app.services.render_state_service import RenderStateService

_HINTS = {
    "intensity_default": 0.5,
    "default": {"mouth": "neutral", "eyes": "neutral", "effects": [], "thought": ""},
    "emotions": {
        "curious": {"mouth": "small_open", "eyes": "wide", "effects": ["head_tilt"], "thought": "?"},
        "calm": {"mouth": "neutral", "eyes": "soft", "effects": [], "thought": ""},
    },
    "reactions": {
        "flinch": {"mouth": "open", "eyes": "wide", "effects": ["recoil"], "thought": "!"},
        "freeze": {"mouth": "neutral", "eyes": "wide", "effects": ["still"], "thought": ""},
    },
}


def _service() -> RenderStateService:
    return RenderStateService(ConfigService.from_dict({}, {}, render_hints=_HINTS).render_hints())


def _domain_state(**overrides) -> dict:
    state = {
        "beingId": "being_001",
        "tick": 42,
        "needs": {
            "hunger": 30,
            "sleep": 35,
            "comfort": 70,
            "warmth": 20,
            "curiosity": 72,
            "safety": 80,
        },
        "emotion": "curious",
    }
    state.update(overrides)
    return state


def _is_render_frame(frame: dict) -> bool:
    """The ADR-0004 `being_state_update` core: present and well-typed."""
    return (
        frame.get("type") == "being_state_update"
        and isinstance(frame.get("beingId"), str)
        and isinstance(frame.get("tick"), int)
        and isinstance(frame.get("emotion"), str)
        and isinstance(frame.get("needs"), dict)
        and isinstance(frame.get("visual"), dict)
    )


def test_a_known_state_maps_to_a_valid_being_state_update_frame():
    frame = _service().render(_domain_state())

    assert _is_render_frame(frame)
    # The domain data survives the mapping unchanged.
    assert frame["beingId"] == "being_001"
    assert frame["tick"] == 42
    assert frame["emotion"] == "curious"
    assert frame["needs"]["curiosity"] == 72


def test_the_frame_carries_a_neutral_intensity_until_the_emotion_model_has_one():
    frame = _service().render(_domain_state())

    assert isinstance(frame["intensity"], float)
    assert 0.0 <= frame["intensity"] <= 1.0


def test_visual_hints_are_a_config_mapping_from_emotion_not_a_decision():
    frame = _service().render(_domain_state(emotion="curious"))

    assert frame["visual"] == {
        "mouth": "small_open",
        "eyes": "wide",
        "effects": ["head_tilt"],
        "thought": "?",
    }


def test_an_unknown_emotion_falls_back_to_the_default_visual():
    frame = _service().render(_domain_state(emotion="whatever"))

    assert frame["visual"] == {"mouth": "neutral", "eyes": "neutral", "effects": [], "thought": ""}


def test_a_perceived_block_passes_through_when_present():
    perceived = {"objects": [{"objectId": "obj_red_ball", "confidence": 1.0}]}

    frame = _service().render(_domain_state(perceived=perceived))

    assert frame["perceived"] == perceived


def test_pose_and_action_are_absent_until_the_domain_supplies_them():
    frame = _service().render(_domain_state())

    assert "pose" not in frame
    assert "action" not in frame


def test_unknown_future_fields_pass_through_so_the_frame_can_grow():
    # Forward-compatibility: a field a later slice adds to state() (e.g. V0-4's
    # currentAction) flows onto the wire without a change here.
    frame = _service().render(_domain_state(currentAction="observe"))

    assert frame["currentAction"] == "observe"


def test_an_active_reaction_maps_into_the_visual_block_from_config():
    # INS-ACT surfaces state()["reaction"] = {type, intensity}; RenderStateService
    # presents it as visual.reaction, the config draw hints stamped with the
    # engine-decided type + intensity (a pure presentation lookup, no psychology).
    frame = _service().render(_domain_state(reaction={"type": "flinch", "intensity": 0.75}))

    assert frame["visual"]["reaction"] == {
        "type": "flinch",
        "intensity": 0.75,
        "mouth": "open",
        "eyes": "wide",
        "effects": ["recoil"],
        "thought": "!",
    }
    # The emotion face still drives the top-level visual hints alongside it.
    assert frame["visual"]["mouth"] == "small_open"


def test_a_reaction_of_an_unknown_label_still_carries_its_type_and_intensity():
    frame = _service().render(_domain_state(reaction={"type": "orient", "intensity": 0.4}))

    assert frame["visual"]["reaction"]["type"] == "orient"
    assert frame["visual"]["reaction"]["intensity"] == 0.4


def test_no_reaction_leaves_the_visual_block_free_of_a_reaction():
    frame = _service().render(_domain_state())

    assert "reaction" not in frame["visual"]

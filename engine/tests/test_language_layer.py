"""Behaviors of the natural-language layer (card v9, BRIEF §17): a natural-
language command maps ONLY to allowed actions, and narration/summaries turn
state into readable text WITHOUT ever changing simulation state — language sits
on top, never in control.

Everything is observed through the services' public surface. The LLM lives
behind the `LanguageModelPort` seam; every test drives the deterministic
`FakeLanguageModel`, so no real API call is ever made. The `Simulation` is a
black box here — read through its public `state()`, never mutated.
"""
from __future__ import annotations

import os

import pytest

from app.adapters.claude_language_model import ClaudeLanguageModel
from app.config_service import ConfigService
from app.domain.player_command import PlayerCommand
from app.ports.language_model import FakeLanguageModel
from app.services.action_validation_service import (
    ActionValidationError,
    ActionValidationService,
)
from app.services.language_command_service import (
    LanguageCommandError,
    LanguageCommandService,
)
from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def _sim() -> Simulation:
    return Simulation(_config())


def _visible(sim: Simulation) -> set:
    return {obj["objectId"] for obj in sim.state()["perceived"]["objects"]}


def _validator(config: ConfigService) -> ActionValidationService:
    return ActionValidationService(config.action_policies())


# --- LanguageCommandService: NL -> a validated, allowed action only ---------


def test_a_natural_language_command_maps_to_an_allowed_action():
    config = _config()
    service = LanguageCommandService(
        FakeLanguageModel(reply="touch obj_red_ball"), _validator(config)
    )

    command = service.interpret(
        "please reach out and touch the red ball", visible_object_ids={"obj_red_ball"}
    )

    assert command == PlayerCommand(command="touch", target_id="obj_red_ball")
    assert command.command in config.action_policies()


def test_an_unsupported_model_output_is_rejected():
    # The model 'invents' an action outside the vocabulary; the layer refuses it
    # rather than passing an unknown action through.
    config = _config()
    service = LanguageCommandService(
        FakeLanguageModel(reply="cast_spell obj_red_ball"), _validator(config)
    )

    with pytest.raises(LanguageCommandError):
        service.interpret("hex the ball", visible_object_ids={"obj_red_ball"})


def test_a_command_referencing_an_unseen_object_is_rejected():
    config = _config()
    service = LanguageCommandService(
        FakeLanguageModel(reply="touch obj_dragon"), _validator(config)
    )

    with pytest.raises(LanguageCommandError):
        service.interpret("touch the dragon", visible_object_ids={"obj_red_ball"})


def test_a_model_that_declines_to_map_is_rejected():
    config = _config()
    service = LanguageCommandService(
        FakeLanguageModel(reply="none"), _validator(config)
    )

    with pytest.raises(LanguageCommandError):
        service.interpret("do a barrel roll", visible_object_ids={"obj_red_ball"})


def test_interpreting_a_command_never_changes_the_simulation():
    # Language never controls the sim: producing a validated command is inert on
    # the being — its state only ever advances through tick().
    sim = _sim()
    for _ in range(5):
        sim.tick()
    before = sim.state()

    service = LanguageCommandService(
        FakeLanguageModel(reply="touch obj_red_ball"), _validator(_config())
    )
    command = service.interpret("touch the ball", visible_object_ids=_visible(sim))

    assert command.command == "touch"
    assert sim.state() == before


# --- NarrationService: state -> readable, non-authoritative log --------------


def test_narrating_a_state_does_not_mutate_the_simulation():
    sim = _sim()
    for _ in range(5):
        sim.tick()
    snapshot = sim.state()

    narration = NarrationService(
        FakeLanguageModel(reply="The being watches the objects nearby, feeling calm.")
    ).narrate(snapshot)

    assert isinstance(narration, str) and narration.strip()
    # Narration read the snapshot and produced text; the being is untouched.
    assert sim.state() == snapshot


def test_narration_is_built_from_the_state_it_is_given():
    # The echoing fake returns exactly the prompt it was handed, so a fact that
    # appears in the narration must have come from the snapshot, not been
    # invented — narration reflects state, it does not drive or override it.
    narration = NarrationService(FakeLanguageModel(echo=True)).narrate(
        {
            "emotion": "scared",
            "needs": {"safety": 12},
            "perceived": {"objects": [{"objectId": "obj_hot_lamp", "properties": ["hot"]}]},
        }
    )

    assert "scared" in narration
    assert "obj_hot_lamp" in narration


# --- MemorySummaryService: memories -> readable summary, read-only -----------


def test_a_memory_summary_reads_memories_without_changing_them():
    memories = [
        {"objectId": "obj_hot_lamp", "action": "touch", "observedOutcome": ["causes_pain"]},
        {"objectId": "obj_soft_blanket", "action": "touch", "observedOutcome": ["pleasant"]},
    ]
    original = [dict(m) for m in memories]

    summary = MemorySummaryService(FakeLanguageModel(echo=True)).summarize(memories)

    assert "obj_hot_lamp" in summary and "obj_soft_blanket" in summary
    assert memories == original  # the log the being keeps is untouched


# --- ActionValidationService: the guardrail ---------------------------------


def test_validation_rejects_an_action_outside_the_allowlist():
    validator = _validator(_config())

    with pytest.raises(ActionValidationError):
        validator.validate("fly", "obj_red_ball", visible_object_ids={"obj_red_ball"})


def test_validation_accepts_an_allowed_action_on_a_visible_object():
    validator = _validator(_config())

    command = validator.validate(
        "touch", "obj_red_ball", visible_object_ids={"obj_red_ball"}
    )

    assert command == PlayerCommand(command="touch", target_id="obj_red_ball")


def test_an_object_directed_action_requires_a_visible_target():
    validator = _validator(_config())

    with pytest.raises(ActionValidationError):
        validator.validate("touch", None, visible_object_ids={"obj_red_ball"})


# --- Claude adapter: env-gated, never called in tests -----------------------


def test_the_claude_adapter_needs_a_key_and_makes_no_call(monkeypatch):
    # Default provider is Claude, behind the same port; it is gated on
    # ANTHROPIC_API_KEY (like DATABASE_URL/JWT_SECRET) and never invoked by the
    # suite. With no key it refuses to build a client rather than call out.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError):
        ClaudeLanguageModel().complete("say hello")

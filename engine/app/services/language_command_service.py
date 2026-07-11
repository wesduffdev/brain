"""LanguageCommandService — turns a natural-language command into a validated,
allowed action (card v9, BRIEF §17).

This is the "interpret" half of the language layer. It asks the language model
(behind `LanguageModelPort`) to map a free-text command onto the being's action
vocabulary given what is currently in view, then runs the model's proposal
through `ActionValidationService`. The result is a validated `PlayerCommand`; a
proposal the model could not make, or one outside the allowed actions / not
aimed at a visible object, is rejected with `LanguageCommandError`.

Crucially, this service **never touches the simulation**. It reads what is
visible (passed in by the caller from `Simulation.state()`) and returns a
request; it does not apply it, and never reaches into the being's decision.
Language sits on top of the sim, never in control — the model's output is
untrusted text and the validator, not the model, is the guarantee.

The model is asked to answer in a strict one-line contract — ``none`` when it
cannot map the command, otherwise ``<action> [<target_id>]`` — so the reply
parses deterministically; the validator is the backstop regardless of what the
model returns.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from app.domain.player_command import PlayerCommand
from app.ports.language_model import LanguageModelPort
from app.services.action_validation_service import (
    ActionValidationError,
    ActionValidationService,
)

_DECLINE = "none"


class LanguageCommandError(ValueError):
    """A natural-language command could not be mapped to an allowed action:
    the model declined, its output did not parse, or the proposed action/target
    failed validation."""


class LanguageCommandService:
    def __init__(self, model: LanguageModelPort, validator: ActionValidationService):
        self._model = model
        self._validator = validator

    def interpret(
        self, text: str, *, visible_object_ids: Iterable[str]
    ) -> PlayerCommand:
        """Map ``text`` onto a validated, allowed `PlayerCommand`, or raise
        `LanguageCommandError`. Reads only what is visible; never mutates the
        simulation."""
        visible = set(visible_object_ids)
        prompt = self._prompt(text, visible)
        proposal = self._parse(self._model.complete(prompt))
        if proposal is None:
            raise LanguageCommandError(f"could not map command {text!r} to an action")
        action, target_id = proposal
        try:
            return self._validator.validate(
                action, target_id, visible_object_ids=visible
            )
        except ActionValidationError as exc:
            raise LanguageCommandError(str(exc)) from exc

    def _prompt(self, text: str, visible: set) -> str:
        objects = ", ".join(sorted(visible)) or "(nothing in view)"
        actions = ", ".join(self._validator.allowed_actions)
        return (
            "You map a person's request onto ONE action the being may take, or "
            "refuse it.\n"
            f"Allowed actions: {actions}\n"
            f"Objects currently in view: {objects}\n"
            f"Request: {text!r}\n"
            "Answer with a single line: 'none' if it maps to no allowed action, "
            "otherwise '<action> <object_id>' (omit the object for a self-"
            "directed action)."
        )

    @staticmethod
    def _parse(reply: str) -> Optional[Tuple[str, Optional[str]]]:
        tokens = reply.strip().split()
        if not tokens or tokens[0].lower() == _DECLINE:
            return None
        action = tokens[0].lower()
        target_id = tokens[1] if len(tokens) > 1 else None
        return action, target_id

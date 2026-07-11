"""ActionValidationService — the guardrail that keeps language mapped ONLY to
allowed actions (card v9, BRIEF §17).

The natural-language layer proposes an action from untrusted model output; this
service is the gate that turns a proposal into a validated command or refuses
it. It is the language layer's analogue of `CommandService` (ADR 0004), over the
being's *action* vocabulary (`config/actions.yaml`) rather than the player-
command vocabulary: an action must be one the being actually has, an object-
directed action must name a currently-visible object, and a named target must be
something the being can presently perceive. A validated result is a
`PlayerCommand` — a *request*, never an application: this service decides no
behavior and never touches the being's decision (BRIEF §17).

Anything the model invents outside the vocabulary, or aimed at an object that is
not in view, is rejected here — so a language command can never invent an action
or reach past the being's own psychology.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional, Tuple

from app.domain.player_command import PlayerCommand
from app.policies import ActionPolicy


class ActionValidationError(ValueError):
    """A proposed action was not allowed: unknown action, a missing required
    target, or a target the being cannot currently perceive."""


class ActionValidationService:
    def __init__(self, actions: Mapping[str, ActionPolicy]):
        self._actions = dict(actions)

    @property
    def allowed_actions(self) -> Tuple[str, ...]:
        """The action names language may map onto, in sorted order — the vocab
        a natural-language prompt is constrained to."""
        return tuple(sorted(self._actions))

    def validate(
        self,
        action: str,
        target_id: Optional[str],
        *,
        visible_object_ids: Iterable[str],
    ) -> PlayerCommand:
        """Return a validated `PlayerCommand` for an allowed action on a visible
        object, or raise `ActionValidationError`.

        An action must be in the being's vocabulary. A named target must be
        among the currently-visible objects. An object-directed action (one that
        needs an affordance, e.g. `touch`/`grab`) requires such a target; a free
        action (`approach`/`withdraw`) may carry a visible target or none.
        """
        policy = self._actions.get(action)
        if policy is None:
            raise ActionValidationError(f"unknown action {action!r}")

        visible = set(visible_object_ids)
        if target_id is not None and target_id not in visible:
            raise ActionValidationError(f"object {target_id!r} is not in view")

        if not policy.is_free and not target_id:
            raise ActionValidationError(f"action {action!r} needs an object to act on")

        return PlayerCommand(command=action, target_id=target_id)

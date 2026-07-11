"""ExplorationPolicyService — the being's exploration drive, in one place.

This coordinates the two cognitive signals of card v4 into the form the rest of
the being consumes. It owns a `CuriosityService` and a `SurpriseService` and the
`ExplorationPolicy` weights, and offers three things:

- `curiosity_map` / `surprise_map` — per perceived object, the being's current
  curiosity toward it (curiosity built on top of the object's decayed recent
  surprise) and that recent surprise itself; the Simulation exposes these on the
  render frame and feeds curiosity into the decision;
- `adjustment` — the score delta the DecisionService adds to a *safe* (action,
  object) candidate: a curiosity pull toward novel/uncertain objects minus an
  anticipated-discomfort push off actions the being expects to hurt. Because the
  decision applies it only after the safety floor has dropped blocked actions, a
  curiosity bonus can never rescue an action a safety rule forbids;
- `observe_interaction` — after the being acts, folds that interaction's surprise
  into the recent-surprise memory and makes the acted-on object's properties more
  familiar, so next tick's curiosity reflects what the being just learned.

Deleting this module would scatter the curiosity/surprise orchestration across
`Simulation._act` and `DecisionService`; it is the single facade both use for
"everything exploration", so the two collaborators and the weight math have one
home. Nothing here reads YAML — the weights arrive as typed policies.
"""
from __future__ import annotations

from typing import Dict, Mapping, Sequence

from app.policies import ExplorationPolicy
from app.services.curiosity_service import CuriosityService
from app.services.surprise_service import SurpriseService


class ExplorationPolicyService:
    def __init__(
        self, policy: ExplorationPolicy, curiosity: CuriosityService, surprise: SurpriseService
    ):
        self._policy = policy
        self._curiosity = curiosity
        self._surprise = surprise

    def curiosity_map(self, *, perceived: Sequence[Mapping], tick: int) -> Dict[str, float]:
        """The being's curiosity toward each object it currently perceives — built
        from the object's perceived properties and its decayed recent surprise."""
        return {
            obj["objectId"]: self._curiosity.curiosity(
                perceived_properties=obj.get("properties", []),
                recent_surprise=self._surprise.recent(obj["objectId"], tick),
            )
            for obj in perceived
        }

    def surprise_map(self, *, perceived: Sequence[Mapping], tick: int) -> Dict[str, float]:
        """The decayed recent surprise for each perceived object, as of `tick`."""
        return {obj["objectId"]: self._surprise.recent(obj["objectId"], tick) for obj in perceived}

    def adjustment(
        self, *, action: str, curiosity: float, anticipated_discomfort: float = 0.0
    ) -> float:
        """The exploration score delta for taking `action` on an object with this
        `curiosity` and `anticipated_discomfort`: a curiosity pull minus a
        discomfort push, both config-weighted. Positive means "explore it more"."""
        pull = self._policy.action_weight(action) * self._policy.curiosity_weight * float(curiosity)
        push = self._policy.discomfort_weight * float(anticipated_discomfort)
        return pull - push

    def observe_interaction(
        self,
        *,
        object_id: str,
        tick: int,
        expected: Sequence[str],
        observed: Sequence[str],
        perceived_properties: Sequence[str],
    ) -> None:
        """Learn from one interaction: record how surprising its outcome was and
        make the acted-on object's perceived properties more familiar, so the next
        tick's curiosity reflects it."""
        self._surprise.record(object_id=object_id, tick=tick, expected=expected, observed=observed)
        self._curiosity.learn(perceived_properties)

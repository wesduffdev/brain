"""DecisionService — chooses the being's one action each tick (ADR 0009).

Given the being's needs, its dominant emotion, the objects it currently
perceives, and which actions are resting on cooldown, it scores every valid
(action, object) pair by utility and picks the best — returning a `Decision`
(`action`, `targetId`, `emotion`, `reason`), or `None` when there is nothing to
do (no perceived object, or every candidate blocked or on cooldown).

Safety is not something this service weighs; it *obeys* it. It asks the injected
SafetyService about each candidate and drops any that is blocked before ranking,
so a high score can never bypass a guardrail (BRIEF §12: "learned predictions
never bypass safety"). When a would-be top choice was blocked, the chosen action
says so in its reason. All the numbers live in `config/actions.yaml`; this
service holds none — retuning what the being tends to do is a config change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Set

from app.domain.decision import Decision
from app.policies import ActionPolicy
from app.services.safety_service import SafetyService


@dataclass(frozen=True)
class _Candidate:
    score: float
    order: int
    object_id: str
    action: str
    reason: str


class DecisionService:
    def __init__(self, actions: Mapping[str, ActionPolicy], safety: SafetyService):
        # Preserve authored order so ties break deterministically by config order.
        self._actions = dict(actions)
        self._order = {name: i for i, name in enumerate(self._actions)}
        self._safety = safety

    def decide(
        self,
        *,
        needs: Mapping[str, int],
        emotion: str,
        perceived: Sequence[Mapping],
        on_cooldown: Set[str],
    ) -> Optional[Decision]:
        selectable: list = []
        blocked_top: Optional[_Candidate] = None

        for obj in perceived:
            object_id = obj["objectId"]
            properties = obj.get("properties", [])
            affordances = set(obj.get("affordances", []))
            for name, policy in self._actions.items():
                if not policy.is_free and policy.affordance not in affordances:
                    continue
                score = policy.score(needs, emotion)
                block = self._safety.block_reason(name, properties)
                if block is not None:
                    candidate = _Candidate(score, self._order[name], object_id, name, block)
                    if blocked_top is None or score > blocked_top.score:
                        blocked_top = candidate
                    continue
                if name in on_cooldown:
                    continue
                selectable.append(_Candidate(score, self._order[name], object_id, name, policy.reason))

        if not selectable:
            return None

        selectable.sort(key=lambda c: (-c.score, c.order, c.object_id))
        chosen = selectable[0]

        reason = chosen.reason
        if blocked_top is not None and blocked_top.score > chosen.score:
            reason = (
                f"{reason} (a higher-scoring {blocked_top.action} was blocked: "
                f"{blocked_top.reason})"
            )

        return Decision(action=chosen.action, target_id=chosen.object_id, emotion=emotion, reason=reason)

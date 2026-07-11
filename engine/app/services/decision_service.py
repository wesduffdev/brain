"""DecisionService — chooses the being's one action each tick (ADR 0009, ADR
0011 extended by card v3).

Given the being's needs, its dominant emotion, the objects it currently
perceives, and which actions are resting on cooldown, it scores every valid
(action, object) pair by utility and picks the best — returning a `Decision`
(`action`, `targetId`, `emotion`, `reason`), or `None` when there is nothing to
do (no perceived object, or every candidate blocked or on cooldown).

When an outcome **predictor** is injected (prediction is *active* — card v3), the
being also anticipates each safe action's outcomes: the predictor gives a blended
neural+rule probability per outcome, and the anticipated aversive cost of those
outcomes (`OutcomeEffectPolicy.anticipated_cost`) is subtracted from the action's
utility — so the being can learn to avoid an action it predicts will hurt. With
no predictor, the being decides on raw utility exactly as before (shadow).

Safety is not something this service weighs; it *obeys* it. It asks the injected
SafetyService about each candidate and drops any that is blocked before ranking,
so neither a high utility nor a confident learned prediction can bypass a
guardrail (BRIEF §12: "learned predictions never bypass safety") — the prediction
only ever reshuffles the *safe* candidates. When a would-be top choice was
blocked, the chosen action says so in its reason. All the numbers live in
`config/*.yaml`; this service holds none.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Set

from app.domain.decision import Decision
from app.ml.encode_features import Example
from app.policies import ActionPolicy, OutcomeEffectPolicy
from app.ports.predictor import PredictorPort
from app.services.safety_service import SafetyService


@dataclass(frozen=True)
class _Candidate:
    score: float
    order: int
    object_id: str
    action: str
    reason: str


class DecisionService:
    def __init__(
        self,
        actions: Mapping[str, ActionPolicy],
        safety: SafetyService,
        *,
        predictor: Optional[PredictorPort] = None,
        outcome_effects: Optional[OutcomeEffectPolicy] = None,
    ):
        # Preserve authored order so ties break deterministically by config order.
        self._actions = dict(actions)
        self._order = {name: i for i, name in enumerate(self._actions)}
        self._safety = safety
        # Active prediction (card v3): both are present together or neither is.
        self._predictor = predictor
        self._outcome_effects = outcome_effects or OutcomeEffectPolicy()

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
                # Prediction is active only for the SAFE candidates — it can never
                # rescue a blocked one, so a learned score cannot bypass safety.
                score -= self._anticipated_cost(policy, properties)
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

    def _anticipated_cost(self, policy: ActionPolicy, properties: Sequence[str]) -> float:
        """The anticipated aversive cost of taking `policy` on an object with
        `properties`, from the blended prediction — 0.0 when prediction is off."""
        if self._predictor is None:
            return 0.0
        example = Example(
            properties=tuple(properties),
            action=policy.affordance or "",
            context=(),
        )
        probabilities = self._predictor.predict_outcomes(example)
        return self._outcome_effects.anticipated_cost(probabilities)

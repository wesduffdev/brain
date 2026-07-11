"""NeedService — the one place the being's needs change and stay in band.

Two forces move needs, both config-driven and both clamped to each need's band
(`tick_rates.yaml` is the single home for a need's floor/ceiling):

- `apply`     — autonomous drift over time (a deficit growing, a good state
                fading), from the NeedTickPolicy set.
- `apply_outcomes` — the felt consequence of an action's observed outcomes
                (ADR 0014): a harmful outcome (`causes_pain`) raises pain and
                lowers felt safety/comfort at once, from the OutcomeEffectPolicy.
                This is event-driven, not tick-gated — the consequence lands the
                moment the action does.

It holds no numbers of its own: every rate and delta comes from config, so
retuning temperament or how much harm hurts never touches this code.
"""
from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional

from app.policies import CONTEXTUAL, INCREASE, NeedBands, NeedTickPolicy, OutcomeEffectPolicy


class NeedService:
    def __init__(
        self,
        policies: Mapping[str, NeedTickPolicy],
        effects: Optional[OutcomeEffectPolicy] = None,
    ):
        self._policies = dict(policies)
        self._effects = effects or OutcomeEffectPolicy()
        # A need's floor/ceiling knowledge lives in one place, not inline here.
        self._bands = NeedBands.from_policies(self._policies)

    def apply(self, needs: Mapping[str, int], tick: int) -> Dict[str, int]:
        """Return the needs after this tick's drift. Pure: it copies rather
        than mutating the input. Tick 0 is the birth state and never drifts."""
        updated: Dict[str, int] = dict(needs)
        if tick <= 0:
            return updated

        for name, policy in self._policies.items():
            if name not in updated:
                continue
            # A contextual need has no autonomous drift; the world moves it
            # in a later slice.
            if policy.direction == CONTEXTUAL:
                continue
            if policy.every_ticks <= 0 or tick % policy.every_ticks != 0:
                continue
            step = policy.amount if policy.direction == INCREASE else -policy.amount
            updated[name] = self._bands.clamp(name, updated[name] + step)
        return updated

    def apply_outcomes(self, needs: Mapping[str, int], outcomes: Iterable[str]) -> Dict[str, int]:
        """Return the needs after the felt consequence of `outcomes` lands (ADR
        0014) — the being touched something hot, so pain spikes and felt safety
        and comfort fall. Pure: it copies rather than mutating. Each moved need
        is clamped to its own band; a need with no configured band moves
        unclamped (never happens for the shipped needs)."""
        updated: Dict[str, int] = dict(needs)
        for name, delta in self._effects.deltas_for(outcomes).items():
            if name not in updated or delta == 0:
                continue
            updated[name] = self._bands.clamp(name, updated[name] + delta)
        return updated

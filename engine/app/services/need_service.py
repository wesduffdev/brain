"""NeedService — applies need drift from policies, and clamps.

It holds no rates of its own: every number comes from the NeedTickPolicy set it
was built with (which came from config). Change a rate in `tick_rates.yaml` and
this code does not move. That is the fine-tuning isolation the brief requires.
"""
from __future__ import annotations

from typing import Dict, Mapping

from app.policies import CONTEXTUAL, INCREASE, NeedTickPolicy


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


class NeedService:
    def __init__(self, policies: Mapping[str, NeedTickPolicy]):
        self._policies = dict(policies)

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
            updated[name] = _clamp(
                updated[name] + step, policy.min_value, policy.max_value
            )
        return updated

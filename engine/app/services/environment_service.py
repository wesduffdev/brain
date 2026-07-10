"""EnvironmentService — lets the room's environmental conditions move the
being's *contextual* needs.

Contextual needs (safety, warmth) have no drift of their own; the NeedService
deliberately leaves them alone. This service is what moves them: given the room
the being is in and the current tick, it reads the room's conditions (light,
sound, temperature), resolves them against the environment policy into per-need
deltas, and applies those deltas — clamped to each need's own band. A dark or
loud room pushes safety down until `scared` becomes the dominant emotion; a
comfortable room pushes nothing (ADR 0006).

It holds no numbers of its own: the deltas and cadence come from the
EnvironmentPolicy (config), and the clamp bands come from the need policies —
the single source of truth for a need's floor/ceiling stays `tick_rates.yaml`.
"""
from __future__ import annotations

from typing import Dict, Mapping, Tuple

from app.domain.room import Room
from app.policies import EnvironmentPolicy, NeedTickPolicy


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


class EnvironmentService:
    def __init__(
        self,
        policy: EnvironmentPolicy,
        need_policies: Mapping[str, NeedTickPolicy],
    ):
        self._policy = policy
        self._bands: Dict[str, Tuple[int, int]] = {
            name: (p.min_value, p.max_value) for name, p in need_policies.items()
        }

    def apply(self, needs: Mapping[str, int], room: Room, tick: int) -> Dict[str, int]:
        """Return the needs after this tick's environmental push. Pure: it copies
        rather than mutating. Tick 0 is the birth state and never moves; deltas
        land only when `tick % every_ticks == 0`. A need with no configured band
        is left unclamped (never happens for the contextual needs, which do have
        bands)."""
        updated: Dict[str, int] = dict(needs)
        # Resolve (and so validate) the room's conditions every tick — a typo'd
        # category fails loudly at once, not only on a cadence tick.
        deltas = self._policy.deltas_for(room.conditions())
        if tick <= 0:
            return updated
        if self._policy.every_ticks <= 0 or tick % self._policy.every_ticks != 0:
            return updated

        for need_name, delta in deltas.items():
            if need_name not in updated or delta == 0:
                continue
            moved = updated[need_name] + delta
            band = self._bands.get(need_name)
            updated[need_name] = _clamp(moved, band[0], band[1]) if band else moved
        return updated

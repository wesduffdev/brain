"""BeingState — the being's minimal runtime state for this slice.

Just what it needs to have: an identity, a set of needs, and a dominant
emotion. No age, no life-stage, no caregiver. The services own the rules that
move this state; the being is the state, not the behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class BeingState:
    being_id: str
    needs: Dict[str, int] = field(default_factory=dict)
    emotion: str = "calm"

    def snapshot(self, tick: int) -> Dict:
        """A plain, serializable view of the being at `tick`. This is the shape
        the (future) API and renderer will consume, so it uses stable
        camelCase keys."""
        return {
            "beingId": self.being_id,
            "tick": tick,
            "needs": dict(self.needs),
            "emotion": self.emotion,
        }

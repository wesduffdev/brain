"""Decision — the being's choice of one action toward one object this tick.

The output of the DecisionService (ADR 0009): which `action` the being takes, on
which `target_id`, the `emotion` it felt while deciding, and a human-readable
`reason`. It is the being's own doing — self-/world-directed only, never aimed at
a caregiver. It carries no scoring internals; those stay inside the service.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Decision:
    action: str
    target_id: str
    emotion: str
    reason: str

    def as_output(self) -> Dict:
        """The `{action, targetId, emotion, reason}` shape the brief names as the
        decision system's output (BRIEF §12)."""
        return {
            "action": self.action,
            "targetId": self.target_id,
            "emotion": self.emotion,
            "reason": self.reason,
        }

    def as_current_action(self) -> Dict:
        """The `currentAction` block `state()` exposes: `{type, targetId, reason}`
        — the emotion is already reported at the top level of the snapshot."""
        return {"type": self.action, "targetId": self.target_id, "reason": self.reason}

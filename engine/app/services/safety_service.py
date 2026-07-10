"""SafetyService — the invariant floor on what the being may do (ADR 0009,
narrowed by ADR 0013/0014).

It answers one question: is taking this action on an object with these perceived
properties forbidden? It is deliberately separate from the DecisionService so the
floor is absolute — the decision layer asks it about every candidate and drops
any it blocks, so a high utility (or, later, a confident learned prediction) can
never buy its way past it. The rules live in `config/safety_rules.yaml`; this
service holds no thresholds of its own.

The floor blocks only genuinely *simulation-breaking* actions, not merely harmful
ones: recoverable-but-harmful actions (touching something hot) are allowed and
their harm lands as felt consequences on the being's needs (see
`OutcomeEffectPolicy`), not as a block — that is how the being learns cause and
effect. In v0 nothing is simulation-breaking, so the floor is empty and this
service permits everything; the seam stays so a rule can reinstate a hard block.
Per the design boundary, any rule's reason is abstract and human-readable — never
any depiction of harm.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from app.policies import SafetyRule


class SafetyService:
    def __init__(self, rules: Sequence[SafetyRule]):
        self._rules = tuple(rules)

    def block_reason(self, action: str, properties: Iterable[str]) -> Optional[str]:
        """The reason `action` is forbidden on an object with `properties`, or
        None if it is permitted. First matching rule wins."""
        present = set(properties)
        for rule in self._rules:
            if rule.action == action and rule.blocked_property in present:
                return rule.reason
        return None

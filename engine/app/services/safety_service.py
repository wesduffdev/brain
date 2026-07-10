"""SafetyService — the hard guardrail on what the being may do (ADR 0009).

It answers one question: is taking this action on an object with these perceived
properties forbidden? It is deliberately separate from the DecisionService so the
guardrail is absolute — the decision layer asks it about every candidate and
drops any it blocks, so a high utility (or, later, a confident learned
prediction) can never buy its way past safety. The rules live in
`config/safety_rules.yaml`; this service holds no thresholds of its own.

Per the design boundary, a blocked action carries an abstract, human-readable
reason (a hot surface would cause pain) — never any depiction of harm.
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

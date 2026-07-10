"""EmotionService — derives the one dominant emotion from the being's needs.

The rules come from config (`emotions.yaml`). They are evaluated in order and
the first match wins, so the file's ordering encodes priority: fear before
hunger, hunger before curiosity, and so on. No emotion is ever set by hand.
"""
from __future__ import annotations

import operator
from typing import Callable, Dict, Mapping, Sequence

from app.policies import EmotionRule

_OPS: Dict[str, Callable[[int, int], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
}


class EmotionService:
    def __init__(self, rules: Sequence[EmotionRule], default: str = "calm"):
        for rule in rules:
            if rule.op not in _OPS:
                raise ValueError(f"emotion rule for {rule.emotion!r}: unknown op {rule.op!r}")
        self._rules = list(rules)
        self._default = default

    def derive(self, needs: Mapping[str, int]) -> str:
        for rule in self._rules:
            if rule.need in needs and _OPS[rule.op](needs[rule.need], rule.value):
                return rule.emotion
        return self._default

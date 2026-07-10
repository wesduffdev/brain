"""TickService — owns the passage of time and nothing else.

It knows the current tick and how to advance one step. It does NOT know how
any need drifts or which emotion follows; that keeps time a single, trivially
testable concept. In tests you advance it by hand; a real loop (a later slice)
will advance it on a timer.
"""
from __future__ import annotations


class TickService:
    def __init__(self, start: int = 0):
        self._tick = start

    @property
    def current_tick(self) -> int:
        return self._tick

    def advance(self) -> int:
        self._tick += 1
        return self._tick

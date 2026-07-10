"""ClockPort — the passage of real time, made injectable.

The tick loop asks the clock to wait between frames; it does not care how the
waiting happens. Production waits on the wall clock (`WallClock`); tests inject
a fake clock so the stream is deterministic and no real time passes. This is
the one seam introduced for transport: it exists because wall-clock time and a
controllable test clock genuinely vary across it (ADR 0003, reassessing the
note left open in ADR 0001).
"""
from __future__ import annotations

import asyncio
from typing import Protocol


class ClockPort(Protocol):
    """Something that can pause the tick loop for a while."""

    async def sleep(self, seconds: float) -> None:
        """Wait roughly `seconds` before returning control to the loop."""
        ...


class WallClock:
    """The production clock: waits real time on the event loop."""

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

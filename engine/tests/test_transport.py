"""Behaviors of the transport surface.

Observable through the public HTTP/WebSocket boundary: `GET /state` returns the
being's current snapshot, and the WebSocket endpoint streams one `state()` frame
per tick. Time is injected through a clock seam, so tests drive a fake clock —
no real time passes and the stream is deterministic.

`/state` and `/ws` are now behind JWT auth (V0-SEC, ADR 0005); the suite runs
with auth on (see `conftest.py`), so these tests present a token minted by the
`mint` fixture. The generic-serialization behavior is unchanged.
"""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.config_service import ConfigService
from app.main import create_app
from app.simulation import Simulation


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _tiny_config() -> ConfigService:
    """A minimal, fully deterministic being: hunger rises by 1 every tick."""
    tick_rates = {
        "tick": {"duration_ms": 1000},
        "needs": {
            "hunger": {
                "direction": "increase",
                "amount": 1,
                "every_ticks": 1,
                "min": 0,
                "max": 100,
                "start": 10,
            },
        },
    }
    emotions = {"rules": [], "default": "calm"}
    return ConfigService.from_dict(tick_rates, emotions)


class _StubSimulation:
    """A being at the Simulation seam whose snapshot carries fields the core
    does not have today (a `perceived` block, `currentAction`). It proves the
    transport serializes whatever `state()` returns, not a fixed field list, so
    it survives later slices growing the snapshot."""

    def __init__(self) -> None:
        self._tick = 0

    def state(self) -> dict:
        return {
            "tick": self._tick,
            "perceived": {"obj_red_ball": 0.8},
            "currentAction": "observe",
            "surprised": True,
        }

    def tick(self) -> dict:
        self._tick += 1
        return self.state()


class _CountingClock:
    """A test clock through which no real time passes. It permits `allowed`
    waits and then blocks until the server task is cancelled, so the stream
    produces a bounded, deterministic number of frames without sleeping."""

    def __init__(self, allowed: int) -> None:
        self._remaining = allowed
        self.waits = 0

    async def sleep(self, seconds: float) -> None:
        self.waits += 1
        if self._remaining > 0:
            self._remaining -= 1
            return
        await asyncio.Event().wait()  # block until the server task is cancelled


def test_state_endpoint_returns_the_current_snapshot(mint):
    sim = Simulation(_tiny_config())
    client = TestClient(create_app(simulation=sim, tick_interval_seconds=0))

    resp = client.get("/state", headers=_bearer(mint()))

    assert resp.status_code == 200
    assert resp.json() == sim.state()  # the current snapshot, unadvanced


def test_state_endpoint_serializes_whatever_the_snapshot_contains(mint):
    # A snapshot with fields the current core never emits must still round-trip.
    client = TestClient(create_app(simulation=_StubSimulation(), tick_interval_seconds=0))

    body = client.get("/state", headers=_bearer(mint())).json()

    assert body["perceived"] == {"obj_red_ball": 0.8}
    assert body["currentAction"] == "observe"
    assert body["surprised"] is True


def test_stream_pushes_one_state_frame_per_tick_with_increasing_tick(mint):
    sim = Simulation(_tiny_config())
    reference = Simulation(_tiny_config())  # identical config → identical drift
    app = create_app(simulation=sim, clock=_CountingClock(allowed=3), tick_interval_seconds=0)
    client = TestClient(app)

    with client.websocket_connect(f"/ws?token={mint()}") as ws:
        frames = [ws.receive_json() for _ in range(3)]

    ticks = [f["tick"] for f in frames]
    assert ticks == [1, 2, 3]
    assert all(b > a for a, b in zip(ticks, ticks[1:]))  # strictly increasing
    # Each frame is exactly what state() produced for that tick.
    assert frames == [reference.tick() for _ in range(3)]

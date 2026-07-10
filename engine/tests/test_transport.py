"""Behaviors of the transport surface.

Observable through the public HTTP/WebSocket boundary: `GET /state` returns the
being's current domain snapshot, the WebSocket endpoint streams one mapped
ADR-0004 `being_state_update` frame per tick (via RenderStateService), and
`POST /command` accepts a `player_command` validated by CommandService. Time is
injected through a clock seam, so tests drive a fake clock — no real time passes
and the stream is deterministic.

`/state`, `/ws`, and `/command` are behind JWT auth (V0-SEC, ADR 0005); the suite
runs with auth on (see `conftest.py`), so these tests present a token minted by
the `mint` fixture. The generic-serialization behavior of `/state` is unchanged.
"""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.config_service import ConfigService
from app.main import create_app
from app.services.command_service import CommandService
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


_COMMANDS = {"commands": {"present_object": {"requires_target": True}}}


def _command_service() -> CommandService:
    specs = ConfigService.from_dict({}, {}, commands=_COMMANDS).command_specs()
    return CommandService(specs, ("obj_red_ball",))


def _app_with_commands() -> TestClient:
    return TestClient(
        create_app(
            simulation=Simulation(_tiny_config()),
            command_service=_command_service(),
            tick_interval_seconds=0,
        )
    )


def test_stream_emits_one_mapped_being_state_update_frame_per_tick(mint):
    sim = Simulation(_tiny_config())
    app = create_app(simulation=sim, clock=_CountingClock(allowed=3), tick_interval_seconds=0)
    client = TestClient(app)

    with client.websocket_connect(f"/ws?token={mint()}") as ws:
        frames = [ws.receive_json() for _ in range(3)]

    ticks = [f["tick"] for f in frames]
    assert ticks == [1, 2, 3]
    assert all(b > a for a, b in zip(ticks, ticks[1:]))  # strictly increasing
    # Each frame is the ADR-0004 render frame, not the raw domain snapshot.
    assert all(f["type"] == "being_state_update" for f in frames)
    assert all(isinstance(f["visual"], dict) for f in frames)
    # The domain data still rides along inside the mapped frame.
    assert all("needs" in f and "emotion" in f for f in frames)


def test_a_valid_player_command_is_accepted(mint):
    client = _app_with_commands()

    resp = client.post(
        "/command",
        headers=_bearer(mint()),
        json={"type": "player_command", "command": "present_object", "targetId": "obj_red_ball"},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert resp.json()["targetId"] == "obj_red_ball"


def test_an_unknown_command_is_rejected(mint):
    client = _app_with_commands()

    resp = client.post(
        "/command",
        headers=_bearer(mint()),
        json={"type": "player_command", "command": "teleport", "targetId": "obj_red_ball"},
    )

    assert resp.status_code == 422


def test_a_command_without_a_token_is_rejected():
    client = _app_with_commands()

    resp = client.post(
        "/command",
        json={"type": "player_command", "command": "present_object", "targetId": "obj_red_ball"},
    )

    assert resp.status_code == 401

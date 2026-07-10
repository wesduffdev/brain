"""Behaviors of the engine's API authentication (V0-SEC).

Observable through the HTTP/WS boundary: `/health` is public, `/state` and the
tick stream require a verified JWT (HS256; signature + expiry + issuer +
audience), and the app mints tokens its own guard accepts (the service-token
loop). Auth is always in the code path; the test environment turns it on via the
`_auth_env` fixture in `conftest.py`. These tests state the security contract
Wave 2 builds on.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app


class _StubSim:
    """A minimal being at the Simulation seam, so these tests exercise auth and
    transport without depending on config or psychology."""

    def __init__(self) -> None:
        self._tick = 0

    def state(self) -> dict:
        return {"tick": self._tick, "emotion": "calm"}

    def tick(self) -> dict:
        self._tick += 1
        return self.state()


class _CountingClock:
    """Lets a bounded number of waits through, then blocks until the server task
    is cancelled — a deterministic, sleepless stream (as in test_transport)."""

    def __init__(self, allowed: int) -> None:
        self._remaining = allowed

    async def sleep(self, seconds: float) -> None:
        if self._remaining > 0:
            self._remaining -= 1
            return
        await asyncio.Event().wait()


def _client() -> TestClient:
    return TestClient(create_app(simulation=_StubSim(), tick_interval_seconds=0))


def _ws_client(allowed: int = 3) -> TestClient:
    return TestClient(
        create_app(simulation=_StubSim(), clock=_CountingClock(allowed), tick_interval_seconds=0)
    )


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_is_public_and_needs_no_token():
    resp = _client().get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_state_without_a_token_is_rejected():
    resp = _client().get("/state")

    assert resp.status_code == 401


def test_state_with_a_valid_token_returns_the_snapshot(mint):
    resp = _client().get("/state", headers=_bearer(mint()))

    assert resp.status_code == 200
    assert resp.json()["emotion"] == "calm"


def test_state_accepts_a_token_minted_by_the_app():
    # The app's own minting path (behind `make token`) yields a token its guard
    # accepts — the service-token loop, end to end.
    token = auth.mint_token(auth.AuthConfig.from_env())

    resp = _client().get("/state", headers=_bearer(token))

    assert resp.status_code == 200


def test_expired_token_is_rejected(mint):
    expired = mint(expires_at=datetime.now(timezone.utc) - timedelta(seconds=5))

    resp = _client().get("/state", headers=_bearer(expired))

    assert resp.status_code == 401


def test_token_with_a_bad_signature_is_rejected(mint):
    forged = mint(secret="attacker-secret")

    resp = _client().get("/state", headers=_bearer(forged))

    assert resp.status_code == 401


def test_tampered_token_is_rejected(mint):
    good = mint()
    tampered = good[:-3] + ("abc" if good[-3:] != "abc" else "xyz")

    resp = _client().get("/state", headers=_bearer(tampered))

    assert resp.status_code == 401


def test_wrong_issuer_is_rejected(mint):
    resp = _client().get("/state", headers=_bearer(mint(issuer="evil-corp")))

    assert resp.status_code == 401


def test_wrong_audience_is_rejected(mint):
    resp = _client().get("/state", headers=_bearer(mint(audience="some-other-service")))

    assert resp.status_code == 401


def test_ws_rejects_a_bad_token_at_handshake():
    client = _ws_client()

    with client.websocket_connect("/ws?token=not-a-real-token") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()

    assert exc.value.code == 1008


def test_ws_accepts_a_valid_token_and_streams_frames(mint):
    client = _ws_client(allowed=3)

    with client.websocket_connect(f"/ws?token={mint()}") as ws:
        frames = [ws.receive_json() for _ in range(3)]

    assert [f["tick"] for f in frames] == [1, 2, 3]


def test_auth_disabled_makes_state_public(monkeypatch):
    # Documented dev-only no-op: with AUTH_REQUIRED false the guard lets /state
    # through without a token. There is no localhost bypass — only this flag.
    monkeypatch.setenv("AUTH_REQUIRED", "false")

    resp = _client().get("/state")

    assert resp.status_code == 200

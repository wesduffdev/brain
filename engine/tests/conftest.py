"""Shared fixtures for the engine suite.

The security slice (V0-SEC) adds two seams the tests need. The auth module reads
its config from the environment — deploy/secret config like `DATABASE_URL`, not
authored YAML — so `_auth_env` pins a known secret and issuer/audience for the
whole suite and turns auth on. `mint` signs tokens with that same secret through
one door, with overrides so a test can forge an expired, wrong-issuer,
wrong-audience, or bad-signature token.

`_hermetic_database_url` closes a subtler hole in the same seam: `build_simulation`
wires Postgres whenever `DATABASE_URL` is set, so an ambient one (exported by CI or
a Docker shell) would silently route a behavior test through persistence and recall
state from earlier runs. It strips `DATABASE_URL` for every non-`@integration`
test so behavior tests always build a fresh in-memory being — while `@integration`
tests keep it, since a live-Postgres round-trip is the whole point.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import pytest

TEST_SECRET = "test-secret-do-not-use-in-prod-0123456789"  # >=32 bytes (HS256)
TEST_ISSUER = "jarvis"
TEST_AUDIENCE = "jarvis-engine"


def pytest_configure(config):
    """BUG #81: app.main builds the app at import (create_app connects to the DB),
    so the autouse _hermetic_database_url fixture (test-setup) is too late to stop an
    import-time connect. Before collection, if DATABASE_URL points at an UNREACHABLE
    server, strip it (+ MODEL_SERVICE_URL) so import takes the in-memory path and
    @integration tests skip-as-unreachable. Reachable/unset -> unchanged."""
    import os
    import socket
    import warnings

    url = os.environ.get("DATABASE_URL")
    if not url:
        return
    try:
        from sqlalchemy.engine import make_url

        u = make_url(url)
        host, port = (u.host or "localhost"), (u.port or 5432)
    except Exception:
        host, port = "localhost", 5432
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return  # reachable -> keep DATABASE_URL (integration tests run)
    except OSError:
        pass
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("MODEL_SERVICE_URL", None)
    warnings.warn(
        f"DATABASE_URL points at unreachable {host}:{port}; stripped for this "
        f"session so non-integration tests stay in-memory (BUG #81)."
    )


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    """Pin always-on auth with a known secret for every test. The app reads
    these from the environment, so this is the seam tests control it through."""
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("JWT_ISSUER", TEST_ISSUER)
    monkeypatch.setenv("JWT_AUDIENCE", TEST_AUDIENCE)
    monkeypatch.setenv("JWT_TTL_SECONDS", "3600")


@pytest.fixture(autouse=True)
def _hermetic_database_url(request, monkeypatch):
    """Isolate non-`@integration` tests from an ambient `DATABASE_URL`.

    `build_simulation` opens Postgres whenever `DATABASE_URL` is set in the
    environment (the demo/runtime convenience). Without this guard, an ambient
    `DATABASE_URL` — exported in CI or a Docker shell — would silently route a
    plain behavior test through persistence and recall state persisted by earlier
    runs (the class of bug where v6 memory-avoidance broke the demo test, BUG
    rAPBdcaM). Strip it for every test WITHOUT the `integration` marker so behavior
    tests build a fresh in-memory being regardless of the ambient environment;
    `@integration` tests keep it, since exercising a live Postgres is their point."""
    if request.node.get_closest_marker("integration") is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    # Same isolation for the model-service endpoint: an ambient MODEL_SERVICE_URL
    # must not route a plain behavior test through the sidecar. `model_service`
    # tests keep it -- a live round-trip is their point (v8, ADR 0043).
    if request.node.get_closest_marker("model_service") is None:
        monkeypatch.delenv("MODEL_SERVICE_URL", raising=False)


@pytest.fixture
def mint():
    """Sign an HS256 JWT with the test secret. Overrides let a test forge an
    expired, wrong-issuer, wrong-audience, or bad-signature token."""

    def _mint(
        *,
        subject: str = "test-client",
        issuer: str = TEST_ISSUER,
        audience: str = TEST_AUDIENCE,
        secret: str = TEST_SECRET,
        ttl_seconds: int = 3600,
        expires_at: Optional[datetime] = None,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "iat": now,
            "exp": expires_at if expires_at is not None else now + timedelta(seconds=ttl_seconds),
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    return _mint

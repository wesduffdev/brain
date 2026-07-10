"""Shared fixtures for the engine suite.

The security slice (V0-SEC) adds two seams the tests need. The auth module reads
its config from the environment — deploy/secret config like `DATABASE_URL`, not
authored YAML — so `_auth_env` pins a known secret and issuer/audience for the
whole suite and turns auth on. `mint` signs tokens with that same secret through
one door, with overrides so a test can forge an expired, wrong-issuer,
wrong-audience, or bad-signature token.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import pytest

TEST_SECRET = "test-secret-do-not-use-in-prod-0123456789"  # >=32 bytes (HS256)
TEST_ISSUER = "jarvis"
TEST_AUDIENCE = "jarvis-engine"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    """Pin always-on auth with a known secret for every test. The app reads
    these from the environment, so this is the seam tests control it through."""
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("JWT_ISSUER", TEST_ISSUER)
    monkeypatch.setenv("JWT_AUDIENCE", TEST_AUDIENCE)
    monkeypatch.setenv("JWT_TTL_SECONDS", "3600")


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

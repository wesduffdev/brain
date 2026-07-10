"""auth — the one place that knows how the engine's API is authenticated.

A deep module over PyJWT and the FastAPI request surface. It hides the whole
token story behind three things:

- `AuthConfig.from_env()` reads the deploy/secret config (`JWT_SECRET`,
  `JWT_ISSUER`, `JWT_AUDIENCE`, `JWT_TTL_SECONDS`, `AUTH_REQUIRED`) — these are
  environment/secret config like `DATABASE_URL`, not authored YAML, so they do
  **not** live in `config/*.yaml`.
- `mint_token(config, ...)` signs a short-lived HS256 service token (used by the
  `python -m app.auth_token` CLI / `make token`).
- `require_auth(config)` builds a FastAPI dependency that verifies the
  `Authorization: Bearer <jwt>` header (signature + expiry + issuer + audience)
  and raises 401 on anything missing or invalid; `authenticate_ws` does the same
  for a token pulled from the WebSocket handshake.

Authentication is **always in the code path**; it is gated only by
`AUTH_REQUIRED`. When that is false the guard is a documented dev-only no-op —
there is no localhost/loopback bypass. Today the algorithm is symmetric HS256;
migrating to RS256/asymmetric keys is a change confined to this module (ADR
0005).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Optional

import jwt
from fastapi import Header, HTTPException

_ALGORITHM = "HS256"
_UNAUTH = {"WWW-Authenticate": "Bearer"}


class AuthError(Exception):
    """A token was missing, malformed, expired, or failed verification."""


@dataclass(frozen=True)
class AuthConfig:
    """Resolved authentication settings. Built from the environment in
    production; constructed directly in tests that want to pin values."""

    secret: str
    issuer: str = "jarvis"
    audience: str = "jarvis-engine"
    ttl_seconds: int = 3600
    required: bool = True

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AuthConfig":
        env = os.environ if env is None else env
        return cls(
            secret=env.get("JWT_SECRET", ""),
            issuer=env.get("JWT_ISSUER", "jarvis"),
            audience=env.get("JWT_AUDIENCE", "jarvis-engine"),
            ttl_seconds=int(env.get("JWT_TTL_SECONDS", "3600")),
            required=_as_bool(env.get("AUTH_REQUIRED", "true")),
        )


def mint_token(config: AuthConfig, subject: str = "jarvis-service", *, now: Optional[datetime] = None) -> str:
    """Sign a fresh HS256 token valid for `config.ttl_seconds`. Refuses to mint
    without a secret — an unsigned service token is never what the caller wants."""
    if not config.secret:
        raise RuntimeError("JWT_SECRET is not set — cannot mint a service token")
    issued = now or datetime.now(timezone.utc)
    payload = {
        "iss": config.issuer,
        "aud": config.audience,
        "sub": subject,
        "iat": issued,
        "exp": issued + timedelta(seconds=config.ttl_seconds),
    }
    return jwt.encode(payload, config.secret, algorithm=_ALGORITHM)


def _verify_token(config: AuthConfig, token: str) -> dict:
    """Decode and fully verify a token (signature + required exp/iss/aud).
    Returns the claims, or raises `AuthError` on anything invalid. Internal —
    callers go through `require_auth` (HTTP) or `authenticate_ws` (WebSocket)."""
    if not config.secret:
        raise AuthError("authentication is not configured (no JWT_SECRET)")
    try:
        return jwt.decode(
            token,
            config.secret,
            algorithms=[_ALGORITHM],
            audience=config.audience,
            issuer=config.issuer,
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.InvalidTokenError as exc:  # expired / bad-sig / wrong iss|aud / malformed
        raise AuthError(str(exc)) from exc


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Pull the token out of an `Authorization: Bearer <jwt>` header value, or
    `None` if the header is absent or not a well-formed bearer header."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def authenticate_ws(config: AuthConfig, token: Optional[str]) -> dict:
    """Verify a token taken from the WebSocket handshake (query param or header).
    Returns claims, or `{}` when auth is disabled; raises `AuthError` on a
    missing or invalid token when auth is required."""
    if not config.required:
        return {}
    if not token:
        raise AuthError("missing token")
    return _verify_token(config, token)


def require_auth(config: AuthConfig) -> Callable[..., dict]:
    """Build a FastAPI dependency that enforces a verified bearer token.

    Bind it to an `AuthConfig` and hand the result to `Depends(...)`: the guard
    reads the `Authorization` header, verifies the token, and raises 401 on
    anything missing or invalid, returning the claims on success. It is a no-op
    that returns empty claims when `AUTH_REQUIRED` is false (dev only).

    Returned as a closure rather than a callable class instance so FastAPI can
    resolve the header parameter's annotation under `from __future__ import
    annotations` — an instance has no `__globals__`, so its string annotation
    would never be evaluated and pydantic would reject the header."""

    def guard(authorization: Optional[str] = Header(default=None)) -> dict:
        if not config.required:
            return {}
        token = bearer_token(authorization)
        if token is None:
            raise HTTPException(status_code=401, detail="Missing bearer token", headers=_UNAUTH)
        try:
            return _verify_token(config, token)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail="Invalid token", headers=_UNAUTH) from exc

    return guard


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

"""Database connection — engine and session, built from ``DATABASE_URL``.

The connection string is deploy/secret configuration (like ``JWT_SECRET``), not
authored YAML, so it comes from the environment only and is never committed or
hard-coded (ADR 0005 secrets guardrail). `docker compose` sets it for the engine
service; local host dev exports it (see `.env.example`).

The Postgres dialect is ``postgresql+psycopg`` (psycopg 3). This module owns
building the engine, a session factory, and — because an immediate connect right
after ``docker compose up`` races Postgres' first-boot init — waiting for the
database to accept connections (``wait_for_database``). Nothing above it
constructs a SQLAlchemy engine directly.

The retry's timings (``wait_for_database``) are *deploy/ops* configuration, the
same category as ``DATABASE_URL`` itself, so they are read from the environment
(``DB_CONNECT_*``) rather than from the authored ``config/*.yaml`` gameplay
surface. Defaults live in the named constants below, not as literals in the loop.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import sessionmaker

# Deploy/ops defaults for waiting on Postgres at boot. Every one is overridable
# via the matching ``DB_CONNECT_*`` environment variable (see RetryPolicy).
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_INITIAL_BACKOFF_SECONDS = 0.5
DEFAULT_MAX_BACKOFF_SECONDS = 5.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0

# Failures that mean "not ready yet, retry": the connection was refused or the
# handshake could not complete. Anything else (auth/programming errors) is a
# real misconfiguration and propagates immediately rather than being waited out.
_RETRYABLE_CONNECT_ERRORS = (OperationalError, InterfaceError)


def database_url(env: Optional[Mapping[str, str]] = None) -> str:
    """The configured connection string. Reads ``DATABASE_URL`` from the
    environment and refuses to guess one — an unset URL is a configuration
    error, not a silent default to some local server."""
    env = os.environ if env is None else env
    url = env.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set — the database connection is configured from "
            "the environment only (see .env.example)"
        )
    return url


def create_db_engine(url: Optional[str] = None, **kwargs) -> Engine:
    """Build a SQLAlchemy engine for ``url`` (or ``DATABASE_URL`` when omitted).
    ``pool_pre_ping`` keeps pooled connections from going stale; extra kwargs
    (e.g. ``connect_args``) pass straight through for callers that need them."""
    resolved = url or database_url()
    kwargs.setdefault("pool_pre_ping", True)
    kwargs.setdefault("future", True)
    return create_engine(resolved, **kwargs)


def session_factory(engine: Engine) -> sessionmaker:
    """A configured ``sessionmaker`` bound to ``engine``. ``expire_on_commit``
    is off so a just-committed row stays readable without another round-trip."""
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


class DatabaseUnavailable(RuntimeError):
    """Raised when the database still refuses connections after the configured
    wait budget. Carries the original driver error as its ``__cause__`` so the
    real reason is not lost behind a generic timeout message."""


@dataclass(frozen=True)
class RetryPolicy:
    """How long to wait for Postgres to accept connections, and how to space the
    attempts. A *deploy/ops* policy (not gameplay config): built from the
    ``DB_CONNECT_*`` environment variables via :meth:`from_env`, with the module
    defaults as fallbacks. Backoff grows geometrically from
    ``initial_backoff_seconds`` by ``multiplier`` up to ``max_backoff_seconds``;
    the whole wait is bounded by ``timeout_seconds``."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    initial_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS
    multiplier: float = DEFAULT_BACKOFF_MULTIPLIER

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "RetryPolicy":
        env = os.environ if env is None else env
        return cls(
            timeout_seconds=_float(env, "DB_CONNECT_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
            initial_backoff_seconds=_float(
                env, "DB_CONNECT_BACKOFF_SECONDS", DEFAULT_INITIAL_BACKOFF_SECONDS
            ),
            max_backoff_seconds=_float(
                env, "DB_CONNECT_BACKOFF_MAX_SECONDS", DEFAULT_MAX_BACKOFF_SECONDS
            ),
            multiplier=_float(env, "DB_CONNECT_BACKOFF_MULTIPLIER", DEFAULT_BACKOFF_MULTIPLIER),
        )


def wait_for_database(
    engine: Engine,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    policy: Optional[RetryPolicy] = None,
) -> Engine:
    """Block until ``engine`` accepts a connection, then return it.

    Retries a connect probe with bounded, geometric backoff so an immediate
    connect after ``docker compose up`` no longer races Postgres' first-boot
    init. If the database still refuses after ``policy.timeout_seconds``, raises
    :class:`DatabaseUnavailable` with a clear message (and the last driver error
    as ``__cause__``). ``sleep`` and ``now`` are injected so the wait is testable
    without real time passing; they default to the real clock in production."""
    policy = policy or RetryPolicy.from_env()
    deadline = now() + policy.timeout_seconds
    delay = policy.initial_backoff_seconds
    while True:
        try:
            with engine.connect():
                return engine
        except _RETRYABLE_CONNECT_ERRORS as exc:
            if now() >= deadline:
                raise DatabaseUnavailable(
                    f"database did not accept a connection within "
                    f"{policy.timeout_seconds:g}s ({_describe(engine)}) — giving up"
                ) from exc
            # Back off, but never sleep past the deadline nor above the cap.
            sleep(min(delay, deadline - now(), policy.max_backoff_seconds))
            delay = min(delay * policy.multiplier, policy.max_backoff_seconds)


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    return default if raw is None or raw == "" else float(raw)


def _describe(engine: Engine) -> str:
    """A safe, password-hidden description of what we were waiting on."""
    url = getattr(engine, "url", None)
    if url is None:
        return "unknown target"
    try:
        return url.render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 — description is best-effort, never fatal
        return str(url)

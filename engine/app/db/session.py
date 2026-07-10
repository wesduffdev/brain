"""Database connection — engine and session, built from ``DATABASE_URL``.

The connection string is deploy/secret configuration (like ``JWT_SECRET``), not
authored YAML, so it comes from the environment only and is never committed or
hard-coded (ADR 0005 secrets guardrail). `docker compose` sets it for the engine
service; local host dev exports it (see `.env.example`).

The Postgres dialect is ``postgresql+psycopg`` (psycopg 3). This module owns
building the engine and a session factory; nothing above it constructs a
SQLAlchemy engine directly.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker


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

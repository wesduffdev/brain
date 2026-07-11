"""Behaviors: a non-`@integration` behavior test can never be silently perturbed
by an ambient `DATABASE_URL`.

`build_simulation` wires Postgres whenever `DATABASE_URL` is set in the process
environment (the demo/runtime convenience). CI and Docker shells routinely export
`DATABASE_URL`, so without a guard a plain behavior test would silently route
through persistence and recall state from earlier runs — the class of bug where
v6 memory-avoidance broke the demo test (BUG rAPBdcaM). The autouse conftest guard
strips `DATABASE_URL` for every test WITHOUT the `integration` marker, so behavior
tests always build a fresh in-memory being regardless of the ambient environment,
while `@integration` tests still receive it.

These tests prove both directions through the public seam (`build_simulation`) and
the environment the guard controls. The module-scoped fixture genuinely exports
`DATABASE_URL` into `os.environ` (pointing at an unreachable Postgres) BEFORE the
function-scoped conftest guard runs — the exact hazard the guard exists to
neutralize.
"""
from __future__ import annotations

import os

import pytest

from app.bootstrap import build_simulation
from app.config_service import ConfigService

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

# An unreachable Postgres: if the guard failed to strip it, `build_simulation`
# would try to open this session and raise on connect — so a clean build is
# itself proof the ambient URL was neutralized.
_AMBIENT_DB_URL = "postgresql+psycopg://nobody:nobody@127.0.0.1:1/never"


@pytest.fixture(autouse=True, scope="module")
def _ambient_database_url():
    """Simulate a process started with `DATABASE_URL` exported (as CI/Docker do).

    Module scope runs this before the function-scoped conftest guard, so every
    test in this file starts with the var genuinely present in `os.environ`."""
    prior = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _AMBIENT_DB_URL
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prior


def _config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def test_a_non_integration_test_builds_a_fresh_in_memory_being_despite_ambient_database_url():
    # The guard stripped the ambient URL for this (non-integration) test...
    assert os.environ.get("DATABASE_URL") is None
    # ...so the being builds in-memory against the unreachable DB without ever
    # touching it, and is a real being that ticks and acts — no persistence store.
    with build_simulation(_config()) as sim:
        for _ in range(20):
            sim.tick()
        assert sim.interactions()  # it acted, entirely in memory


@pytest.mark.integration
def test_an_integration_test_still_sees_the_ambient_database_url():
    # The guard is scoped to NON-integration tests, so an @integration test keeps
    # DATABASE_URL — the seam the live-Postgres round-trips depend on.
    assert os.environ.get("DATABASE_URL") == _AMBIENT_DB_URL

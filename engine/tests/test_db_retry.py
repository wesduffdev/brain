"""Behavior of the Postgres connection retry (V0-DB).

An immediate connect right after ``docker compose up`` races the database's
first-boot init: Postgres refuses connections for a beat before it is ready.
``wait_for_database`` makes the connection robust — it retries with bounded
backoff until the engine accepts a connection, then fails with a clear error
once a configurable timeout elapses.

These tests drive that behavior through the public ``wait_for_database`` surface
with an injected fake engine (a "flaky connector" that refuses a set number of
times, as Postgres does at boot) and an injected clock/sleep, so they exercise
the real retry loop with **no real sleeping** and no database.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.db.session import DatabaseUnavailable, RetryPolicy, wait_for_database


class _FakeClock:
    """Deterministic stand-in for the monotonic clock + ``time.sleep``.

    Sleeping advances the clock by exactly the slept duration — modelling real
    time faithfully while running instantly. ``sleeps`` records every backoff so
    a test can assert on the backoff schedule."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class _NullConnection:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FlakyEngine:
    """A stand-in SQLAlchemy engine whose ``connect()`` refuses ``fail_times``
    times (raising the same OperationalError a not-yet-ready Postgres does)
    before it starts accepting connections."""

    def __init__(self, fail_times: int) -> None:
        self._remaining = fail_times
        self.connect_attempts = 0

    def connect(self):
        self.connect_attempts += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise OperationalError("connect", None, Exception("connection refused"))
        return _NullConnection()


def test_a_refused_connection_is_retried_until_postgres_accepts():
    engine = _FlakyEngine(fail_times=2)
    clock = _FakeClock()
    policy = RetryPolicy(
        timeout_seconds=60, initial_backoff_seconds=1, max_backoff_seconds=5, multiplier=2
    )

    result = wait_for_database(engine, sleep=clock.sleep, now=clock.now, policy=policy)

    assert result is engine
    assert engine.connect_attempts == 3  # two refusals, then it accepts
    assert clock.sleeps == [1, 2]  # backed off between the three attempts


def test_a_database_that_never_accepts_fails_clearly_after_the_timeout():
    engine = _FlakyEngine(fail_times=10_000)  # never accepts
    clock = _FakeClock()
    policy = RetryPolicy(
        timeout_seconds=10, initial_backoff_seconds=1, max_backoff_seconds=4, multiplier=2
    )

    with pytest.raises(DatabaseUnavailable) as excinfo:
        wait_for_database(engine, sleep=clock.sleep, now=clock.now, policy=policy)

    assert "10" in str(excinfo.value)  # the configured timeout is named in the error
    assert isinstance(excinfo.value.__cause__, OperationalError)  # wraps the last failure
    assert clock.t == pytest.approx(10)  # gave up only after the whole budget elapsed
    assert clock.sleeps  # and it did back off along the way


def test_backoff_grows_but_never_exceeds_the_configured_max():
    engine = _FlakyEngine(fail_times=6)
    clock = _FakeClock()
    policy = RetryPolicy(
        timeout_seconds=10_000, initial_backoff_seconds=1, max_backoff_seconds=4, multiplier=2
    )

    wait_for_database(engine, sleep=clock.sleep, now=clock.now, policy=policy)

    assert clock.sleeps == [1, 2, 4, 4, 4, 4]  # doubles, then caps at the max
    assert max(clock.sleeps) <= policy.max_backoff_seconds


def test_the_timeout_is_configurable_from_the_environment(monkeypatch):
    # No policy passed: it defaults to RetryPolicy.from_env(), so this drives the
    # environment-config surface end to end.
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("DB_CONNECT_BACKOFF_SECONDS", "1")
    monkeypatch.setenv("DB_CONNECT_BACKOFF_MAX_SECONDS", "1")
    monkeypatch.setenv("DB_CONNECT_BACKOFF_MULTIPLIER", "1")
    engine = _FlakyEngine(fail_times=10_000)
    clock = _FakeClock()

    with pytest.raises(DatabaseUnavailable):
        wait_for_database(engine, sleep=clock.sleep, now=clock.now)

    assert clock.t == pytest.approx(3)  # waited exactly the configured 3s budget

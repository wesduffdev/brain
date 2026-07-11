"""Behavior of the persistence seam (V0-7).

The engine gains a repository port with two implementations: an in-memory fake
(the seam tests drive) and a real Postgres-backed adapter. These tests pin the
port's *behavior* — save + fetch round-trips, unknown ids read as absent,
re-saving replaces — through the public port surface, run once against the
in-memory fake and once against a live Postgres when one is reachable.

Scope note: no InteractionEvents are produced yet (that is V0-4), so nothing
here writes events. This exercises the seam that will store them, using the one
aggregate that exists today — the being.
"""
from __future__ import annotations

import os

import pytest

from app.db.migrate import create_all, drop_all
from app.db.models import Base
from app.db.session import (
    DatabaseUnavailable,
    RetryPolicy,
    create_db_engine,
    session_factory,
    wait_for_database,
)
from app.db.unit_of_work import NullUnitOfWork, SessionUnitOfWork
from app.domain.being_state import BeingState
from app.repositories import InMemoryBeingRepository, PostgresBeingRepository

# A short, bounded wait so a just-started Postgres gets a brief chance to accept
# connections (the same retry the app/migration use), without making the suite
# hang for the full production budget when there is simply no DB.
_PROBE_POLICY = RetryPolicy(
    timeout_seconds=5, initial_backoff_seconds=0.25, max_backoff_seconds=1, multiplier=2
)


def _reachable_postgres_or_skip():
    """Connect to the DATABASE_URL Postgres, or skip with a clear reason.

    Never fakes a DB: if DATABASE_URL is unset or the server is unreachable
    (the case in this sandbox, where host->container forwarding is broken), the
    live variant is skipped rather than substituted. A reachable-but-still-booting
    Postgres is waited for briefly (bounded backoff) before we give up."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping live Postgres round-trip")
    engine = create_db_engine(url, connect_args={"connect_timeout": 2})
    try:
        wait_for_database(engine, policy=_PROBE_POLICY)
    except DatabaseUnavailable as exc:
        reason = type(exc.__cause__).__name__ if exc.__cause__ else "timeout"
        pytest.skip(f"Postgres not reachable at DATABASE_URL ({reason}) — skipping")
    except Exception as exc:  # noqa: BLE001 — any other connect problem means "skip, don't fake"
        pytest.skip(f"Postgres not reachable at DATABASE_URL ({type(exc).__name__}) — skipping")
    return engine


@pytest.fixture(
    params=[
        pytest.param("memory"),
        pytest.param("postgres", marks=pytest.mark.integration),
    ]
)
def being_repo(request):
    """A BeingRepository under test, paired with the unit of work its writes go
    through (ADR 0017): the no-op unit for the in-memory fake, a session-backed
    unit for the live Postgres adapter. Runs the same contract against both."""
    if request.param == "memory":
        yield InMemoryBeingRepository(), NullUnitOfWork()
        return

    engine = _reachable_postgres_or_skip()
    drop_all(engine)  # fresh schema so each test starts empty
    create_all(engine)
    session = session_factory(engine)()
    try:
        yield PostgresBeingRepository(session), SessionUnitOfWork(session)
    finally:
        session.close()
        engine.dispose()


def test_a_saved_being_round_trips_through_the_repository(being_repo):
    repo, uow = being_repo
    being = BeingState(being_id="being_001", needs={"hunger": 35, "safety": 70}, emotion="curious")

    with uow.begin():
        repo.save(being)

    assert repo.get("being_001") == being


def test_an_unknown_being_reads_as_absent(being_repo):
    repo, _uow = being_repo
    assert repo.get("being_nobody") is None


def test_saving_a_being_again_replaces_the_stored_one(being_repo):
    repo, uow = being_repo
    with uow.begin():
        repo.save(BeingState(being_id="being_001", needs={"hunger": 10}, emotion="calm"))
    with uow.begin():
        repo.save(BeingState(being_id="being_001", needs={"hunger": 90}, emotion="hungry"))

    stored = repo.get("being_001")
    assert stored.emotion == "hungry"
    assert stored.needs == {"hunger": 90}


def test_a_fetched_being_does_not_alias_the_store(being_repo):
    repo, uow = being_repo
    with uow.begin():
        repo.save(BeingState(being_id="being_001", needs={"hunger": 20}, emotion="calm"))

    fetched = repo.get("being_001")
    fetched.needs["hunger"] = 999  # mutating the copy must not leak back into the store

    assert repo.get("being_001").needs["hunger"] == 20


def test_the_migration_defines_the_schema_tables():
    # The schema seam declares exactly the v0 tables from BRIEF §15, plus the
    # `memories` table the cognitive loop adds (card v1), the concept-learning
    # tables card v2 adds (concept_schemas, concept_evidence, beliefs,
    # object_similarity_records), and the concept-graph tables card v7 adds
    # (graph_nodes, graph_edges).
    assert set(Base.metadata.tables) == {
        "beings",
        "objects",
        "interaction_events",
        "training_examples",
        "prediction_records",
        "model_runs",
        "memories",
        "concept_schemas",
        "concept_evidence",
        "beliefs",
        "object_similarity_records",
        "graph_nodes",
        "graph_edges",
    }


def test_the_migration_creates_the_v0_tables_in_a_database():
    # Exercise the migration path end-to-end against a real (in-memory SQLite)
    # engine — this proves create_all emits the tables. The Postgres-specific
    # round-trip is the skipped-when-unreachable integration test above; this is
    # a portable check of the DDL, not a stand-in for it.
    from sqlalchemy import create_engine, inspect

    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)

    tables = set(inspect(engine).get_table_names())
    assert {
        "beings",
        "objects",
        "interaction_events",
        "training_examples",
        "prediction_records",
        "model_runs",
        "memories",
        "concept_schemas",
        "concept_evidence",
        "beliefs",
        "object_similarity_records",
    } <= tables

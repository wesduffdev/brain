"""Behavior: the SQLite test path enforces foreign keys (TEST-FK).

SQLite ships with ``PRAGMA foreign_keys=OFF``, so a referential-integrity
violation that a live Postgres rejects would slip through silently in the SQLite
test path — the gap that once hid a ``training_examples`` FK bug. The central
engine seam (``app.db.session``) turns FK enforcement ON for every SQLite
connection, so the test database now rejects an orphan child exactly as Postgres
does, and CI catches the violation instead of production.

Pinned through the public engine seam — a SQLite engine built the way the app
builds one (``create_db_engine`` + ``create_all``):

- a deliberate orphan insert (a ``training_example`` whose ``event_id`` points to
  no ``interaction_events`` row) is rejected with an ``IntegrityError``;
- the same child, with its parent event present, still persists — enforcement
  rejects orphans, not valid links (and does not otherwise break the schema).
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import models
from app.db.migrate import create_all
from app.db.session import create_db_engine, session_factory


def _sqlite_engine_and_session():
    """A fresh in-memory SQLite database with the v0 schema, built through the
    same engine seam the app uses — so this exercises the real FK-enforcement
    behavior, not a test-only setup."""
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine, session_factory(engine)()


def test_an_orphan_child_insert_is_rejected_under_sqlite():
    engine, session = _sqlite_engine_and_session()
    try:
        # a training_example whose event_id references no interaction_events row
        session.add(
            models.TrainingExample(
                event_id="ghost-event-does-not-exist",
                input_features=[],
                output_labels=[],
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.close()
        engine.dispose()


def test_a_child_with_its_parent_present_persists_under_sqlite():
    engine, session = _sqlite_engine_and_session()
    try:
        # seed the parents the foreign keys require, then the child links validly
        session.add(models.Being(being_id="being_001", needs={}, emotion="calm"))
        session.add(
            models.InteractionEvent(
                event_id="being_001:1",
                being_id="being_001",
                object_id=None,
                action="touch",
            )
        )
        session.add(
            models.TrainingExample(
                event_id="being_001:1",
                input_features=[1.0],
                output_labels=[1.0],
            )
        )
        session.commit()  # a valid link commits cleanly under enforcement

        assert session.query(models.TrainingExample).count() == 1
    finally:
        session.close()
        engine.dispose()

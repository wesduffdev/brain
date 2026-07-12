"""Behavior: ingesting documents accumulates their chunks (embedded) into a
PERSISTENT, CUMULATIVE knowledge store behind a RetrievalPort, and a query
retrieves the top-k relevant passages spanning ALL ingested documents — each
passage carrying its source document, so an answer (reading R4) can cite it
(reading R3, ADR 0038).

Offline: driven by the deterministic hashing embedder + an in-memory or SQLite
store, so the whole slice runs in the plain suite with no model and no network.
"""
from __future__ import annotations

import pytest

from app.db.migrate import create_all
from app.db.unit_of_work import NullUnitOfWork, SessionUnitOfWork
from app.language.embedding import HashingEmbedder
from app.language.ingest import ingest_text
from app.language.knowledge_store import KnowledgeStore, index_document
from app.ports.retrieval import Chunk
from app.repositories import (
    InMemoryKnowledgeChunkRepository,
    PostgresKnowledgeChunkRepository,
)

_CATS = (
    "The cat is a small domesticated feline. Cats purr when they are content "
    "and hunt small prey at night."
)
_VOLCANO = (
    "A volcano erupts molten lava from deep underground. Volcanoes build "
    "mountains over many eruptions."
)


def _memory_store(dim=256):
    """A knowledge store backed by the in-memory chunk repository — the seam the
    behavior suite drives, no database required."""
    return KnowledgeStore(
        embedder=HashingEmbedder(dim=dim),
        repository=InMemoryKnowledgeChunkRepository(),
        unit_of_work=NullUnitOfWork(),
    )


def test_an_ingested_document_is_chunked_embedded_and_retrievable():
    store = _memory_store()
    document = ingest_text(_CATS, source="cats.txt", max_chars=1000)

    added = index_document(document, store)
    assert added == len(document.chunks)

    hits = store.search("what do you know about cats", k=3)
    assert hits, "an ingested document is retrievable"
    top = hits[0]
    assert "cat" in top.text.lower()
    assert top.source == "cats.txt"          # the passage cites its source document
    assert top.score > 0.0


def test_search_returns_the_relevant_passage_over_an_unrelated_one():
    store = _memory_store()
    index_document(ingest_text(_CATS, source="cats.txt"), store)
    index_document(ingest_text(_VOLCANO, source="volcano.txt"), store)

    top = store.search("tell me about a volcano and lava", k=1)[0]
    assert top.source == "volcano.txt"
    assert "volcano" in top.text.lower() or "lava" in top.text.lower()


def test_a_second_document_adds_to_retrievable_knowledge_spanning_all_docs():
    # The cumulative invariant: knowledge GROWS across documents. After two docs,
    # a query can return a passage from EITHER, and the store spans both sources.
    store = _memory_store()

    index_document(ingest_text(_CATS, source="cats.txt"), store)
    cats_only = store.search("cats", k=5)
    assert {h.source for h in cats_only} == {"cats.txt"}

    index_document(ingest_text(_VOLCANO, source="volcano.txt"), store)

    # A cat query still finds the cat doc; a volcano query now finds the new doc.
    assert store.search("domesticated feline cats", k=1)[0].source == "cats.txt"
    assert store.search("molten lava volcano eruptions", k=1)[0].source == "volcano.txt"

    # And retrieval now SPANS both documents — the second added to what is knowable.
    spanning = {h.source for h in store.search("cats and volcanoes", k=10)}
    assert spanning == {"cats.txt", "volcano.txt"}


def test_search_k_bounds_the_number_of_passages_returned():
    store = _memory_store()
    index_document(ingest_text(_CATS, source="cats.txt"), store)
    index_document(ingest_text(_VOLCANO, source="volcano.txt"), store)
    assert len(store.search("cats and volcanoes", k=1)) == 1


def test_add_accepts_chunks_tagged_with_their_source():
    # RetrievalPort.add takes source-tagged chunks directly (the ingest bridge is
    # only a convenience over it).
    store = _memory_store()
    store.add([Chunk(text="Sea otters float on their backs.", source="otters.txt")])
    top = store.search("otters float", k=1)[0]
    assert top.source == "otters.txt"


def test_knowledge_persists_and_round_trips_through_the_store():
    # Persistence round-trip: add through a SQLAlchemy-backed store in one unit of
    # work, then reload with a FRESH store over the same database and search — the
    # accumulated knowledge survives (SQLite stands in for Postgres here; the live
    # Postgres path is the @integration round-trip).
    from sqlalchemy import create_engine

    engine = create_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)

    write_session = Session()
    try:
        writer = KnowledgeStore(
            embedder=HashingEmbedder(dim=256),
            repository=PostgresKnowledgeChunkRepository(write_session),
            unit_of_work=SessionUnitOfWork(write_session),
        )
        index_document(ingest_text(_CATS, source="cats.txt"), writer)
        index_document(ingest_text(_VOLCANO, source="volcano.txt"), writer)
    finally:
        write_session.close()

    read_session = Session()
    try:
        reader = KnowledgeStore(
            embedder=HashingEmbedder(dim=256),
            repository=PostgresKnowledgeChunkRepository(read_session),
            unit_of_work=SessionUnitOfWork(read_session),
        )
        hits = reader.search("molten lava volcano", k=1)
        assert hits[0].source == "volcano.txt"
        # Both documents survived the round-trip — the store is cumulative + durable.
        spanning = {h.source for h in reader.search("cats and volcanoes", k=10)}
        assert spanning == {"cats.txt", "volcano.txt"}
    finally:
        read_session.close()
        engine.dispose()


def test_retrieval_policy_is_read_from_config():
    import os

    from app.config_service import ConfigService

    config_root = os.path.join(os.path.dirname(__file__), "..", "..", "config")
    policy = ConfigService.from_files(config_root).knowledge_retrieval_policy()
    assert policy.embedder in ("hashing", "sentence-transformers")
    assert policy.dim > 0
    assert policy.k >= 1

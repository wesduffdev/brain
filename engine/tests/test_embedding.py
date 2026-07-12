"""Behavior: the reading faculty embeds passages into fixed-dim vectors so the
knowledge store can retrieve by similarity (reading R3, ADR 0038).

The DEFAULT embedder is a pure, deterministic, offline hashing/bag-of-words
embedder — no model download, no network, no heavy dependency — so the whole
retrieval slice runs in the plain suite. The real sentence-transformers embedder
(bge-small / all-MiniLM) is a config-selected, lazily-imported option that is
GATED here: its test skips when the library is absent.
"""
from __future__ import annotations

import math

import pytest

from app.language.embedding import (
    HashingEmbedder,
    SentenceTransformerEmbedder,
    build_embedder,
)
from app.policies import KnowledgeRetrievalPolicy


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def test_embedding_has_the_configured_dimension():
    embedder = HashingEmbedder(dim=128)
    vector = embedder.embed("the quick brown fox")
    assert embedder.dim == 128
    assert len(vector) == 128


def test_embedding_is_deterministic_and_offline():
    embedder = HashingEmbedder(dim=64)
    # Same text, embedded twice (and even by a fresh embedder), is byte-identical —
    # no per-process hash salt, no model state, no randomness.
    assert embedder.embed("volcanoes erupt molten lava") == embedder.embed(
        "volcanoes erupt molten lava"
    )
    assert HashingEmbedder(dim=64).embed("hello world") == HashingEmbedder(dim=64).embed(
        "hello world"
    )


def test_similar_text_embeds_closer_than_unrelated_text():
    embedder = HashingEmbedder(dim=256)
    cats = embedder.embed("the cat is a small domesticated feline that purrs")
    kittens = embedder.embed("a small cat that purrs is a gentle feline")
    volcano = embedder.embed("a volcano erupts molten lava from deep underground")
    # Two passages sharing vocabulary are more alike than a wholly different one.
    assert _cosine(cats, kittens) > _cosine(cats, volcano)


def test_empty_text_embeds_without_error():
    # A degenerate (all-zero) vector is allowed, not a crash — cosine treats it as
    # unrelated to everything.
    embedder = HashingEmbedder(dim=32)
    assert len(embedder.embed("")) == 32


def test_build_embedder_defaults_to_the_deterministic_hashing_embedder():
    embedder = build_embedder(KnowledgeRetrievalPolicy(embedder="hashing", dim=96))
    assert isinstance(embedder, HashingEmbedder)
    assert embedder.dim == 96


@pytest.mark.skipif(
    not SentenceTransformerEmbedder.available(),
    reason="sentence-transformers not installed — the real embedder is gated/offline-optional",
)
def test_sentence_transformer_embedder_produces_vectors():
    # GATED: only runs where sentence-transformers + a downloaded model exist.
    policy = KnowledgeRetrievalPolicy(embedder="sentence-transformers", model="all-MiniLM-L6-v2")
    embedder = build_embedder(policy)
    vector = embedder.embed("a passage to embed")
    assert len(vector) == embedder.dim > 0

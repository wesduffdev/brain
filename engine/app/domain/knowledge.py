"""The knowledge-store domain aggregate (reading R3, ADR 0038).

`KnowledgeChunk` is one embedded passage in the being's growing knowledge store:
the chunk text, the source document it came from (for citation), and its
embedding vector. It is an append-only fact — a document read is folded in and
never edited — so its repository (`app.ports.repositories.KnowledgeChunkRepository`)
`add`s and reads back, like the other learned-fact aggregates.

The embedding is kept as a plain tuple of floats, stored as JSON today and
pgvector-ready tomorrow (roadmap v11): moving to a native vector column + ANN
index is a persistence-adapter change, not a domain one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class KnowledgeChunk:
    """One embedded passage of the growing knowledge store: the `source` document
    it came from (its citation), the chunk `text`, and its `embedding` vector.
    Immutable and append-only — reading a document adds chunks, it never mutates
    an existing one."""

    source: str
    text: str
    embedding: Tuple[float, ...]

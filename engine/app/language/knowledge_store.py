"""KnowledgeStore — the being's growing, persistent knowledge store behind the
`RetrievalPort` (reading R3, ADR 0038).

Everything the being reads is chunked (reading R1's `ingest`), embedded, and
folded into this store, which spans EVERY document it has ever read. At answer
time the most relevant passages are retrieved — each citing its source document —
so grounded, cited answering (R4) can draw on the whole accumulated corpus.

Deep module, small interface: `add` and `search` are the whole surface, hiding
embedding, cosine ranking, and persistence. It composes two seams — an
`EmbedderPort` (deterministic offline hashing by default; a real embedder gated
behind config) and a `KnowledgeChunkRepository` (an in-memory fake for the suite,
a Postgres/SQLite adapter for the runtime) — plus a `UnitOfWork`, so the SAME
store is the test's in-memory store or the durable one purely by what it is
handed (ADR 0017). Ranking is brute-force cosine today and pgvector-ready
(roadmap v11): the vectors already persist per chunk, so moving to an ANN index
is a repository-adapter change, not a store one.
"""
from __future__ import annotations

import math
from typing import Iterable, List

from app.domain.knowledge import KnowledgeChunk
from app.ports.retrieval import Chunk, EmbedderPort, RetrievedPassage
from app.language.ingest import IngestedDocument


def _cosine(a, b) -> float:
    """Cosine similarity of two vectors — 0.0 when either is all-zero (so an empty
    passage or query is simply unrelated to everything, never a divide-by-zero)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class KnowledgeStore:
    """A persistent, cumulative retrieval store (implements `RetrievalPort`).

    `embedder` turns text into vectors; `repository` persists the embedded chunks
    (append-only) and reads them back; `unit_of_work` groups an ingest's writes so
    they commit atomically (ADR 0017). Defaults to a no-op unit of work for the
    in-memory path."""

    def __init__(self, *, embedder: EmbedderPort, repository, unit_of_work=None) -> None:
        self._embedder = embedder
        self._repository = repository
        if unit_of_work is None:
            from app.db.unit_of_work import NullUnitOfWork  # noqa: PLC0415 — in-memory default

            unit_of_work = NullUnitOfWork()
        self._unit_of_work = unit_of_work

    def add(self, chunks: Iterable[Chunk]) -> None:
        """Embed and persist `chunks` (source-tagged passages) into the store,
        staging every write in ONE unit of work so a document's chunks commit
        together or not at all (ADR 0017)."""
        records = [
            KnowledgeChunk(
                source=chunk.source,
                text=chunk.text,
                embedding=self._embedder.embed(chunk.text),
            )
            for chunk in chunks
        ]
        if not records:
            return
        with self._unit_of_work.begin():
            for record in records:
                self._repository.add(record)

    def search(self, query: str, k: int) -> List[RetrievedPassage]:
        """The `k` passages most relevant to `query`, best-first — brute-force
        cosine over every stored chunk, so a query spans EVERY document read.
        Each result carries its source document (citation) and relevance score."""
        if k <= 0:
            return []
        query_vector = self._embedder.embed(query)
        scored = [
            RetrievedPassage(
                text=record.text,
                source=record.source,
                score=_cosine(query_vector, record.embedding),
            )
            for record in self._repository.all()
        ]
        scored.sort(key=lambda passage: passage.score, reverse=True)
        return scored[:k]


def index_document(document: IngestedDocument, store) -> int:
    """Fold an ingested document's chunks into `store`, each tagged with the
    document's source — the ingest → knowledge-store bridge. Returns how many
    chunks were added. A thin convenience over `RetrievalPort.add`."""
    chunks = [Chunk(text=text, source=document.source) for text in document.chunks]
    store.add(chunks)
    return len(chunks)

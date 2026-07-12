"""Retrieval ports — the growing-knowledge-store seam (reading R3, ADR 0038).

The being reads documents and folds them into a PERSISTENT, CUMULATIVE knowledge
store it later retrieves from to answer questions (grounded + cited answering
follows in R4). Two seams make that swappable:

- `RetrievalPort` — the store itself: `add` source-tagged passages, and `search`
  a query for the top-k most relevant passages, each carrying the source document
  it came from (for citation) and a relevance score. One implementation exists
  today — `app.language.knowledge_store.KnowledgeStore`, a brute-force cosine
  store over a chunk repository (in-memory fake / Postgres, pgvector-ready) — so
  this is the interface a later ANN/pgvector store slots behind unchanged.
- `EmbedderPort` — how a passage becomes a fixed-dimension vector. The DEFAULT is
  a pure, deterministic, offline hashing/bag-of-words embedder
  (`HashingEmbedder`) so retrieval runs in the plain suite with no model and no
  network; a real sentence-transformers embedder (bge-small / all-MiniLM) is a
  config-selected, lazily-imported, gated option behind the same port.

Callers depend on these ports, never on how a vector is computed or where a
passage is stored.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Protocol, Tuple


@dataclass(frozen=True)
class Chunk:
    """A passage to ADD to the knowledge store: the chunk `text`, tagged with the
    `source` document it came from so a later answer can cite it. This is the
    port's INPUT — before embedding; the embedded, persisted form is the domain
    `KnowledgeChunk`."""

    text: str
    source: str


@dataclass(frozen=True)
class RetrievedPassage:
    """A passage RETURNED by a search: the chunk `text`, the `source` document it
    came from (the citation), and its `score` — how relevant it is to the query
    (higher is closer). Ordered best-first in a search result."""

    text: str
    source: str
    score: float


class EmbedderPort(Protocol):
    """Turns text into a fixed-dimension embedding vector for similarity search.

    `dim` is the vector length (the same for every text an embedder produces);
    `embed` maps one string to its vector. Implementations vary across this seam:
    a deterministic offline hashing embedder (the default/test embedder) and a
    real sentence-transformers embedder (gated on the optional library)."""

    @property
    def dim(self) -> int:
        """The dimension of every vector this embedder produces."""
        ...

    def embed(self, text: str) -> Tuple[float, ...]:
        """The embedding vector for `text` (length `dim`)."""
        ...


class RetrievalPort(Protocol):
    """The being's growing knowledge store — persistent and cumulative across every
    document it has ever read (reading R3, ADR 0038).

    `add` folds source-tagged passages into the store (embedding + persisting them
    in one unit of work); `search` returns the top-`k` passages most relevant to
    `query`, each citing its source document, spanning ALL ingested documents.
    Append-only and additive: a new document adds to what is retrievable and never
    replaces what came before."""

    def add(self, chunks: Iterable[Chunk]) -> None:
        """Embed and persist `chunks` into the store, atomically (one unit of work)."""
        ...

    def search(self, query: str, k: int) -> List[RetrievedPassage]:
        """The `k` passages most relevant to `query`, best-first, each with its
        source document and relevance score."""
        ...

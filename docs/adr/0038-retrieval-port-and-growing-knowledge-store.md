# 0038 — Retrieval port + growing knowledge store

- **Status:** Accepted
- **Date:** 2026-07-11

## Context

The being's knowledge stance is **learn-and-grow** (READING_VOICEBOX §3): it
starts from its open base model and **adds to what it knows** as you feed it
documents. Reading R1 (ADR 0036) gave us the front half — `ingest` cleans and
chunks a document — and R2 (ADR 0037) serves our fine-tuned model behind
`LanguageModelPort`. But a LoRA fine-tune is the *durable, slow* path
(consolidation, R5); the *immediate* path is a **growing knowledge store**: every
document is chunked, embedded, and folded into a persistent store spanning
everything read, so a new document is retrievable the instant it is ingested — no
retrain. Grounded, cited answering over that store follows in R4.

We need this to be:

- **Persistent and cumulative** — knowledge accumulates across every document
  read and survives restarts; a new document *adds to* what is retrievable and
  never replaces it.
- **Offline and reproducible in the suite** — no model download or network in the
  plain test run, so retrieval behavior is pinned deterministically.
- **Swappable** at two seams: how a passage becomes a vector (a cheap offline
  embedder now, a real semantic embedder later) and where/how passages are stored
  and ranked (brute-force cosine now, pgvector/ANN later — roadmap v11).

## Decision

Introduce two ports and one store.

- **`RetrievalPort`** (`app/ports/retrieval.py`) — the knowledge store's interface:
  `add(chunks)` folds source-tagged passages in (embedding + persisting them in one
  unit of work); `search(query, k)` returns the top-`k` `RetrievedPassage`s
  best-first, each carrying its **source document (for citation)** and a relevance
  **score**, spanning **all** ingested documents. `Chunk(text, source)` is the
  input DTO (pre-embedding); the persisted, embedded form is the domain
  `KnowledgeChunk(source, text, embedding)`.
- **`EmbedderPort`** (`app/ports/retrieval.py`) — `dim` + `embed(text) -> vector`.
  The **default is `HashingEmbedder`**: a pure, deterministic, offline
  bag-of-words hashing embedder (stable `blake2b` content hash — never Python's
  per-process-salted `hash()` — with stopword/short-token filtering so topical
  words dominate cosine). The real **`SentenceTransformerEmbedder`** (bge-small /
  all-MiniLM) is a **config-selected, lazily-imported, gated** option that refuses
  loudly when `sentence-transformers` is absent and never fakes an embedding —
  mirroring the MLX / torch / espeak availability gates. `build_embedder(policy)`
  selects between them; the default path is fully offline.
- **`KnowledgeStore`** (`app/language/knowledge_store.py`) — the one implementation
  behind `RetrievalPort`. A deep module over a small interface: it composes an
  `EmbedderPort`, a `KnowledgeChunkRepository` (in-memory fake for the suite; a
  Postgres/SQLite adapter for the runtime), and a `UnitOfWork`, so the *same* store
  is the in-memory test store or the durable one purely by what it is handed. `add`
  stages a document's chunks in **one unit of work** (ADR 0017); `search` reads all
  chunks and ranks by **brute-force cosine**. `index_document(doc, store)` is the
  thin ingest → store bridge.

**Persistence.** A new append-only table `knowledge_chunks` (`source`, `text`,
`embedding` as JSON, `created_at`). `source` is a plain indexed string, not a DB
foreign key — a chunk is a self-contained fact about text read, not a catalog
relationship (the FK discipline of ADR 0019 / the event backbone). The
`PostgresKnowledgeChunkRepository` only **stages** its writes; the caller's unit of
work commits them.

**pgvector-ready (roadmap v11).** The embedding already persists per chunk as a
float list and ranking is isolated in the store. Moving to a native `vector`
column + ANN index is a change to the one table + its adapter, behind the
unchanged `RetrievalPort` — not a domain or caller change.

**Config.** A `retrieval:` block in `config/language.yaml` → `KnowledgeRetrievalPolicy`
(`embedder`, `dim`, `k`, `model`), read only by `ConfigService`. Defaults are
fully offline, so retuning what/how the being retrieves — or switching to the real
embedder — is a config change only. This is distinct from the card-v6 memory-recall
`RetrievalPolicy`; that is memory recall, this is the reading faculty's document
store.

## Consequences

- Ingesting several documents accumulates their chunks into a persistent,
  cumulative store; a query after two documents can return passages from **either**
  (retrieval spans all), each citing its source — the observable outcome of R3,
  covered offline by the deterministic embedder + in-memory/SQLite store.
- The plain suite stays offline and deterministic: the hashing embedder needs no
  model and no network; the real-embedder test is gated/skipped when
  `sentence-transformers` is absent; the persistence round-trip uses in-memory
  SQLite (the live-Postgres path is the existing `@integration` skip).
- R4 (grounded, cited answers) consumes `RetrievalPort.search` and reuses this ADR;
  R5 (consolidation fine-tune) bakes the accumulated store into weights; v11 swaps
  in pgvector behind the same port.
- The knowledge store sits **on top** of the simulation like narration/voice — it
  adds to what the being knows and drives no need, emotion, or decision (BRIEF rule
  #6, ADR 0022); reading changes the being only through the validated cognition
  door (R7), never by letting retrieval write state.

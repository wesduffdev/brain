# 0044 — Runtime document-ingest endpoint (`POST /ingest`) over one shared knowledge store

- **Status:** Accepted
- **Date:** 2026-07-11

## Context

The reading faculty could already ingest a document (R1, ADR 0036), index it into
the growing knowledge store (R3, ADR 0038), answer/converse about it (R4/R6, ADR
0039), and let it CHANGE the being through the validated perception/cognition door
(R7, ADR 0040). But there was no **runtime surface** to hand the being a document:
`/ask/reading` and `/chat` could only ever answer about a store that was empty at
process start, because `create_app` built a **separate, private** `KnowledgeStore`
for reading QA and (transitively) for conversation — nothing wrote to them at
runtime, so a served being always declined. Ingest was reachable only as an
in-process function (and `/read`, which merely voices a document aloud, ADR 0035).

We want the observable: an operator hands the being a document over HTTP and the
being (a) can then answer about it grounded + cited, and (b) forms memories/concepts
from it — without violating the invariants. Reading must NOT let a language model
write state (language-on-top, ADR 0022); it must enter cognition only through the
validated door (ADR 0040).

## Decision

Add **`POST /ingest`** (body `{"text", "source"?}`), behind the always-on JWT guard
(ADR 0005) and mirroring `/read`'s 422-on-empty. One call does two things, each
through an existing validated path:

1. **Index** the cleaned + chunked text into the knowledge store via the existing
   `ingest_text` + `index_document` (ADR 0036/0038), so retrieval can ground and
   cite it.
2. **Read** it through the validated door via the existing public
   `Simulation.read(text, source=…)` (ADR 0040) — perceived content tokens →
   `PerceptionService` → `ActionValidationService` → the SAME `Memory`/`Concept`
   services — so memories/concepts form. No new seam: `Simulation.read` is already
   the R7 surface; `/ingest` composes what exists.

Refactor `create_app` to build **ONE shared `KnowledgeStore`** and thread it to
`/ingest`, `ReadingQAService`, and `ConversationService` (previously each reading
surface built its own private store). The store stays injectable for tests. The
handler returns a small summary `{"source", "chunks", "perceived"}`.

The language model remains **absent from the write path** — `/ingest` never asks a
model to record anything; text becomes state only as perceived tokens judged at the
door (ADR 0022/0040). The store is the default **in-memory** adapter (ADR 0038): a
durable store is a repository swap behind the same seam.

## Consequences

- A served being can be taught at runtime: after `POST /ingest`, `/ask/reading` and
  `/chat` answer grounded + cited about the document, and `Simulation.memories()` /
  `concepts()` reflect the reading. The same query is declined before ingest.
- **One global corpus, per process.** All clients and every conversation share the
  single in-memory `KnowledgeStore`; there is no per-session isolation, and an
  ingest is **not persisted across a restart** (transient like the in-memory being).
  A durable/partitioned store is a later repository swap behind `RetrievalPort`
  (pgvector-ready, ADR 0038), not a change to this surface.
- Invariants hold: language stays on top (no model writes state), reading enters
  only through the validated door, and the route is read-only w.r.t. the world (it
  advances the being's clock one step per read section, as R7 already does — reading
  takes time — but drives no needs/emotion; ADR 0040).
- No new port/seam was added — a wiring + surface change only, so it is easily
  reversible; it extends ADR 0038/0039/0040 and does not supersede them.

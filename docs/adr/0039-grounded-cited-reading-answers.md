# 0039 — Grounded, cited reading answers (`ReadingQAService`)

- **Status:** Accepted
- **Date:** 2026-07-11

## Context

Reading R3 (ADR 0038) gave the being a growing, persistent knowledge store behind
`RetrievalPort` — everything it reads is chunked, embedded, and retrievable, each
passage carrying its source document. R4 is the conversational payoff
(READING_VOICEBOX §3, §7): **ask a question and get an answer grounded in what the
being has read, citing the source** — or, for something it has not read, an honest
"I haven't read anything about that," optionally reasoning from base knowledge and
clearly distinguishing *what it read* from *what it already knew*.

The hard part is not phrasing; it is **grounding by construction**. A language
model will happily invent facts and cite documents it never saw. The self-report
and subject surfaces (ADR 0032/0034) solved the same problem by building the
model's prompt from ONLY the being's own structured experience, and by answering an
unknown deterministically (never a model call). R4 needs the equivalent for read
documents, reusing the existing seams — `RetrievalPort` (ADR 0038) and
`LanguageModelPort` (ADR 0022) — without a new port.

## Decision

Add **`ReadingQAService`** on the two existing seams: `RetrievalPort` (the R3
store) and an optional `LanguageModelPort` (the shared narrator). `answer(question)`
retrieves the top-`k` passages, keeps only those scoring at or above a config
`min_relevance`, and then:

- **Grounded path** (something read is relevant): it builds a prompt from ONLY the
  retrieved passages (each tagged with its source) + the question — never the whole
  store — and the citation is composed from the **retrieval result's** source
  documents, **never from the model**. So the model cannot invent grounding and can
  never fabricate a citation. The answer is prefixed with a `read_label` and
  suffixed with the cited source(s).
- **Extractive default** (no generative model — the offline `deterministic`
  narrator): the being still answers grounded and cited by **quoting** the retrieved
  passages. Fluency is an upgrade; grounding and citation are guaranteed with no
  model call. A generative narrator (`fake`/`claude`/`local`) rephrases the same
  grounded prompt.
- **Unread path** (nothing relevant): the honest `unread_response` line, naming the
  topic, which **never carries a citation**. When `blend_base_knowledge` is on and a
  model is present, it also offers a base-knowledge answer — the model answering
  WITHOUT any retrieved context (so it can carry no source) — under a distinct
  `base_label`, so what the being READ is always transparent from what it KNEW.

Exposed on a **focused route, `POST /ask/reading`** (kept separate from `/ask` so
the S1 self-report / S3 subject behavior is byte-identical), behind the same
always-on JWT guard (ADR 0005) and read-only (ADR 0022). All values — `k`,
`min_relevance`, the unread phrasing, the labels, the citation template, the base
blend toggle — live in `config/language.yaml` (`reading_qa:`) via `ReadingQAPolicy`.
The default runtime store is in-memory and empty (a fresh being has read nothing, so
it honestly declines until documents are ingested). This reuses ADR 0038/0022; no
new port.

## Consequences

- Grounding is a property of the service, not the model's goodwill: the citation is
  structural (from retrieval), the grounded prompt is closed over the retrieved
  passages, and the unread/extractive paths need no model at all — so the being can
  never cite a document it did not read, on any provider.
- Read-vs-base is transparent by labelling, satisfying the learn-and-grow stance
  without any refusal machinery to blind the base model.
- Fluent reading answers require a generative provider (`narrator.kind`); the
  offline default answers extractively (quoted + cited), which is honest but terse.
  This mirrors the fallback-safe posture of the narrator (ADR 0033) and predictor
  (ADR 0011): the fluent voice is never a dependency.
- `min_relevance` is the honest/forced boundary — too low forces ungrounded answers,
  too high declines things actually read; it is config-tunable and defaults low
  (0.05) so a clearly-unrelated query (cosine ≈ 0) declines while a real match
  passes.
- Populating the running app's store (an ingest surface / persistent store wiring)
  is deliberately out of scope here; R4 delivers the ANSWER, R1's pipeline and a
  later ingest surface deliver the documents.

# 0032 — Self-report narration surface (deterministic narrator + `/ask`)

## Status

Accepted (extends [0022](0022-natural-language-layer-and-language-model-port.md))

## Date

2026-07-11

## Context

ADR 0022 landed the natural-language layer behind its service interfaces but
left the "narrate" half — `NarrationService` and `MemorySummaryService` —
**unwired to any surface**, and noted an HTTP endpoint was a follow-up. This is
that follow-up, and the first LANGUAGE slice the being actually speaks through
(the self-narration plan, `docs/SELF_NARRATION.md`, S1): ask it *"what have you
done recently?"* and it answers in plain first-person language, grounded only in
its own logged memories.

Two forces shape it. First, BRIEF rule #6 / ADR 0022 — language sits **on top**
of the psychology and never controls it. A self-report must read snapshots and
mutate nothing; it can never feed back into the being's decision. Second, the
report must be **grounded by construction**: the being can only say what it has
lived, and it names objects by what it PERCEIVED, never a developer label (ADR
0002). We also want a talking being with **no external model dependency** — the
behaviour suite stays offline and deterministic (ADR 0022's fake-model rule), and
a being should speak on day one without an API key, MLX, or Ollama.

## Decision

**A deterministic template narrator behind the existing `LanguageModelPort`.**
`TemplateLanguageModel` implements the same `complete(prompt) -> str` seam as the
Claude adapter and the test `FakeLanguageModel` (ADR 0022 — **no new port**). It
renders the being's structured experience into first-person prose with no model:
`MemorySummaryService` / `NarrationService` serialize each memory / state snapshot
into a small, documented **fact-line grammar** (`- action=… object=… perceived=…
observed=… felt=… salience=…`), and the narrator parses those facts and phrases
them. The string round-trip is the deliberate price of keeping **one** language
seam: the same fact-line prompt a deterministic narrator parses, a real model
reads as facts under the "use only these records; do not invent" instruction — so
swapping in Claude (S2) changes only fluency, never grounding. Parsing is lenient
(unknown/missing tokens degrade, never raise), so an upstream format tweak cannot
crash the being.

**A `SelfReportService` orchestrates; the narrator renders.** Handed the being's
`memories()` and `state()` read-backs (plain dicts), it SELECTS the relevant
slice — the most-recent `recent_count` memories, in lived order — and hands them
to `MemorySummaryService`; when the being has no memories yet it falls back to
`NarrationService` over the present `state()`, so a being that has done nothing
truthfully describes the present rather than inventing a past.

**`POST /ask` exposes it, behind the always-on JWT guard.** The endpoint runs the
same `require_auth` dependency as `GET /state` (ADR 0005) and returns
`{"query", "report"}`. It is wired in `app.main` from config; the DB-less runtime
now wires the in-memory memory adapter (`bootstrap`) so a being remembers
in-process and `/ask` is grounded offline, with no database.

**The voice is config, not code.** `config/language.yaml` selects the narrator
(`deterministic` vs `model`), how many recent memories a report covers, the
salience at or above which a memory's felt affect is emphasized, and the phrasing
vocabulary (action verbs, outcome clauses, feeling words) — surfaced as
`SelfReportPolicy` / `NarrationPhrasing` through `ConfigService`. Retuning what
the being says is a YAML change only; an unmapped token falls back to itself, so
the being still speaks (grounded, if terse) before a word is authored.

## Consequences

- **A talking being, day one, fully offline.** The deterministic narrator needs
  no key, no network, and no trained model; the whole path is exercised by the
  suite without touching Claude.
- **Grounded by construction.** Every word traces to a logged memory (or the
  present state); the object is named by its perceived properties, and there is
  no `developerLabel` in a memory snapshot to leak (ADR 0002). Narration mutates
  nothing — asking leaves the being and its log exactly as they were (ADR 0022).
- **Fluency is a later upgrade, not a dependency.** Flipping `narrator.kind` to
  `model` routes the same fact-line prompt to the Claude adapter (S2); because the
  model only ever sees the structured experience, it still cannot invent. This is
  the adapter wiring reading R2 reuses.
- **The DB-less being now remembers in-process.** A small `bootstrap` change: the
  no-database runtime wires the in-memory memory adapter so `/ask` has grounded
  experience to report. Transient (lost on restart), like every other in-memory
  being's state; the Postgres path is unchanged.
- **Subject and salience-ranked queries are deferred (S3).** This slice answers
  every question with the recent-experience report (or the present); routing a
  query onto a subject or a salience-ranked recall is a later slice, not a silent
  gap.

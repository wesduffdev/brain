# 0040 — Reading-as-perception (`ReadingPerceptionService`)

- **Status:** Accepted
- **Date:** 2026-07-11

## Context

The reading faculty so far (R1–R6) lets the being ingest a document, grow a
retrieval store, and answer/converse about it — all in the **language layer, on
top of the sim** (ADR 0022): it reads, remembers *as text*, and speaks, but it
does not change the being's cognition. R7 is the payoff the plan reserved
(READING_VOICEBOX §4, §7): **reading a document should CHANGE the being** — form
memories and concepts, move curiosity — the way lived experience does.

The invariant makes this delicate. The being knows objects by **perceived
properties** and learns from **validated interactions** (`action → observed
outcome → memory/concept`), keyed on perceived tokens — never from raw text, and
**never** by letting a language model write state (BRIEF rule #6, ADR 0022). A
model will happily emit "add a memory that X"; if that could mutate cognition, the
language layer would be driving the sim. So "reading forms a memory/concept" must
go through the **same door** a lived interaction goes through — the validated
perception/cognition seam — and the language model must be **absent from the write
path** entirely.

## Decision

Add **`ReadingPerceptionService`** — a bridge that turns each ingested **section**
into a **validated perceptual observation** and routes it through the existing
cognition machinery, reusing it wholesale:

1. **Perceive (deterministic, model-free).** A section's salient **content tokens**
   are extracted from its text by `ReadingPerceptionPolicy.salient_tokens` — the
   most-frequent word tokens (length- and stopword-filtered, order-stable). The
   section is modelled as a perceivable `ObjectEntity` (id `read:<source>#<index>`,
   `properties = tokens`, `developer_label = source`) and run through the **real
   `PerceptionService`**, which **drops the developer label** (ADR 0002) — so the
   being perceives tokens, never the file name.
2. **Validate (the door).** The read is validated through **`ActionValidationService`**
   as an allowed reading `action` on the perceived section; an unknown action or an
   unperceived section is refused here. Cognition changes only *through* this gate.
3. **Learn (reuse).** The validated observation becomes an `InteractionEvent`
   (`action = read`, `observed = expected = [outcome]`, emotion unchanged) and is
   handed to the **same `MemoryService` and `ConceptService`** the interaction loop
   uses, inside **one unit of work per section** (ADR 0017): a memory keyed on
   perceived tokens, and a `(token → outcome)` concept that strengthens where a
   token **recurs across sections** (the regularity). Then the **same
   `ExplorationPolicyService`** folds the material into familiarity, so curiosity
   updates from what was read.

`Simulation.read(text, source)` ingests the document into sections (reusing the R1
`ingest` chunker, config-driven) and drives the bridge, advancing the clock **one
step per section** (reading takes time, so each memory keeps a distinct identity).
It requires a memory store; concepts are folded in when a concept store is present.
Tuning — the reading action/outcome, token extraction, sectioning, stopwords —
lives in `config/language.yaml` (`reading_perception:`) behind
`reading_perception_policy()`; retuning is config-only.

**Language stays strictly on top.** `ReadingPerceptionService` holds **no
`LanguageModelPort`** — there is no parameter through which model output could reach
memory/concept formation. Text enters the being **only** as perceived tokens judged
at the validated door; a raw model string can neither set a memory's structure nor
forge a row. The model reads and phrases (R4/R6); it never writes state.

## Consequences

- **Reading changes the being, faithfully.** After `read()`, `memories()` and
  `concepts()` reflect the document (keyed on perceived tokens, never a developer
  label) and curiosity shifts toward the novel — through the exact seams a lived
  interaction uses. No cognition machinery is duplicated.
- **The write path is provably model-free.** The bridge takes no language model; a
  structural test pins that its constructor exposes no model/language parameter, and
  behavior tests show state changes with no model present and that a hostile string
  cannot hijack a memory. This is the enforceable form of the ADR 0022 invariant.
- **The door is honest.** Reading and language commands both validate through
  `ActionValidationService`; a section that fails validation forms nothing.
- **Reading consumes time.** The clock advances per section — reading is a sequence
  of perceived moments — but reading drives no needs/emotion (it informs, it does
  not startle), keeping language non-authoritative over the drives.
- **Modelling choice — token salience, not comprehension.** A "concept" from reading
  is a frequency/co-recurrence regularity (`token → informs`), not semantic
  understanding; it is deliberately shallow and honest, and deepens naturally as the
  same material recurs. Consolidation into weights remains R5's separate job.
- **Trade-off.** Sectioning + top-N token salience is coarse; a section's meaning is
  reduced to its frequent words. This is the price of a *validated, deterministic*
  door — richer extraction would either need a model (which must not write state) or
  a heavier NLP dependency; either is a future slice behind the same seam.

# SELF-NARRATION — the being talks about its own experience

_Ask it what it's done; it tells you, grounded in its own memories._

Status: Proposed · Date: 2026-07-11 · Owner: director + orchestrator

A **planning document to cut parallel tickets from** (not an ADR, not code). This
is the **first language slice** — it comes *before* the reading faculty
([`docs/READING_VOICEBOX.md`](READING_VOICEBOX.md)) and front-loads the
conversational surface and voice that track needs. Fits the repo discipline:
one-sentence outcomes, TDD red-first, config-driven, deep modules, per-slice
gates, ADRs where warranted. See [`CLAUDE.md`](../CLAUDE.md) and
[`docs/BRIEF.md`](BRIEF.md).

---

## 1. The vision (north star)

> You ask the being *"what have you done recently?"* and it tells you, in plain
> language, what it actually did and felt — **"I pushed the round red thing and
> saw it bounce; that felt exciting."** Every word is grounded in its own logged
> experience: its memories, the outcomes it observed, and the emotion the moment
> carried. It can only say what it has lived.

---

## 2. Why this comes first (better than reading-first)

1. **Grounded by construction — no hallucination, no closed-world problem.** The
   being speaks *only* from its own experience log. The reading track's hard
   question ("how do we keep it from making things up / knowing things it
   shouldn't") simply does not arise here — the source of truth is the memory
   table.
2. **It's already ~80% built.** The two services that do exactly this already
   exist (built for v9 / ADR 0022) but are **unwired to any surface**:
   - `MemorySummaryService.summarize(memories)` — "Summarise… what the being
     remembers of its experiences so far. Use only these records; do not invent
     events." It already emits `- push obj_red_ball -> bounces`-shaped facts.
   - `NarrationService.narrate(snapshot)` — the present-tense companion.
   This slice mostly **wires up what's there**, realizing the "narrate" half of
   the language layer for the first time.
3. **No model required to start.** A deterministic **template narrator** built
   straight from the structured `Memory` fields is fully offline, deterministic,
   and testable — zero fine-tuning, MLX, or Ollama needed. A talking being on day
   one.
4. **It front-loads the reading track.** The `/ask` conversational surface, the
   language-model wiring, and the voicebox are exactly what the reading R-series
   needs. Build them here over data that already exists, and reading shrinks to
   "add a *new knowledge source* (documents + our own model) on top of an
   already-talking being."

---

## 3. Ground truth (what exists vs. what is new)

| Piece | State today | Where |
|---|---|---|
| `MemorySummaryService.summarize(memories)` | ✅ exists, **unwired** | `engine/app/services/memory_summary_service.py` |
| `NarrationService.narrate(snapshot)` | ✅ exists, **unwired** | `engine/app/services/narration_service.py` |
| `LanguageModelPort` seam (+ `FakeLanguageModel`) | ✅ exists — reuse | `engine/app/ports/language_model.py` |
| Read-backs: `memories()`, `interactions()`, `concepts()`, `beliefs()`, `explanations()` | ✅ mature | `engine/app/simulation.py` |
| The lived record itself | ✅ rich | `Memory`: `action`, `perceived_properties`, `observed_outcome`, `emotion_before/after`, `priority` (salience) |
| A conversational surface (`/ask`) | ❌ new | this plan (S1) |
| A deterministic template narrator | ❌ new (tiny) | this plan (S1) |
| Voice / TTS | ❌ new | this plan (S4) = reading R8 |

**The honest nuance (it's a feature).** The being knows objects by **perceived
properties**, not human names — there is deliberately no "red ball" label in its
head (ADR 0002). So faithfully it says *"the round red thing,"* not *"red ball."*
That is more psychologically true and it "depends on its learning," exactly as
intended. What it can say is bounded by what it has actually perceived and done.

**Invariant (unchanged):** narration sits **on top** and never controls the sim
(BRIEF rule #6, ADR 0022). It reads plain snapshot dicts and mutates nothing — the
self-report is a description laid over the being's state, never an input back into
its psychology.

---

## 4. Design

- **Where the words come from.** Start with a **deterministic template narrator**
  that implements `LanguageModelPort`, so `summarize()` / `narrate()` work with no
  external model: it renders the structured `Memory` fields directly
  (`action` + `observed_outcome` + affect from `emotion_after`/`priority`) into a
  plain sentence. This adds a real implementation behind an existing seam — no new
  port.
- **How it's asked.** A small `SelfReportService` selects the relevant slice of
  experience (recent memories, most-salient memories, or a subject) from the
  existing read-backs and hands it to the narrator; an authenticated `/ask`
  endpoint exposes it.
- **Fluency is an upgrade, not a dependency.** Swapping the deterministic narrator
  for the real `LanguageModelPort` (Claude now, our own local model when reading
  R1/R2 land) makes phrasing natural — while the model only ever sees the
  structured experience, so it still cannot invent.

---

## 5. Slices → tickets

| # | Slice (outcome) | New/changed seams | Observable | ADR? | Parallel |
|---|---|---|---|---|---|
| **S1** ⭐ | **"What have you done recently?" → grounded self-report** (deterministic, no model) | `SelfReportService` + a **deterministic template narrator** behind `LanguageModelPort`; wire `MemorySummaryService`/`NarrationService`; `POST /ask` (JWT) over `memories()`/`interactions()` | after living a few ticks, `/ask "what have you done recently?"` → "I pushed the round red thing and saw it bounce — that felt exciting", from the real log | **Yes** — wire v9 narration to a surface (update ADR 0022) | first |
| **S2** | **Fluent phrasing via `LanguageModelPort`** | select the model by config (deterministic/Fake in tests; Claude now; our local model when R1/R2 land); template stays as fallback | the same report phrased naturally, still grounded (model sees only the structured experience) | reuse ADR 0022 | after S1 · **shares the adapter wiring with reading R2** |
| **S3** | **Subject queries — "what do you know / how do you feel about X?"** | subject resolver (query term → perceived properties/concept) → narrate over `concepts()`/`beliefs()`/`explanations()` (v2/v7) | "what about hot things?" → "hot things hurt — I touched one, it caused pain, I was scared" | reuse R3/graph ADRs | after S1 |
| **S4** | **Speak it aloud (voicebox)** | `VoicePort` + espeak-ng (→ Piper); `FakeVoice` in tests; renderer "speaking" pose | hear the being tell you what it did | **Yes** — voice synthesis port (**= reading R8**) | after S1 · **shares the voicebox with reading R8** |

**First-playable:** **S1** alone — a being that truthfully reports its own
experience, fully offline and deterministic. **S2** makes it fluent; **S4** gives
it a voice.

---

## 6. Sequencing & sharing with the reading track

```
S1 ─ S2 ─┬─ S3
         └─ S4                       then:  R1 ─ R2 ─ R3 ─ R4 ─ …
                                            (reading + our own LLM)
shared build (done once, reused by reading):
   S2  ≡  reading R2  (LanguageModelPort local adapter)
   S4  ≡  reading R8  (voicebox / open-source TTS)
```

The **S-series ships first**. It stands up the `/ask` surface, the model-adapter
wiring, and the voice. The reading **R-series is sequenced after S** and then only
has to add the *new knowledge source*: ingest documents → grow a knowledge store →
fine-tune our own model → converse over that. Because S2 and R2 (and S4 and R8) are
the same work, build them once in S and reuse.

---

## 7. Cross-cutting

- **TDD red-first, behavior-named:** `test_being_reports_a_recent_experience`,
  `test_self_report_uses_only_logged_memories`,
  `test_report_names_perceived_properties_not_developer_label`.
- **Config-driven:** `config/language.yaml` (narrator selection: deterministic vs
  model; how many recent/salient memories to report). Only `ConfigService` reads
  config.
- **Deep modules:** deepen the existing narration services + add one
  `SelfReportService`; add a deterministic narrator behind the existing
  `LanguageModelPort` (no new port). Run `/legacy-deep-module-review` per slice;
  extend root `CONTEXT.md` (add: *self-report*, *narration*, *salience*).
- **Auth:** `/ask` runs `require_auth` (always-on JWT, ADR 0005).
- **Design boundary** (ADR 0013) unchanged.

---

## 8. Roadmap fit

This realizes the **narrate** half of **v9 (natural-language layer, ADR 0022)** —
which is built but unwired — on a surface, over the being's own experience. It is
the most natural next language step, and it de-risks the bigger reading faculty by
proving the conversational surface + voice first. Decisions (base model, toolchain,
voice engine, modality) are **inherited from
[`docs/READING_VOICEBOX.md`](READING_VOICEBOX.md) §11** — nothing new to decide.

# READING VOICEBOX — the being's own language faculty

_Read · learn · converse · speak — growing its knowledge from what you give it._

Status: Proposed · Date: 2026-07-11 · Owner: director + orchestrator

A **planning document to cut parallel tickets from** (not an ADR, not code). Split
out of [`docs/TRAINING.md`](TRAINING.md) (which now covers only Play Catch) and
built around the director's vision: the being runs **our own LLM** (fine-tuned from
an open-source base), reads a file, **learns from it and adds it to its knowledge**,
and can **hold a conversation** about it — all running **locally on the MacBook**
for now, with a clean path to a production model later.

Fits the repo discipline: one-sentence outcomes, TDD red-first, config-driven,
deep modules, per-slice deep-module + domain-model gates, ADRs where warranted.
See [`CLAUDE.md`](../CLAUDE.md) and [`docs/BRIEF.md`](BRIEF.md).

---

## 1. The vision (north star)

> You hand the being a document. It reads it (aloud, in its own synthesized
> voice) and **learns from it** — folding it into a knowledge store that starts
> from its open-source base model and **grows with everything you teach it**. Then
> you ask questions and have a back-and-forth about the document — or about
> anything it has learned — answered by **an LLM we built and run ourselves**,
> offline on your Mac. Ask about something it has read and it draws on that,
> citing it; ask something it hasn't been taught and it says so honestly (and can
> still reason from what it already knows).

Three capabilities, one faculty:
1. **Read** — ingest a provided file, speak it aloud.
2. **Learn & grow** — accumulate the document into a **growing knowledge store**
   (and into the being's cognition), so knowledge compounds across everything you
   give it.
3. **Converse** — grounded, cited question-answering and multi-turn dialogue that
   blends what it has read with its base knowledge.

---

## 2. Decisions locked (director, 2026-07-11)

| Fork | Decision | Consequence |
|---|---|---|
| How to build "our own LLM" | **Fine-tune a small open model** (LoRA) | Local, open-source, our own artifact; fluent enough to converse. |
| Base model | **Qwen2.5-3B-Instruct** (Apache-2.0) — a **test-scale** default | Comfortable on the 48 GB M4 Pro; fast LoRA fine-tunes; 7B+ headroom exists but is unneeded for a test. This is a test, not a production app. |
| Knowledge stance | **Learn-and-grow** — base knowledge **+** everything you teach it, accumulating over time | Evolved from the earlier "closed world / knows only what I give it." No refusal machinery to blind the base model; instead a **growing knowledge store** (see [§3](#3-knowledge-stance-learn-and-grow)). |
| First thing to see run | **Watch our own model train & generate** | Slice **R1**: LoRA fine-tune on the Mac's GPU (MLX), watch loss drop, sample generations in the document's style. |
| Where it runs | **Locally on a 48 GB M4 Pro MacBook** (Rancher + Docker) now; robust production model later | Model runs **host-native** for the Apple GPU (~30 GB usable when the Mac is otherwise idle); the engine container calls it behind `LanguageModelPort` ([§5](#5-runtime--deployment-local-mac-now-production-later)). |
| Local toolchain | **MLX-LM to fine-tune · Ollama to serve** | `mlx_lm.lora` trains (R1); fuse LoRA → GGUF → `ollama create`; Ollama serves on `:11434`; engine calls `host.docker.internal:11434`. One convert step per re-fine-tune. |
| Training data | **Claude at build-time only** | Claude synthesizes QA + consolidation pairs FROM your docs at build time; runtime inference is 100% our local model. R1 trains on raw text and needs none. |
| Consolidation cadence | **On a simulated 'sleep' tick** | The being's sleep cycle triggers an **async** host-native consolidation LoRA pass (minutes-long — never blocks the sim); `make consolidate` stays as a dev override. |
| Conversation modality | **Type questions → text + spoken answers** | Typed input; answers in text and read aloud via the voicebox (R8, TTS). No speech-to-text model needed. |

---

## 3. Knowledge stance: learn-and-grow

The being **starts from its open-source base model's knowledge** and **adds to it**
as you feed it documents. Two mechanisms make knowledge accumulate:

1. **A growing knowledge store (immediate).** Every document you give it is
   chunked, embedded, and **added to a persistent store that spans everything it
   has ever read**. At answer time the relevant passages are retrieved and the
   being answers from them — *citing which document* — blended with its base
   knowledge. New documents are usable the instant they're ingested (no retrain).
2. **Consolidation into weights (durable).** Periodically — the being's
   "sleep"/consolidation — we **LoRA-fine-tune on the accumulated documents** so
   recurring knowledge is baked into the model itself, not only the retrieval
   store. This is the "learn it for good" step.

**How it answers.** When you ask about a document it has read, it grounds the
answer in that document and cites it. When you ask something new, it says so
plainly — *"I haven't read anything about that"* — and may still reason from its
base knowledge, clearly distinguishing **what it read** from **what it already
knew**. It is transparent, not blinded. (This is the deliberate change from the
earlier closed-world framing, and it removes the need to mask the base model.)

---

## 4. Ground truth (what exists vs. what is new)

| Piece | State today | Where |
|---|---|---|
| A language seam `LanguageModelPort.complete(prompt)->str` | ✅ exists — **reuse it** | `engine/app/ports/language_model.py`; `FakeLanguageModel` for tests |
| A **Claude** adapter behind that port | ✅ exists (cloud) | `engine/app/adapters/claude_language_model.py` — we add a **local** adapter beside it |
| `NarrationService` / `MemorySummaryService` / `LanguageCommandService` | ⚠️ exist but **unwired to any surface** | `engine/app/services/*`; ADR 0022 defers HTTP wiring |
| Our own **local** LLM (fine-tuned, offline) | ❌ new | this plan |
| Document **ingestion / chunking** | ❌ new | this plan |
| **Growing** retrieval store / embeddings / grounding | ❌ new | this plan (pgvector-ready — roadmap v11) |
| **Voice / TTS / audio** (the voicebox) | ❌ new | this plan (R8) |
| Memory / concept / graph cognition (to "learn from" a doc) | ✅ mature — bridge into it | `MemoryService`, `ConceptService`, `KnowledgeGraphService` |
| Model-service **sidecar** pattern | ✅ precedent (`ml-trainer`) | roadmap **v8** is "model-service sidecar + multi-model inference" — this faculty is its vehicle |

**Invariant (unchanged):** the language faculty sits **on top** and never controls
the sim (BRIEF rule #6, ADR 0022). It reads, remembers, and converses; it does not
drive needs/emotion/decision. Reading *changes* the being only through the
validated perception/cognition door (R7), never by letting model output write
state directly.

---

## 5. Runtime & deployment (local Mac now, production later)

**The gotcha that shapes this:** Docker containers on macOS — including under
**Rancher Desktop** — run inside a Linux VM, and the **Apple-Silicon GPU (Metal)
is not passed through**. So anything running *in a container* on your Mac is
**CPU-only**, no matter how capable the machine's GPU is.

**Therefore, for local dev the model runs host-native and the engine calls it:**

```
  ┌───────────────────────── your MacBook (host) ─────────────────────────┐
  │                                                                        │
  │   host-native (Metal GPU):  MLX-LM fine-tunes → fuse → GGUF →          │
  │        ▲                    Ollama serves (OpenAI-style) on :11434     │
  │        │                                                               │
  │   ┌────┴─────────── Rancher / Docker (Linux VM, CPU) ──────────────┐   │
  │   │  engine container ── LocalLanguageModel adapter                │   │
  │   │      calls host.docker.internal:11434  (LanguageModelPort)     │   │
  │   │  postgres · retrieval/embeddings (CPU, in-container is fine)    │   │
  │   └────────────────────────────────────────────────────────────────┘  │
  └────────────────────────────────────────────────────────────────────────┘
```

- **Fine-tuning (GPU work):** host-native on Metal via **MLX-LM** (`mlx_lm.lora`) —
  drives R1's live "watch it train" view and produces the LoRA adapter.
- **Serving:** host-native **Ollama** on `:11434` (Metal, OpenAI-style HTTP). After
  each fine-tune, **fuse the LoRA into the base, convert to GGUF, and `ollama
  create`** the model; Ollama then serves it. (One convert step per re-fine-tune —
  the accepted trade for Ollama's model management/UX.)
- **The engine stays containerized** and reaches the model over
  `host.docker.internal:11434` via a `LocalLanguageModel` adapter behind the
  existing `LanguageModelPort`.
- **Embeddings/retrieval are cheap** — they run CPU-in-container fine; only the LLM
  needs the host GPU.
- **Production later:** the model becomes a **GPU container** (PyTorch + PEFT/LoRA,
  served by vLLM/TGI on CUDA) behind the *same* port. **Only the adapter's endpoint
  changes** — no service rewrites. The seam is what makes local-Mac → prod a config
  swap.

---

## 6. Component choices (recommendations)

| Component | Recommendation | Notes / alternatives |
|---|---|---|
| **Base model** | **Qwen2.5-3B-Instruct** (Apache-2.0) — the chosen **test-scale** default: comfortable on the 48 GB M4 Pro (~6–7 GB serve, ~10–16 GB LoRA fine-tune), quick to iterate | Lighter: 1.5B / 0.5B. Headroom for 7B (even 14B via 4-bit) exists but is overkill for a test. SmolLM2 · GPT-2-small (most transparent for "watch it learn"). |
| **Fine-tune (local, Mac)** | **MLX-LM LoRA** (`mlx_lm.lora`) — Metal-native, fast, adapter *is* "our model" | The R1 first-cut runs here. |
| **Serve (local, Mac)** | **Ollama** on `:11434` (Metal, OpenAI-style) — serves the **fused + GGUF** fine-tuned model | Reached from the engine via `host.docker.internal:11434`. One fuse→GGUF→`ollama create` step per fine-tune. |
| **Fine-tune / serve (prod)** | **PyTorch + PEFT/LoRA** on CUDA, served by **vLLM/TGI** — same `LanguageModelPort` | Local-Mac → prod is an endpoint swap. |
| **Embeddings (retrieval)** | **bge-small-en-v1.5** or **all-MiniLM-L6-v2** (sentence-transformers), CPU-in-container | any small local open embedder |
| **Knowledge store** | Start **SQLite / in-memory**, **pgvector-ready** behind a `RetrievalPort` | pgvector is roadmap **v11**; the store is **persistent + cumulative** across docs |
| **TTS (voicebox)** | **espeak-ng** first (offline, deterministic), then **Piper** (neural, offline, MIT) | can run CPU-in-container or host; Kokoro/Coqui as upgrades |
| **Consolidation/QA training data** | **Claude at build time only** — synthesize QA + consolidation pairs FROM your docs (a one-off dataset step) | runtime inference stays 100% our own/local; R1 trains on raw doc text and needs none |

---

## 7. Slices → tickets

Each is a card (one-sentence outcome, acceptance criteria, affected files/ADRs).
Ordered so the **first observable is the model training** (director's first cut).

| # | Slice (outcome) | New/changed seams | Observable | ADR? | Parallel |
|---|---|---|---|---|---|
| **R1** ⭐ | **Ingest a doc → LoRA-fine-tune our own model on the Mac's GPU → watch it train & generate** | `language/` module, `ingest` (chunk/clean), MLX-LM LoRA fine-tune, host-native run (§5), `make train-language DOC=path` | loss curve + sampled generations in the doc's style; adapter artifact saved | **Yes** — "Our own language model (open base + LoRA, host-native on Mac)" | independent (first) |
| **R2** | **Serve our model via Ollama + local adapter behind `LanguageModelPort`** — our model answers offline | fuse R1's LoRA → GGUF → `ollama create`; `adapters/local_language_model.py` calls `host.docker.internal:11434`; config selects adapter/endpoint | `complete(prompt)` returns text from **our** model via Ollama, no network beyond the host | update ADR 0022 (local adapter) | after R1 |
| **R3** | **Growing knowledge store** — everything read accumulates and is retrievable | `ingest` → embeddings → **persistent, cumulative** vector store behind a `RetrievalPort` (SQLite/in-mem, pgvector-ready) | after ingesting several docs, retrieval spans **all** of them | **Yes** — retrieval port + growing knowledge store | after R1, parallel w/ R2 |
| **R4** | **Grounded, cited answers (blend read + base)** | `ReadingQAService`: retrieve → grounded prompt → our model → answer citing the source; if unread, say so and optionally reason from base knowledge | test: read topic → cited grounded answer; unread topic → "I haven't read about that" (+ optional base answer), clearly distinguished | reuse R3 ADR | after R2, R3 |
| **R5** | **Knowledge consolidation ("sleep") fine-tune** — bake accumulated docs into weights | the being's **sleep cycle triggers an async** host-native LoRA pass (never blocks the tick) over Claude-synthesized consolidation pairs; `make consolidate` dev override; re-fuse → GGUF → `ollama create` | after a sleep/consolidation, the model recalls consolidated facts **without** retrieval | note in R1 ADR + reading-as-perception ADR | after R3 (data) + sleep signal |
| **R6** | **Multi-turn conversation** — a real back-and-forth | `ConversationService` (history-aware, grounded each turn); `POST /chat` | a several-turn dialogue that stays grounded and cites sources | — | after R4 |
| **R7** | **Reading becomes a learning event in cognition** — the doc *changes* the being via the validated perception door (not the LM) | route ingested sections through `PerceptionService`/`ActionValidationService` → `MemoryService`/`ConceptService` | after reading, `memories()`/`concepts()` reflect it; curiosity updates | **Yes** — reading-as-perception | after R4 |
| **R8** | **Voicebox — read aloud + speak answers** | `VoicePort` (`synthesize`), `espeak_voice` then `piper_voice`, `FakeVoice` in tests; renderer "speaking" pose | hear the document read; hear answers spoken; `POST /read`, `POST /speak` (JWT) | **Yes** — "Voice synthesis port + open-source TTS" | after R2 (independent of QA) |
| **R9** *(optional)* | **From-scratch tiny Transformer** — a pure ML-learning build (tokenizer + small Transformer in PyTorch) | standalone learning exercise; not the shipping brain | our from-scratch model generates corpus-style text | optional ADR | independent |

**First-playable path:** **R1 → R2 → R3 → R4** = fine-tune our model on a file, then
ask it grounded, cited questions that blend what it read with what it knows. R8
(voice) can land in parallel; R5/R6/R7 deepen it.

---

## 8. Cross-cutting

- **TDD red-first, behavior-named:** `test_answers_cite_the_document_they_came_from`,
  `test_unread_topic_is_flagged_as_unlearned`,
  `test_finetuned_model_generates_in_corpus_style`,
  `test_new_document_adds_to_retrievable_knowledge`, `test_reading_forms_a_memory`.
- **Config-driven, safe defaults:** `config/language.yaml` (base model, fine-tune
  params, **model-server endpoint**, retrieval k, citation on) and
  `config/voice.yaml`. Only `ConfigService` reads config; the host endpoint is
  deploy/ops config (env), like `DATABASE_URL`.
- **Deep modules:** one `language` module with a small surface (ingest, train,
  ask, converse, consolidate) hiding model/retrieval internals; reuse
  `LanguageModelPort`. Run `/legacy-deep-module-review` per slice; extend root
  `CONTEXT.md` (add: *voicebox*, *utterance*, *reading*, *knowledge store*,
  *grounded answer*, *citation*, *consolidation*, *fine-tune*).
- **Persistence:** the knowledge store, ingested docs/chunks/embeddings,
  conversation turns, and model-run metadata **persist and accumulate**
  transactionally (ADR 0017).
- **Auth:** every new endpoint runs `require_auth` (always-on JWT, ADR 0005).
- **Design boundary** (ADR 0013) unchanged.

---

## 9. Relationship to the roadmap & ADR 0022

- **v9 (natural-language layer, ADR 0022)** — this plan **finishes** it: wires the
  language services to a surface and adds a **local, our-own** adapter beside the
  Claude one, keeping language strictly on top.
- **v8 (model-service sidecar + multi-model inference)** — the host-native model
  server (Mac) and the future GPU container (prod) are the v8 vehicle behind one
  port.
- **v11 (pgvector)** — now central, since knowledge grows; R3's retrieval port is
  built pgvector-ready.
- **v6 (memory retrieval + consolidation)** — R5's consolidation fine-tune is the
  language analogue of memory consolidation; R7 folds reading into the same
  memory/concept machinery.
- **Play Catch** lives in [`docs/TRAINING.md`](TRAINING.md), independent — the two
  can run as parallel waves.

---

## 10. New ADRs to author (next free `NNNN`, currently 0024+)

- **Our own language model** (R1) — open base + LoRA; host-native on Mac / GPU
  container in prod behind `LanguageModelPort`; local→prod is an endpoint swap.
- **Retrieval port + growing knowledge store** (R3) — persistent, cumulative,
  pgvector-ready; grounded + cited answering (R4).
- **Reading-as-perception** (R7) — a document changes the being only through the
  validated cognition door.
- **Voice synthesis port + open-source TTS** (R8).
- Update ADR 0022 (local adapter + surface wiring), the ADR index, the roadmap,
  and the governance index in `README.md` in the same slices — per CLAUDE.md.

---

## 11. Decisions — all resolved (director, 2026-07-11)

Every open question is settled; tickets are cut from the §7 slices. **No code
starts yet** — the work lands on its own branch after the cards exist.

| Question | Decision |
|---|---|
| Base model & hardware | **Qwen2.5-3B-Instruct** (test-scale) on the 48 GB M4 Pro |
| Mac toolchain | **MLX-LM** fine-tunes (`mlx_lm.lora`); **Ollama** serves the fused + GGUF model on `:11434` |
| Training data | **Claude at build time only** (runtime 100% local; R1 needs none — trains on raw text) |
| Consolidation cadence | on a **simulated 'sleep' tick** → async host-native job; `make consolidate` dev override |
| Conversation modality | **type questions → text + spoken answers** (voicebox R8; no speech-to-text) |
| Cut cards | **now** — mint the R-slice cards; do not start code |

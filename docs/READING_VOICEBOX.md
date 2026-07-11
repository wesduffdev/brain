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
| Knowledge stance | **Learn-and-grow** — base knowledge **+** everything you teach it, accumulating over time | Evolved from the earlier "closed world / knows only what I give it." No refusal machinery to blind the base model; instead a **growing knowledge store** (see [§3](#3-knowledge-stance-learn-and-grow)). |
| First thing to see run | **Watch our own model train & generate** | Slice **R1**: LoRA fine-tune on the Mac's GPU (MLX), watch loss drop, sample generations in the document's style. |
| Where it runs | **Locally on the MacBook** (Rancher + Docker) now; robust production model later | Model runs **host-native** for the Apple GPU; the engine container calls it behind `LanguageModelPort` ([§5](#5-runtime--deployment-local-mac-now-production-later)). |

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
  │   host-native model server (Metal GPU) ── MLX-LM  (fine-tune + serve)  │
  │        ▲  OpenAI-style HTTP on localhost:PORT     └ or Ollama (serve)  │
  │        │                                                               │
  │   ┌────┴─────────── Rancher / Docker (Linux VM, CPU) ──────────────┐   │
  │   │  engine container ── LocalLanguageModel adapter                │   │
  │   │      calls host.docker.internal:PORT   (LanguageModelPort)     │   │
  │   │  postgres · retrieval/embeddings (CPU, in-container is fine)    │   │
  │   └────────────────────────────────────────────────────────────────┘  │
  └────────────────────────────────────────────────────────────────────────┘
```

- **Serving + fine-tuning (GPU work):** host-native on Metal. Recommend **MLX-LM**
  (`mlx_lm.lora` for LoRA fine-tuning, `mlx_lm.server` for OpenAI-style inference)
  — one Metal-native toolchain for both R1 (train) and R2 (serve). **Ollama** is
  the zero-fine-tune quick-start for serving a base model. (PyTorch-MPS also works
  but is rougher for training than MLX.)
- **The engine stays containerized** and reaches the model over
  `host.docker.internal:PORT` via a `LocalLanguageModel` adapter behind the
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
| **Base model** | A small open-weight instruct model — **Qwen2.5-1.5B-Instruct** (Apache-2.0) as a good conversation/size balance; **0.5B** if RAM-constrained, up to **3B** if the Mac has headroom | SmolLM2 (Apache, on-device) · GPT-2-small (fully MIT, most transparent for "watch it learn"). Pick by your Mac's unified memory (8/16/32 GB). |
| **Fine-tune (local, Mac)** | **MLX-LM LoRA** (`mlx_lm.lora`) — Metal-native, fast, adapter *is* "our model" | The R1 first-cut runs here. |
| **Serve (local, Mac)** | **MLX-LM server** (OpenAI-style) host-native; **Ollama** for a quick base-model start | Reached from the engine via `host.docker.internal`. |
| **Fine-tune / serve (prod)** | **PyTorch + PEFT/LoRA** on CUDA, served by **vLLM/TGI** — same `LanguageModelPort` | Local-Mac → prod is an endpoint swap. |
| **Embeddings (retrieval)** | **bge-small-en-v1.5** or **all-MiniLM-L6-v2** (sentence-transformers), CPU-in-container | any small local open embedder |
| **Knowledge store** | Start **SQLite / in-memory**, **pgvector-ready** behind a `RetrievalPort` | pgvector is roadmap **v11**; the store is **persistent + cumulative** across docs |
| **TTS (voicebox)** | **espeak-ng** first (offline, deterministic), then **Piper** (neural, offline, MIT) | can run CPU-in-container or host; Kokoro/Coqui as upgrades |
| **Consolidation/QA training data** | hand-authored + templates; **optionally** a teacher model (Claude) at **build time only** to synthesize QA pairs from your docs | runtime stays 100% our own/local — see open question |

---

## 7. Slices → tickets

Each is a card (one-sentence outcome, acceptance criteria, affected files/ADRs).
Ordered so the **first observable is the model training** (director's first cut).

| # | Slice (outcome) | New/changed seams | Observable | ADR? | Parallel |
|---|---|---|---|---|---|
| **R1** ⭐ | **Ingest a doc → LoRA-fine-tune our own model on the Mac's GPU → watch it train & generate** | `language/` module, `ingest` (chunk/clean), MLX-LM LoRA fine-tune, host-native run (§5), `make train-language DOC=path` | loss curve + sampled generations in the doc's style; adapter artifact saved | **Yes** — "Our own language model (open base + LoRA, host-native on Mac)" | independent (first) |
| **R2** | **Local LLM adapter behind `LanguageModelPort`** — our model answers offline | `adapters/local_language_model.py` (calls the host model server via `host.docker.internal`); config selects the adapter/endpoint | `complete(prompt)` returns text from **our** model, no network beyond the host | update ADR 0022 (local adapter) | after R1 |
| **R3** | **Growing knowledge store** — everything read accumulates and is retrievable | `ingest` → embeddings → **persistent, cumulative** vector store behind a `RetrievalPort` (SQLite/in-mem, pgvector-ready) | after ingesting several docs, retrieval spans **all** of them | **Yes** — retrieval port + growing knowledge store | after R1, parallel w/ R2 |
| **R4** | **Grounded, cited answers (blend read + base)** | `ReadingQAService`: retrieve → grounded prompt → our model → answer citing the source; if unread, say so and optionally reason from base knowledge | test: read topic → cited grounded answer; unread topic → "I haven't read about that" (+ optional base answer), clearly distinguished | reuse R3 ADR | after R2, R3 |
| **R5** | **Knowledge consolidation ("sleep") fine-tune** — bake accumulated docs into weights | periodic LoRA fine-tune over the accumulated store; a `make consolidate` (or a consolidation tick) | after consolidation, the model recalls consolidated facts **without** retrieval | note in R1 ADR | after R3 (data) |
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

## 11. Open questions for the director

1. **Mac toolchain.** OK to standardize local on **MLX-LM** (Metal-native
   fine-tune *and* serve), with **Ollama** as a quick serve-only fallback — or a
   preference?
2. **Base model / RAM.** Roughly how much unified memory does the Mac have? That
   sets the default base size (**Qwen2.5-0.5B** safe everywhere; **1.5B** good on
   16 GB+; **3B** on 32 GB+).
3. **Teacher for training data.** For consolidation/QA pairs, is **Claude at build
   time only** acceptable to synthesize the dataset from your docs (runtime stays
   100% ours/local), or keep it hand-authored?
4. **Consolidation cadence.** Run consolidation **on demand** (`make consolidate`),
   or **automatically** after N new documents / on a "sleep" tick?
5. **Conversation modality.** Typed questions with **spoken + text** answers to
   start (voice via R8), or full voice-in/voice-out later?
6. **Cut cards?** Want the orchestrator to mint the Trello cards for R1→R4 (+R8)
   next, or keep planning first?

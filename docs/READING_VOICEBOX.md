# READING VOICEBOX — the being's own language faculty

_Read · learn · converse · speak — grounded only in what you give it._

Status: Proposed · Date: 2026-07-11 · Owner: director + orchestrator

A **planning document to cut parallel tickets from** (not an ADR, not code). It
was split out of [`docs/TRAINING.md`](TRAINING.md) (which now covers only Track B —
Play Catch) and expanded to the director's larger vision: the being runs **our own
LLM**, reads a file, **learns from it**, and can **hold a conversation** about it —
and it **knows nothing beyond the documents you give it**.

Fits the repo discipline: one-sentence outcomes, TDD red-first, config-driven,
deep modules, per-slice deep-module + domain-model gates, ADRs where warranted.
See [`CLAUDE.md`](../CLAUDE.md) and [`docs/BRIEF.md`](BRIEF.md).

---

## 1. The vision (north star)

> You hand the being a document. It reads it (aloud, in its own synthesized
> voice), and *learns from it*. Then you ask questions and have a back-and-forth
> conversation about the document — answered by **an LLM we built and run
> ourselves**, entirely offline. Ask it anything the document doesn't cover and it
> tells you, honestly, that it only knows what you've shared with it.

Three capabilities, one faculty:
1. **Read** — ingest a provided file into the being's language faculty (and into
   its cognition), and speak it aloud.
2. **Converse** — grounded question-answering and multi-turn dialogue about the
   document, powered by our own fine-tuned model.
3. **Closed world** — the being answers only from your documents and refuses,
   honestly, beyond them.

---

## 2. Decisions locked (director, 2026-07-11)

| Fork | Decision | Consequence |
|---|---|---|
| How to build "our own LLM" | **Fine-tune a small open model** on the document | Local, open-source, our own artifact; fluent enough to converse. Not from-scratch for the shipping brain (from-scratch kept as optional slice R9). |
| Enforce "knows only what I give it" | **Both belts** | Corpus-biased + refusal-trained fine-tuning **and** grounded-retrieval + honest refusal at answer time. |
| First thing to see run | **Watch our own model train & generate** | Slice **R1** is the fine-tune run: feed the corpus, watch loss drop, sample generations in the document's style. |

---

## 3. Honest constraint: closed-world is *behavioral*, not architectural

This matters, so it is stated up front. A fine-tuned **open** base model (GPT-2,
Qwen2.5, SmolLM2, …) still carries the general knowledge it was pretrained on — we
cannot surgically remove that. So "the being knows nothing outside what I give it"
is enforced **behaviorally**, by three mechanisms stacked together:

1. **Grounded answering** — every answer is built only from passages retrieved out
   of *your* documents; the model is given those passages and instructed to use
   nothing else.
2. **Honest refusal** — if retrieval finds nothing relevant, the being says so
   ("I only know what you've shared with me") instead of drawing on latent
   knowledge.
3. **Refusal-trained fine-tuning** — the fine-tune set teaches the model to prefer
   the corpus and to refuse out-of-corpus questions.

Together these make the being *behave* as a closed world. The **only** way to get a
*hard architectural* guarantee (a model that literally has no other knowledge) is
to train from scratch on the corpus alone — captured as optional slice **R9**,
which also doubles as the pure "build our own model from scratch" ML exercise.
If the behavioral guarantee ever proves insufficient, R9 is the escalation.

---

## 4. Ground truth (what exists vs. what is new)

| Piece | State today | Where |
|---|---|---|
| A language seam `LanguageModelPort.complete(prompt)->str` | ✅ exists — **reuse it** | `engine/app/ports/language_model.py`; `FakeLanguageModel` for tests |
| A **Claude** adapter behind that port | ✅ exists (cloud, not ours) | `engine/app/adapters/claude_language_model.py` — we add a **local** adapter beside it |
| `NarrationService` / `MemorySummaryService` / `LanguageCommandService` | ⚠️ exist but **unwired to any surface** | `engine/app/services/*`; ADR 0022 defers HTTP wiring |
| Our own **local** LLM (fine-tuned, offline) | ❌ new | this plan |
| Document **ingestion / chunking** | ❌ new | this plan |
| **Retrieval** index / embeddings / grounding | ❌ new | this plan (pgvector-ready — roadmap v11) |
| **Voice / TTS / audio** (the voicebox) | ❌ new | this plan (R8) |
| Memory / concept / graph cognition (to "learn from" a doc) | ✅ mature — bridge into it | `MemoryService`, `ConceptService`, `KnowledgeGraphService` |
| Model-service **sidecar** pattern | ✅ precedent (`ml-trainer`) | roadmap **v8** is literally "model-service sidecar + multi-model inference" — this faculty is its natural vehicle |

**Invariant (unchanged):** the language faculty sits **on top** and never controls
the sim (BRIEF rule #6, ADR 0022). It reads, remembers, and converses; it does not
drive needs/emotion/decision. Reading *changes* the being only through the
validated perception/cognition door (R7), never by letting model output write
state directly.

---

## 5. Architecture

```
   your file
      │
      ▼
┌─────────────┐   corpus (chunks)         ┌──────────────────────┐
│  Ingest      │──────────────┬──────────▶│ Fine-tune (LoRA)     │  R1/R5
│  + chunk     │              │           │ small open base      │──▶ our model
└─────────────┘              │           └──────────────────────┘   (adapter artifact)
      │                      │                        │
      │ embeddings           ▼                        ▼ behind LanguageModelPort (R2)
      ▼               ┌──────────────┐        ┌──────────────────┐
┌─────────────┐       │ Retrieval    │  R3    │ Local LLM adapter│
│ Vector index │◀─────│ (top-k       │───────▶│ (our model,      │
│ (doc only)   │      │  passages)   │        │  offline)        │
└─────────────┘       └──────────────┘        └──────────────────┘
      │                      │                        │
      │        ┌─────────────┴──────────┐             │
      ▼        ▼                        ▼             ▼
┌──────────────────────────────────────────────────────────┐
│ ReadingQAService (R4): retrieve → grounded prompt → answer │
│   or honest refusal if nothing relevant                    │
│ ConversationService (R6): multi-turn, history-aware        │
└──────────────────────────────────────────────────────────┘
      │                                              │
      ▼ (R7) learn into cognition                    ▼ (R8) speak
┌──────────────────────┐                    ┌──────────────────┐
│ Memory/Concept/Graph │                    │ VoicePort → TTS  │
│ (perception door)    │                    │ (espeak → Piper) │
└──────────────────────┘                    └──────────────────┘
```

Everything heavy (fine-tune + model inference + embeddings) runs in a **language
sidecar** container (deps in `requirements-language.txt`, kept off the lean engine
image — same pattern as `ml-trainer`). The engine talks to it behind
`LanguageModelPort` + a small retrieval/QA port.

---

## 6. Component choices (recommendations)

| Component | Recommendation | Alternatives / notes |
|---|---|---|
| **Base model** | **Qwen2.5-0.5B-Instruct** (Apache-2.0) — tiny, instruct-tuned (converses out of the box), fine-tunes on modest hardware | **SmolLM2-360M** (Apache, on-device) · **GPT-2-small** (fully MIT, most transparent for "watch it learn") · Llama-3.2-1B (heavier, community license) |
| **Fine-tune method** | **LoRA / QLoRA** via PEFT — parameter-efficient, CPU-feasible (slow) / small-GPU-fast, and the adapter *is* "our model" artifact | Full fine-tune of a 0.5B model is also viable if a GPU is available |
| **Embeddings (retrieval)** | **bge-small-en-v1.5** or **all-MiniLM-L6-v2** via sentence-transformers — small, open, fast | gte-small; any local open embedder |
| **Vector store** | Start **in-memory / SQLite**; make it **pgvector-ready** | pgvector is roadmap **v11** — the port lets us swap in without touching services |
| **TTS (voicebox)** | **espeak-ng** first (offline, deterministic, robotic — great default/test), then **Piper** (neural, offline, MIT) in the sidecar | Kokoro / Coqui as upgrades |
| **Fine-tune data for refusal (R5)** | Hand-authored + template QA/refusal pairs; **optionally** use a teacher model (Claude) at **build time only** to synthesize QA + refusal pairs from the doc | Runtime stays 100% our own/local; teacher is build-time distillation only — see open question Q3 |

---

## 7. Closed-world enforcement — both belts, concretely

**Belt 1 — training (corpus-biased + refusal-trained).** R1 fine-tunes on the
document text (domain adaptation). R5 adds instruction pairs: in-document questions
→ grounded answers; out-of-document questions → a refusal template. The model
*learns to prefer the corpus and to refuse*.

**Belt 2 — inference (grounded retrieval + refusal).** R4 retrieves top-k passages;
if the best similarity is below a config threshold, the being refuses without
calling the model on latent knowledge. When it does answer, the prompt contains
*only* retrieved passages + the instruction to use nothing else.

Both are **config-gated and default to a safe stance** (grounding on, refusal
threshold set) so behavior is predictable. This is the "belt and suspenders" the
director chose.

---

## 8. Slices → tickets

Each is a card (one-sentence outcome, acceptance criteria, affected files/ADRs).
Ordered so the **first observable is the model training** (director's first cut).

| # | Slice (outcome) | New/changed seams | Observable | ADR? | Parallel |
|---|---|---|---|---|---|
| **R1** ⭐ | **Ingest a doc → fine-tune our own small model → watch it train & generate** | `language/` module, `ingest` (chunk/clean), `train_language_model` (LoRA on Qwen2.5-0.5B), `requirements-language.txt`, `language` sidecar | `make train-language DOC=path` → loss curve + sampled generations in the doc's style; adapter artifact saved | **Yes** — "Our own language model (small open base + LoRA)" | independent (first) |
| **R2** | **Local LLM adapter behind `LanguageModelPort`** — our model answers offline | `adapters/local_language_model.py` beside `claude_language_model.py`; config selects the adapter | `complete(prompt)` returns text from **our** model, no network | update ADR 0022 (add local adapter) | after R1 |
| **R3** | **Document retrieval index** — top-k passages from the doc only | `ingest` → embeddings → vector store behind a `RetrievalPort` (in-memory/SQLite, pgvector-ready) | query returns the k most relevant passages of your doc | small ADR (retrieval port) | after R1, parallel w/ R2 |
| **R4** | **Grounded QA + honest refusal** (closed-world, inference belt) | `ReadingQAService`: retrieve → grounded prompt → our model → answer, else refuse | test: in-doc question → grounded answer; out-of-doc question → "I only know what you've given me" | reuse R3 ADR | after R2, R3 |
| **R5** | **Refusal-trained fine-tune** (closed-world, training belt) | extend R1's dataset with in-doc QA + out-of-doc refusal pairs (hand/template, optional teacher-synthesized) | tuned model refuses out-of-doc more reliably than the base | note in R1 ADR | after R1 (data), before/with R4 |
| **R6** | **Multi-turn conversation** — a real back-and-forth about the doc | `ConversationService` (history-aware, grounded each turn); `POST /chat` | a several-turn dialogue that stays grounded across turns | — | after R4 |
| **R7** | **Reading becomes a learning event in cognition** — the doc *changes* the being via the validated perception door (not the LM) | route ingested sections through `PerceptionService`/`ActionValidationService` → `MemoryService`/`ConceptService` | after reading, `memories()`/`concepts()` reflect it; curiosity updates | **Yes** — reading-as-perception (keeps language non-authoritative) | after R4 |
| **R8** | **Voicebox — read aloud + speak answers** | `VoicePort` (`synthesize`), `espeak_voice` then `piper_voice` sidecar, `FakeVoice` in tests; renderer "speaking" pose | hear the document read; hear answers spoken; `POST /read`, `POST /speak` (JWT) | **Yes** — "Voice synthesis port + open-source TTS" | after R2 (independent of QA) |
| **R9** *(optional)* | **From-scratch tiny Transformer** — the pure ML build + **hard** closed-world guarantee | tokenizer + small Transformer trained only on the corpus, in PyTorch | our from-scratch model generates corpus-style text; a model with *no* outside knowledge | **Yes** — from-scratch LM + hard closed-world | after R1 (independent) |
| **R10** *(optional)* | **pgvector-backed retrieval** (roadmap v11) as the corpus grows | swap the `RetrievalPort` impl to pgvector | same behavior, durable/scalable index | reuse R3 ADR | after R3 |

**First-playable path:** **R1 → R2 → R3 → R4** = ingest a file, fine-tune our model,
and ask it grounded questions that refuse outside knowledge. R8 (voice) can land in
parallel; R6/R7 deepen it.

---

## 9. Cross-cutting

- **TDD red-first, behavior-named:** `test_answers_are_grounded_in_the_document`,
  `test_refuses_questions_outside_the_document`,
  `test_finetuned_model_generates_in_corpus_style`,
  `test_reading_forms_a_memory`.
- **Config-driven, safe defaults:** `config/language.yaml` (base model,
  fine-tune params, retrieval k + refusal threshold, adapter selection) and
  `config/voice.yaml`. Only `ConfigService` reads config.
- **Deep modules:** one `language` module with a small surface (ingest, train,
  ask, converse) hiding model/retrieval internals; reuse `LanguageModelPort` rather
  than a parallel seam. Run `/legacy-deep-module-review` per slice; extend root
  `CONTEXT.md` (add: *voicebox*, *utterance*, *reading*, *grounded answer*,
  *honest refusal*, *closed corpus*, *fine-tune*).
- **Persistence:** ingested docs, chunks, embeddings, conversation turns, and
  model-run metadata persist transactionally (ADR 0017); new tables stage in repos.
- **Auth:** every new endpoint runs `require_auth` (always-on JWT, ADR 0005).
- **Infra:** a `language` sidecar (fine-tune + inference + embeddings); GPU
  optional, CPU + LoRA supported (slower). Keeps heavy deps off the engine image.
- **Design boundary** (ADR 0013) unchanged.

---

## 10. Relationship to the roadmap & ADR 0022

- **v9 (natural-language layer, ADR 0022)** — this plan **finishes** it: wires the
  language services to a surface and adds a **local, our-own** adapter beside the
  Claude one, keeping language strictly on top.
- **v8 (model-service sidecar + multi-model inference)** — the `language` sidecar
  *is* the v8 vehicle (fine-tune job + inference service, versioned artifacts).
- **v11 (pgvector)** — R3's retrieval port is built pgvector-ready; R10 realizes it.
- **Play Catch** lives in [`docs/TRAINING.md`](TRAINING.md) and is independent —
  the two can run as parallel waves.

---

## 11. New ADRs to author (next free `NNNN`, currently 0024+)

- **Our own language model** (R1) — small open base + LoRA; local artifact; the
  closed-world stance is behavioral (grounding + refusal + refusal-training).
- **Retrieval port + grounded answering** (R3/R4) — pgvector-ready; refusal
  threshold.
- **Reading-as-perception** (R7) — a document changes the being only through the
  validated cognition door.
- **Voice synthesis port + open-source TTS** (R8).
- **From-scratch tiny Transformer + hard closed-world** (R9, if built).
- Update ADR 0022 (local adapter + surface wiring), the ADR index, the roadmap,
  and the governance index in `README.md` in the same slices — per CLAUDE.md.

---

## 12. Open questions for the director

1. **Compute.** Is there a **GPU** available, or should we assume **CPU-only**?
   (Drives base-model size — 0.5B fits CPU+LoRA; a GPU unlocks 1–3B and full
   fine-tunes.)
2. **Base model.** OK with **Qwen2.5-0.5B-Instruct** as the default (or prefer
   **SmolLM2-360M**, or **GPT-2-small** for maximum "watch it learn" transparency)?
3. **Teacher for training data.** For R5's refusal/QA pairs, is it acceptable to
   use **Claude at build time only** to synthesize the fine-tune dataset from your
   doc (runtime stays 100% our own/local) — or keep training data fully
   hand-authored/templated?
4. **Conversation modality.** Typed questions with **spoken + text** answers to
   start (voice via R8), or full voice-in/voice-out later?
5. **Hard closed-world.** Is the **behavioral** guarantee (grounding + refusal)
   enough, or do you want **R9 (from-scratch)** scheduled to get the architectural
   guarantee?
6. **Cut cards?** Want the orchestrator to mint the Trello cards for R1→R4 (+R8)
   next, or keep planning first?

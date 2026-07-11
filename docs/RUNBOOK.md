# RUNBOOK — install, verify, and train the being on a Mac

_Everything here is **free and open source**. It targets a **48 GB M4 Pro
MacBook** (the machine the plan is written for), but the "verify what's shipped"
section runs on any dev box._

Companion planning docs: [`docs/READING_VOICEBOX.md`](READING_VOICEBOX.md) (the
reading/voice faculty), [`docs/SELF_NARRATION.md`](SELF_NARRATION.md) (the
self-report surface that ships first), [`docs/TRAINING.md`](TRAINING.md) (Play
Catch / the outcome predictor). Auth is [`docs/adr/0005`](adr/0005-api-authentication.md).

---

## 1. TL;DR

- **All tooling is free + open source.** No paid services are required to run,
  test, or train the being. (Claude is used *only at build time* to synthesize
  training data for the reading faculty — runtime inference is 100% local.)
- **The LLM runs HOST-NATIVE on the Mac — not in Docker.** Docker/Rancher on
  macOS runs inside a Linux VM and the **Apple-Silicon GPU (Metal) is not passed
  through**, so anything in a container is CPU-only. Therefore the model
  fine-tunes (MLX) and serves (Ollama on `:11434`) **on the host**, and the
  containerized engine reaches it over **`host.docker.internal:11434`** behind
  the existing `LanguageModelPort`. (See `READING_VOICEBOX.md` §5.)
- **What runs today vs. later.** The engine, the self-report surface
  (`POST /ask` / `POST /speak`), Postgres, and Kafka all run now. The reading
  faculty (ingest → fine-tune our own model → grounded/cited answers → voice)
  lands slice-by-slice as the **R-series** (`READING_VOICEBOX.md` §7); commands
  that don't exist yet are flagged below with the slice that adds them.
- **Rough model footprint** (Qwen2.5-3B-Instruct, the test-scale default):
  **~6–7 GB to serve**, **~10–16 GB for a LoRA fine-tune**. Comfortable on the
  48 GB M4 Pro (~30 GB usable when the Mac is otherwise idle).

---

## 2. One-time install

Only Rancher/Docker and the ML host-native tools need installing on the host;
**Postgres and Kafka run as containers** (no host install). The reading-faculty
Python libraries (MLX, sentence-transformers, Piper) install into the engine
virtualenv or globally as noted — they are only needed on the Mac when you reach
the R-series.

| Component | Purpose | macOS install | Source | License |
|---|---|---|---|---|
| **Rancher Desktop** (or Docker Desktop) | container runtime for the engine, Postgres, Kafka | `brew install --cask rancher` | https://rancherdesktop.io | Apache-2.0 |
| **MLX + MLX-LM** | Metal-native LoRA fine-tune on the Mac's GPU (R1) | `pip install mlx mlx-lm` | https://github.com/ml-explore/mlx · https://github.com/ml-explore/mlx-lm | MIT |
| **Ollama** | serve the fused fine-tuned model host-native on `:11434` (R2) | `brew install ollama` (or download from ollama.com) | https://github.com/ollama/ollama | MIT |
| **Qwen2.5-3B-Instruct** | the test-scale base model we LoRA-fine-tune | via MLX: `mlx_lm.lora --model Qwen/Qwen2.5-3B-Instruct …` · via Ollama: `ollama pull qwen2.5:3b-instruct` | https://huggingface.co/Qwen/Qwen2.5-3B-Instruct | Apache-2.0 |
| **sentence-transformers** | embeddings for the growing knowledge store (R3), CPU-in-container | `pip install sentence-transformers` | https://www.sbert.net | Apache-2.0 |
| **bge-small-en-v1.5** *or* **all-MiniLM-L6-v2** | the actual small embedding model (auto-downloaded on first use) | pulled by sentence-transformers on first `encode()` | https://huggingface.co/BAAI/bge-small-en-v1.5 · https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 | MIT · Apache-2.0 |
| **espeak-ng** | first TTS voice (offline, deterministic) for the voicebox (R8/S4) | `brew install espeak-ng` | https://github.com/espeak-ng/espeak-ng | GPL-3.0 |
| **Piper** | neural offline TTS, the voicebox upgrade after espeak-ng (R8) | `pip install piper-tts` | https://github.com/rhasspy/piper | MIT |
| **PyTorch** | the outcome/instinct predictors' feed-forward nets (`make train`) — **not** the LLM | `pip install -r engine/requirements-train.txt` (pins `torch==2.2.*`) | https://pytorch.org | BSD-3-Clause |
| **Postgres 16** | persistence (memories, interactions, knowledge store) | container only: `make db-up` (`postgres:16`) | https://www.postgresql.org | PostgreSQL License |
| **Kafka 3.8 (KRaft)** | event backbone (`being.*` topics) | container only: `make kafka-up` (`apache/kafka:3.8.0`) | https://kafka.apache.org | Apache-2.0 |

> **License note:** espeak-ng is **GPL-3.0** — it is invoked as a separate
> binary behind the `VoicePort` seam, and the voice degrades to a clear no-op
> when it is absent, so it is an optional upgrade rather than a linked
> dependency. Piper (MIT) is the preferred neural upgrade.

---

## 3. Verify what's shipped (works today)

This all works **without any ML host tooling** — no MLX, no Ollama, no torch
needed for the lean path.

### 3.1 Set up the environment

```bash
make setup     # creates engine/.venv, installs engine/requirements.txt,
               # and installs the git guardrail hooks (no commits on main)
```

### 3.2 Run the lean behavior suite

```bash
make test      # cd engine && PYTHONPATH=. .venv/bin/python -m pytest
```

The lean suite is green with no torch, no Postgres, and no Kafka: the
`integration` (live Postgres) and `kafka` (live broker) markers **skip
automatically** when their dependency is unreachable, and the torch-backed
training tests are skipped without torch installed.

### 3.3 Torch (predictor) tests

```bash
cd engine && .venv/bin/pip install -r requirements-train.txt   # installs torch (slow; minutes)
PYTHONPATH=. .venv/bin/python -m pytest                         # torch-backed tests now run
```

`requirements-train.txt` is the training-only set (`torch`, `numpy`) kept out of
the lean runtime image on purpose (ADR 0008). `make train` installs it on first
run and trains the outcome predictor → `models/outcome_predictor.pt`.

### 3.4 Postgres (integration marker)

```bash
JWT_SECRET=dev make db-up    # docker compose up -d --wait postgres
cd engine && PYTHONPATH=. DATABASE_URL=postgresql+psycopg://sim:sim@localhost:5432/being_sim \
    .venv/bin/python -m pytest -m integration
```

> **Compose gotcha (applies to every `docker compose` / `make db-up|kafka-up|up`):**
> the engine service declares `JWT_SECRET: ${JWT_SECRET:?…}`, and Compose
> validates that for the *whole* file even when you only start Postgres. So
> `JWT_SECRET` must be set (in your shell or `.env`) or the command errors out —
> hence the `JWT_SECRET=dev` prefix above. It is a throwaway dev value here.

### 3.5 Kafka (live `kafka` marker)

```bash
JWT_SECRET=dev make kafka-up    # starts the KRaft broker + creates being.* topics
cd engine && PYTHONPATH=. KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
    .venv/bin/python -m pytest -m kafka
```

Same `JWT_SECRET`-for-Compose gotcha as above. Without the broker the `kafka`
tests skip; with it live they exercise publish→consume, dedupe, and the DLQ.

### 3.6 Watch it live (demos)

```bash
make demo                                              # the being alone with one object (default hot lamp)
make demo OBJ=ball TICKS=600                           # a different object / longer run
cd engine && PYTHONPATH=. .venv/bin/python -m app.demo temperament   # habituation vs. sensitization (self-contained)
cd engine && PYTHONPATH=. .venv/bin/python -m app.demo react         # instinct flinch + suppression
cd engine && PYTHONPATH=. .venv/bin/python -m app.demo sensory       # perception→instinct→reaction chain
```

The `react` and `sensory` demos need a trained instinct model
(`models/instinct.pt`); each prints how to train it
(`python -m app.ml.train_instinct_model`) and runs inert (says so) without it.
`temperament` is self-contained.

### 3.7 Talk to it (`/ask`, `/speak` — always-on JWT, ADR 0005)

`POST /ask` and `POST /speak` are live today (self-narration S1/S4): the being
reports its own experience, grounded only in its logged memories, and can speak
it aloud. Serve the engine and the token-mint with the **same** `JWT_SECRET`:

```bash
# terminal 1 — serve the engine
JWT_SECRET=dev make run                    # uvicorn on http://localhost:8000

# terminal 2 — mint a token and ask
TOKEN=$(JWT_SECRET=dev make token)
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"query":"what have you done recently?"}' \
     http://localhost:8000/ask
# -> {"query":"…","report":"I pushed the round red thing and saw it bounce — that felt exciting"}

# hear it (writes a WAV if a TTS engine is on the host; otherwise 200 JSON with the text)
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"query":"what have you done recently?"}' \
     http://localhost:8000/speak -o report.wav
```

`GET /health` is public; `GET /state`, `POST /command`, `/ask`, `/speak` all
require the JWT; `/speak` degrades to a 200 text response (never mute) when no
TTS engine (espeak-ng) is installed. The narrator is the offline deterministic
template by default (`config/language.yaml` `narrator.kind: deterministic`) — no
model needed to talk.

---

## 4. Train & serve the reading faculty (host-native, once the R-slices land)

This is the reading/voice vision from `READING_VOICEBOX.md`: read a document,
LoRA-fine-tune **our own** model on the Mac's GPU, serve it offline via Ollama,
and answer grounded/cited questions about what it read. It runs **host-native**
(§5 there) — the engine container calls the model at `host.docker.internal:11434`.

**Some commands below do not exist on this branch yet** — they arrive with the
noted slice; use the finalized command from that slice's ADR/README when it
lands.

1. **Serve the base/fine-tuned model host-native.** In a host terminal:
   ```bash
   ollama serve          # OpenAI-style HTTP on :11434 (Metal GPU)
   ollama pull qwen2.5:3b-instruct   # the test-scale base (until a fine-tune replaces it)
   ```
2. **Fine-tune our own model on a document (MLX LoRA, R1).**
   `make train-language DOC=<path>` — **arrives with slice R1** (not yet in the
   Makefile on this branch). It runs `mlx_lm.lora` on the Mac's GPU; you watch
   the loss drop and sample generations in the document's style, and it saves the
   LoRA adapter. See R1's ADR ("Our own language model") for the finalized target.
3. **Fuse → GGUF → `ollama create` (R2).** Fuse R1's LoRA into the base, convert
   to GGUF, and `ollama create` the model so Ollama serves it. This fuse step
   runs **once per re-fine-tune** and is finalized with slice R2 (which also adds
   the `LocalLanguageModel` adapter and the `host.docker.internal:11434` wiring;
   see R2 / the ADR-0022 update).
4. **Point the being at the local model.** Set `config/language.yaml`
   `narrator.kind: local` (its `local:` block already authors
   `base_url: http://localhost:11434`, `model: qwen2.5:3b-instruct`, and
   `base_url_env: OLLAMA_BASE_URL` — inert until R1/R2 serve a model). At deploy
   time the engine's base URL is overridden by `OLLAMA_BASE_URL`
   (→ `http://host.docker.internal:11434` from inside the container). Fallback to
   the deterministic template stays on (`fallback_to_template: true`).
5. **Consolidation ("sleep") fine-tune (R5).** The being's simulated sleep tick
   triggers an **async** host-native LoRA pass that bakes accumulated docs into
   the weights (never blocks the sim). `make consolidate` is the dev override —
   **arrives with slice R5** (not yet in the Makefile); use R5's finalized
   command/ADR when it lands.

The QA/consolidation training pairs are synthesized by **Claude at build time
only**; runtime inference is 100% our local model. R1 trains on raw document text
and needs no synthesized data.

---

## 5. Sandbox vs. your Mac (what runs where)

The reading faculty uses the **same gating pattern** as the existing
`integration` / `kafka` test markers and the espeak-ng voice: the CPU/seam path
runs (or degrades to a deterministic fallback) anywhere, and the GPU/native path
lights up only on the Mac with the host tools installed.

| Capability | Runs anywhere (CPU-in-container / any dev box) | Needs the Mac + MLX/Ollama (host-native Metal) |
|---|---|---|
| Engine core (sim tick/state, needs/emotion/decision) | ✅ | — |
| Instinct / event chain (Kafka backbone, shadow reactions) | ✅ (broker in a container) | — |
| Self-narration (`/ask`, `/speak`) with the deterministic template narrator | ✅ | — |
| Document **ingest** (chunk / clean) | ✅ | — |
| **Embeddings + retrieval / QA** at the `RetrievalPort`/`LanguageModelPort` seam (fake or deterministic model) | ✅ | — |
| Persistence (Postgres), event bus (Kafka) | ✅ (containers) | — |
| Real **LoRA fine-tune** (R1) and **consolidation** fine-tune (R5) | — | ✅ (MLX on Metal) |
| **Serving our own model** (Ollama on `:11434`, real generation) | — | ✅ (called via `host.docker.internal:11434`) |
| **Neural TTS audio** (real espeak-ng / Piper output; otherwise a 200-with-text no-op) | ✅ (no-op degrade) | ✅ (audible voice) |

**Why the split:** Metal is not passed into the Docker/Rancher Linux VM, so GPU
work (fine-tune, model serving) must run on the host; everything else is CPU-fine
in a container and stays portable. That is exactly what keeps local-Mac → prod a
config/endpoint swap: the same ports front a host-native Ollama today and a GPU
container (vLLM/TGI on CUDA) later (`READING_VOICEBOX.md` §5).

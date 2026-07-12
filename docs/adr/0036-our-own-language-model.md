# 0036 — Our own language model: open base + LoRA, host-native on Mac / GPU container in prod

Status: Accepted
Date: 2026-07-11

## Context

The reading faculty's north star (`docs/READING_VOICEBOX.md`) is that the being
runs **our own LLM** — it reads a document, **learns from it**, and can converse
about it — all offline, on the Mac now, with a clean path to production later.
"Our own model" is settled as **fine-tune a small open base with LoRA** rather
than call a cloud model or train from scratch: local, open-source, our own
artifact, fluent enough to converse (READING_VOICEBOX §2). The chosen test-scale
base is **Qwen2.5-3B-Instruct** (Apache-2.0), comfortable on the 48 GB M4 Pro
(§6).

This slice (reading **R1**) is the first, foundational cut: **ingest a document
→ LoRA-fine-tune the base → watch it train & generate**, saving a LoRA adapter
artifact. It must decide *where the model runs*, because that shapes every later
slice.

The gotcha that forces the decision: Docker containers on macOS — including under
Rancher Desktop — run inside a Linux VM, and the **Apple-Silicon GPU (Metal) is
not passed through**. Anything in a container on the Mac is **CPU-only**
(READING_VOICEBOX §5). GPU work therefore cannot live in the engine container on
the Mac.

Existing seams this builds on: the `LanguageModelPort` (`complete(prompt)->str`,
ADR 0022) already abstracts *where the words come from*; the ml trainers
(`train_outcome_model`, `train_instinct_model`, ADR 0008/0026) already establish
the pattern for a training entrypoint that records a `ModelRun` (ADR 0017) and
imports its heavy ML dependency **lazily**, gated behind availability so the lean
runtime and the plain test suite never carry it.

## Decision

1. **Our own model = an open base fine-tuned with LoRA.** We fine-tune
   Qwen2.5-3B-Instruct (config-selected `base_model`) with LoRA; the trained
   **LoRA adapter** is "our model". The base and every LoRA/ingest/sampling
   hyperparameter live in `config/language.yaml`'s `finetune:` block as a typed
   `LoRAFinetunePolicy` (`ConfigService.finetune_policy()`) — no hard-coded
   tuning; retuning is a config change only.

2. **Fine-tuning is host-native on the Mac (MLX-LM); the engine stays
   containerized.** The GPU fine-tune runs on the host via **MLX-LM**
   (`mlx_lm.lora`), driven by `make train-language DOC=<path>`. It is **never**
   run inside the engine container (no Metal passthrough). This is the local
   half of the v8 "model-service sidecar" story.

3. **Ingest is a pure, deterministic front half.** A new `engine/app/language/`
   module owns `ingest` (read → clean → chunk into training-ready text) and
   writes the MLX-LM LoRA dataset (`train.jsonl` / `valid.jsonl`, `{"text": …}`
   lines). It touches no model, MLX, or GPU, so it is fully tested in the plain
   suite. R1 trains on raw document text and needs no synthesized data.

4. **The fine-tune runner is gated behind MLX availability and imports it
   lazily.** `mlx_lm` is an Apple-Silicon/host-only dependency (kept out of both
   `requirements.txt` and the torch `requirements-train.txt`, pinned in
   `requirements-finetune.txt` behind a `sys_platform == "darwin" and
   platform_machine == "arm64"` marker). The runner's command-building is pure;
   `run_finetune` **refuses loudly** with a clear `RuntimeError` naming exactly
   what the host needs when MLX is absent, mirroring the torch / Kafka / espeak
   availability gates. It never fakes a training run. The runner records a
   `ModelRun` (adapter path + metrics) through the model-run repository port in
   one unit of work (ADR 0017), like the other trainers.

5. **Local-Mac → prod is an endpoint swap behind the same port.** In production
   the model becomes a **GPU container** (PyTorch + PEFT/LoRA, served by
   vLLM/TGI on CUDA) behind the *same* `LanguageModelPort`. Only the serving
   adapter's endpoint changes; no service rewrites. Serving our fine-tuned model
   (fuse → GGUF → Ollama, behind the local adapter) is **reading R2**, not this
   slice — R1 produces the adapter artifact and the "watch it train & generate"
   observable.

## Consequences

- **Observable:** `make train-language DOC=<path>` ingests/chunks a document and
  (on a Mac with MLX) runs the LoRA fine-tune, streaming the training loss and
  sampling a generation in the corpus's style, saving the adapter. Off the Mac
  host (no MLX — e.g. the CI sandbox and the Linux container) it fails **loud and
  clear** with the host requirement. The "watch it train" loss-curve observable
  is only reachable on an Apple-Silicon Mac with MLX and the base-model weights;
  that end-to-end test is `pytest.importorskip`-gated and skips elsewhere.
- The ingest half (clean/chunk/dataset) and the config-driven command
  construction are genuinely built and fully tested here; the MLX training itself
  is scaffolded and executed only on the Mac host.
- One more heavy, platform-specific dependency set, isolated in
  `requirements-finetune.txt` behind a platform marker — the runtime image and
  the default test run stay lean and portable.
- The faculty stays strictly **on top** of the simulation (BRIEF rule #6, ADR
  0022): reading learns into an artifact; it does not drive needs/emotion/
  decision. Reading changes the being only through the validated cognition door
  in a later slice (reading R7).
- Supersedes nothing. Extends ADR 0022 (the language-model port), relates to ADR
  0008/0026 (trainer + `ModelRun` pattern) and ADR 0017 (unit of work). Reading
  R2 will update ADR 0022 for the local serving adapter.

# 0037 — Serve our fine-tuned model via Ollama, behind the existing LanguageModelPort

Status: Accepted
Date: 2026-07-11

## Context

Reading R1 (ADR 0036) produces a **LoRA adapter** that IS "our model", host-native
on the Mac's Metal GPU via MLX-LM. R1 explicitly deferred *serving* it: ADR 0036 §5
names "fuse → GGUF → Ollama, behind the local adapter" as **reading R2**, and ADR
0033 built the client-only `local` narrator adapter ("shared with reading R2"). This
slice (reading **R2**) is that step: make the fine-tuned model answerable at runtime
and reachable through the one `LanguageModelPort` — so `narrator.kind: local` answers
from **our** model on a Mac.

The same host constraint as R1 shapes it: on macOS (incl. Rancher Desktop) Docker
runs in a Linux VM with **no Metal passthrough** (READING_VOICEBOX §5), so anything
in a container is CPU-only. The model therefore serves **host-native**, and the
containerized engine calls it over `host.docker.internal:11434`.

Two seams already exist and must not be duplicated: the `LanguageModelPort`
(`complete(prompt)->str`, ADR 0022) and S2's `LocalLanguageModel` — an Ollama-style
HTTP client (`POST {base_url}/api/generate`) selected by `narrator.kind: local`,
with the base URL overridable by `OLLAMA_BASE_URL` (ADR 0033). What is missing is
(a) a **pipeline** that turns R1's adapter into a served Ollama model and (b) the
**config wiring** that points the `local` narrator at that model.

## Decision

1. **The serve pipeline is fuse → GGUF → `ollama create`, host-native on the Mac.**
   A new `engine/app/language/serve.py` fuses R1's LoRA into the base and exports
   GGUF in one MLX-LM step (`mlx_lm.fuse --export-gguf`), renders an Ollama
   **Modelfile**, and `ollama create`s a named model; Ollama's server then serves it
   on `:11434`. Driven by `make serve-language`. One fuse+convert step per
   re-fine-tune is the accepted trade for Ollama's model management (READING_VOICEBOX
   §6).

2. **Gated + lazy, refuses loudly, never fakes.** `mlx_lm` and the `ollama` CLI are
   never imported/required at module load. The command builders (`fuse_command` /
   `ollama_create_command` / `serve_command`) and the Modelfile render
   (`render_modelfile`) are **pure** and fully tested with neither installed.
   `run_serve_pipeline` guards on `mlx_available()` + `ollama_available()` + the
   presence of R1's adapter and raises a clear `RuntimeError` naming exactly what the
   host needs, mirroring the finetune/torch/kafka/espeak gates.

3. **Reuse S2's `LocalLanguageModel` unchanged — no second adapter.** R2 is a serve
   pipeline plus config wiring, not new inference code. The adapter's
   `/api/generate` client and its no-endpoint refusal (ADR 0033) are exactly what a
   served Ollama model needs. The `/api/chat` path and prod (vLLM/TGI) serving are
   deferred until something varies across the seam — no port change here.

4. **Config wires our served model to the narrator; one source of truth for the
   name.** A `serve:` block in `config/language.yaml` (typed `OllamaServePolicy`,
   `ConfigService.serve_policy()`) carries the Ollama `model_name`, the fused/GGUF
   artifact paths, the serve port, and the config-driven Modelfile `params`/`system`
   — nothing hard-coded. `base_model` and `adapter_path` are **reused from the
   `finetune:` block** (R1's artifacts, not re-declared). `narrator.local.model` is
   set to that same `model_name`, so `kind: local` calls our model, not the raw base;
   a test pins `local_model_policy().model == serve_policy().model_name`.

5. **Local-Mac → prod stays an endpoint swap (unchanged from ADR 0036 §5).** In
   production the served model becomes a GPU container behind the *same* port; only
   the adapter's endpoint (`OLLAMA_BASE_URL`) changes. Serving host-native on the Mac
   is the local half of the v8 model-service-sidecar story.

## Consequences

- **Observable:** on a Mac with MLX + Ollama and R1's adapter, `make serve-language`
  fuses → GGUF → `ollama create`s our model, Ollama serves it on `:11434`, and with
  `narrator.kind: local` the being answers from **our** fine-tuned model through the
  unchanged `LanguageModelPort`. Off-host it fails **loud and clear** with the host
  requirement.
- **Built + tested here (offline):** the `serve_policy` accessor, the pure command
  builders, the Modelfile render, the absent-toolchain guard, and the
  adapter→endpoint contract (against a mocked HTTP client, selecting our served model
  name) — plus the shipped-config wiring test. **Scaffolded, executed only on the Mac
  host:** the MLX fuse + GGUF export, `ollama create`, and a live `complete()` (a
  `pytest`-gated test that skips absent a live Ollama).
- No new runtime dependency in the container: Ollama and `mlx_lm` are host-only,
  pinned in `requirements-finetune.txt` behind the darwin/arm64 marker (as in R1).
- The faculty stays strictly **on top** of the sim (BRIEF rule #6, ADR 0022):
  serving makes an artifact answerable; it does not drive needs/emotion/decision.
- Supersedes nothing. Extends ADR 0022 (the port) and ADR 0033 (the client-only
  local adapter, now fed a real served model); realizes ADR 0036 §5's deferred serve
  step; relates to ADR 0035/0032 (the language surface) and the v8 sidecar story.

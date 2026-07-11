# 0041 — Sleep-triggered async knowledge consolidation: bake read knowledge into the weights

Status: Accepted
Date: 2026-07-11

## Context

The reading faculty's knowledge stance is **learn-and-grow**
(`docs/READING_VOICEBOX.md` §3, ADR 0038): a document you give the being is
usable **immediately** via the growing retrieval store (R3/R4), and — periodically
— the recurring knowledge is **consolidated into the model's weights** so it is
recalled *without* retrieval. The plan fixes the consolidation **cadence** as **on
a simulated 'sleep' tick**: the being's sleep cycle triggers an **async**
host-native LoRA pass (minutes-long — it must **never** block the sim), with `make
consolidate` as a dev override (READING_VOICEBOX §2, §7 row R5).

This is reading **R5**. Everything it needs already exists as seams: the being's
**`sleep` need** (`config/tick_rates.yaml`, the same one that reads as the `sleepy`
emotion at ≥80) is the sleep signal; R1's **gated MLX-LM LoRA runner**
(`finetune.run_finetune`, ADR 0036) trains; R2's **gated serve pipeline**
(`serve.run_serve_pipeline`, ADR 0037) re-serves; R3's **knowledge store** (ADR
0038) is the accumulated corpus to consolidate; and the **`LanguageModelPort`** (ADR
0022) is the seam Claude synthesizes training pairs behind at build time.

Two constraints shape the decision. First, the **language-on-top invariant** (BRIEF
rule #6, ADR 0022/0040): the faculty may read/learn/serve but must **never drive the
sim**, and reading changes the being only through the validated cognition door — so
consolidation must be a side pass that writes an *artifact*, not something on the
decision path. Second, the **local-Mac GPU reality** (ADR 0036 §5): the LoRA
fine-tune + fuse→GGUF→Ollama serve are host-native Apple-Silicon work that cannot
run in the Linux/Docker container (no Metal passthrough) and cannot run in CI.

## Decision

1. **The sim tick TRIGGERS consolidation; it never RUNS it.** A new
   `ConsolidationScheduler` (`engine/app/language/consolidation.py`) exposes
   `maybe_consolidate(sleep_before, sleep_after)`. `Simulation.tick()` calls it after
   needs drift, passing the `sleep` need before/after. On a **rising-edge crossing**
   of `sleep_threshold` (was below, now at/above — the being just fell asleep) it
   **enqueues** the consolidation job on an injected executor and **returns at once**.
   One pass per sleep, not one per tick while asleep. The scheduler holds only the
   trigger — no model, store, or MLX — so it is pure and fully unit-tested.

2. **The job runs async, out-of-band, and never blocks the tick.** The executor is a
   seam (`JobExecutor.submit`). The host runtime wires a `BackgroundExecutor` (a
   single-worker daemon thread pool — passes are serialized, one sleep at a time); the
   suite wires a recording fake, so the *enqueue* is observable without a real
   training run ever firing on the tick thread. A `Simulation` constructed **without**
   a scheduler (the default), or with consolidation **disabled** in config, is
   **byte-identical** — no new work on the shipped tick.

3. **Training pairs are synthesized FROM the knowledge store, at build/host time
   only.** `synthesize_consolidation_pairs(chunks, model, policy)` turns the
   accumulated store chunks into Q/A pairs via the `LanguageModelPort` — **Claude at
   build/host time**, a Fake in tests. This synthesis is a **data step**, not runtime
   inference: **runtime inference stays 100% our local served model**. The pair
   synthesis is pure/offline (no MLX/GPU) and fully suite-tested; `pairs_to_document`
   wraps them so R1's `write_dataset` + `run_finetune` train over them unchanged.

4. **The GPU work reuses R1 + R2 and is gated behind MLX — it refuses loudly
   off-host.** `run_consolidation` guards on `finetune.mlx_available()` and raises a
   clear `RuntimeError` naming exactly what the host needs (Apple-Silicon Mac +
   `mlx_lm` + Ollama) when MLX is absent — it **never fakes a training run** — then
   reuses `finetune.run_finetune` (records a `ModelRun`, ADR 0017) and
   `serve.run_serve_pipeline` (re-fuse → GGUF → `ollama create`). The end-to-end
   fine-tune + serve is `pytest.importorskip`-gated and skips everywhere but a Mac.

5. **Config-driven, disabled by default.** A `consolidation:` block in
   `config/language.yaml` → a typed `ConsolidationPolicy`
   (`ConfigService.consolidation_policy()`): `enabled` (default **false**),
   `sleep_threshold` (default 80, aligned with the `sleepy` emotion), `pair_count`,
   the `synthesis_prompt`/`pair_template` the build-time model renders pairs with, and
   the dataset `source`. `make consolidate` forces a pass now (the dev override).

## Consequences

- **Observable:** on a sleep tick (with consolidation enabled and a scheduler wired),
  an async consolidation is enqueued without blocking `tick()`; on the Mac,
  `make consolidate` synthesizes pairs from the knowledge store, LoRA-fine-tunes, and
  re-serves, after which the being recalls consolidated facts **without** retrieval.
  Off the Mac host it refuses **loud and clear** with the host requirement; the
  "recall without retrieval" observable is Mac-only.
- The sleep **trigger**, the **async enqueue** (non-blocking), and the **pair
  synthesis** are genuinely built and fully tested offline (Fake model, recording
  executor). The MLX fine-tune + Ollama re-serve are scaffolded and executed only on
  the Mac host — never faked.
- The faculty stays strictly **on top** (ADR 0022/0040): consolidation reads the
  store and writes a re-fine-tuned *artifact*; it never drives needs/emotion/decision.
  The `sleep` need is read only as a trigger edge — the sim keeps full authority over
  it. No new need is introduced (the existing sleep cycle is reused).
- Supersedes nothing. Extends ADR 0036 (reuses R1's gated LoRA runner + `ModelRun`)
  and ADR 0037 (reuses R2's serve pipeline); consumes ADR 0038 (the knowledge store)
  and ADR 0022 (the `LanguageModelPort` for build-time synthesis); upholds ADR
  0040/0022 (language-on-top) and ADR 0017 (unit of work). Relates to roadmap **v6**
  (memory consolidation — this is its language analogue).

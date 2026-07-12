"""The being's language faculty (reading track, ADR 0036).

It READS documents you give it and learns from them by fine-tuning OUR OWN
open-source base model. This slice (reading R1) is the front half:

  - `ingest` — read a document, clean it, and chunk it into training-ready text
    (pure, deterministic; no model, no MLX, no GPU).
  - `finetune` — a host-native MLX-LM LoRA fine-tune runner over those chunks,
    with `mlx_lm` imported lazily and the training itself GATED behind MLX
    availability (a clear, loud refusal off the Mac host).

  - `consolidation` (reading R5) — when the being SLEEPS, a `ConsolidationScheduler`
    ENQUEUES an async host-native LoRA pass (never blocks the tick) over Q/A pairs
    synthesized FROM the knowledge store at build time, reusing the R1 fine-tune and
    R2 serve — so consolidated facts are later recalled without retrieval.

The faculty sits ON TOP of the simulation and never controls it (BRIEF rule #6,
ADR 0022); it reads and learns, it does not drive needs / emotion / decision.
Consolidation writes an artifact (the re-fine-tuned model); it never drives the sim.
"""

"""consolidation — the being's KNOWLEDGE CONSOLIDATION on its 'sleep' cycle
(reading R5, ADR 0041).

When the being SLEEPS — its `sleep` need crosses the configured threshold (the same
>=80 that reads as the `sleepy` emotion) — it consolidates what it has read into its
OWN WEIGHTS: an ASYNC, host-native LoRA pass that NEVER blocks the tick. The sim tick
only TRIGGERS the pass (`ConsolidationScheduler` enqueues it on a background executor
and returns); the pass itself runs out-of-band and reuses R1's gated fine-tune runner
+ R2's serve pipeline, so consolidated facts are later RECALLED WITHOUT RETRIEVAL.

The consolidation TRAINING DATA is synthesized at BUILD/HOST time only:
`synthesize_consolidation_pairs` turns the accumulated knowledge-store chunks into
question/answer pairs via a `LanguageModelPort` (a Fake in the suite; Claude on the
Mac host). RUNTIME inference stays 100% local (the being's own served model) — this
is a maintenance/training operation, not an inference one, so the language-on-top
invariant holds: consolidation writes an artifact, it never drives the sim.

Like R1/R2 the GPU work is host-only: `run_consolidation` GUARDS on `mlx_available()`
and refuses LOUDLY off the Mac host; it never fakes a training run.

Public surface:
  - `ConsolidationPair` / `synthesize_consolidation_pairs(...)` / `pairs_to_document(...)`
    — build the consolidation dataset FROM the knowledge store (Fake-tested, offline).
  - `ConsolidationScheduler` — the sleep -> async-consolidation trigger: `maybe_consolidate`
    enqueues the job on a rising-edge sleep crossing, without blocking.
  - `BackgroundExecutor` — a real, non-blocking executor (a daemon thread pool) the host
    runtime wires the scheduler with; tests use a recording fake instead.
  - `run_consolidation(...)` — the job body: synthesize pairs -> R1 gated LoRA fine-tune
    (records a ModelRun) -> R2 gated re-serve. Gated behind MLX.
  - `main()` — the `make consolidate` dev-override entry (forces a pass now).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Protocol, Sequence

from app.language import finetune, serve
from app.language.finetune import mlx_available
from app.language.ingest import IngestedDocument

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_ROOT = _REPO_ROOT / "config"
_DEFAULT_WORKSPACE = _REPO_ROOT / "models" / "language" / "consolidation"

# The single, reusable explanation of what a host must have to CONSOLIDATE — used by
# the runner's guard AND the CLI, so the requirement is stated in exactly one place.
_CONSOLIDATION_REQUIREMENT = (
    "knowledge consolidation runs HOST-NATIVE on an Apple-Silicon Mac: it reuses R1's "
    "MLX-LM LoRA fine-tune and R2's Ollama serve, so it needs `mlx_lm` (pip install "
    "mlx-lm; macOS/arm64 only) and — to re-serve — the `ollama` CLI, both on the HOST. "
    "Consolidation is triggered automatically on the being's sleep cycle; `make "
    "consolidate` forces one now. Run it on the Mac HOST itself, not inside the Linux/"
    "Docker container where the Metal GPU is not passed through (see docs/adr/0041 / "
    "READING_VOICEBOX.md §2/§5)."
)


def _chunk_text(chunk) -> str:
    """The passage text of a knowledge-store chunk — a domain `KnowledgeChunk`, a
    retrieval `Chunk`/`RetrievedPassage` (all carry `.text`), or a bare string."""
    text = getattr(chunk, "text", None)
    return text if isinstance(text, str) else str(chunk)


@dataclass(frozen=True)
class ConsolidationPair:
    """One consolidation training example synthesized FROM a knowledge-store chunk:
    the `passage` it was distilled from and the `text` the build-time model produced
    (a Q/A the fine-tune learns to recall). `as_text()` is the training line the R1
    fine-tune pipeline consumes."""

    passage: str
    text: str

    def as_text(self) -> str:
        return self.text


def synthesize_consolidation_pairs(chunks, model, policy) -> List[ConsolidationPair]:
    """Turn accumulated knowledge-store `chunks` into consolidation training pairs
    via `model` (a `LanguageModelPort` — Claude at build/host time; a Fake in tests).

    For each of the first `policy.pair_count` chunks the passage is embedded into
    `policy.synthesis_prompt` and the model's completion is shaped by
    `policy.pair_template` into the pair's training text. Deterministic given a
    deterministic model; touches no MLX/GPU/network of its own, so it is fully
    suite-tested. Runtime inference is unaffected — this is a build-time data step."""
    limit = max(0, int(policy.pair_count))
    pairs: List[ConsolidationPair] = []
    for chunk in list(chunks)[:limit]:
        passage = _chunk_text(chunk)
        prompt = policy.synthesis_prompt.format(passage=passage)
        completion = model.complete(prompt).strip()
        pair_text = policy.pair_template.format(passage=passage, completion=completion)
        pairs.append(ConsolidationPair(passage=passage, text=pair_text))
    return pairs


def pairs_to_document(pairs: Sequence[ConsolidationPair], *, source: str) -> IngestedDocument:
    """Wrap synthesized `pairs` as an `IngestedDocument` so R1's fine-tune pipeline
    (`write_dataset` + `run_finetune`) trains over the consolidation set UNCHANGED —
    one training line per pair. Refuses an empty set (nothing read to consolidate)."""
    chunks = tuple(pair.as_text() for pair in pairs)
    if not chunks:
        raise ValueError(
            "no consolidation pairs to train on — the being's knowledge store is empty; "
            "read some documents first"
        )
    return IngestedDocument(source=source, chunks=chunks)


class JobExecutor(Protocol):
    """Runs a consolidation job out-of-band. `submit` MUST return promptly (never
    block the caller / tick thread) — a thread pool in the host runtime, a recording
    fake in tests."""

    def submit(self, job: Callable[[], object]) -> object:
        ...


class BackgroundExecutor:
    """A real, non-blocking `JobExecutor` — runs each submitted consolidation job on a
    background DAEMON thread, so the minutes-long LoRA pass never blocks the tick
    thread. A single worker serializes passes (one sleep at a time). This is what a
    host runtime wires the scheduler with; the suite uses a recording fake instead."""

    def __init__(self) -> None:
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415 — host runtime only

        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="consolidation")

    def submit(self, job: Callable[[], object]) -> object:
        return self._pool.submit(job)


class ConsolidationScheduler:
    """The sleep -> async-consolidation trigger (reading R5, ADR 0041).

    When the being's `sleep` need crosses the configured threshold on a RISING EDGE
    (was below, now at/above — it just fell asleep), this ENQUEUES the consolidation
    job on an executor and RETURNS immediately, so `Simulation.tick()` is never blocked
    by the minutes-long LoRA pass. `policy.enabled` gates the whole thing: disabled
    (the default), it never enqueues, so the shipped tick is byte-identical.

    Seams: `executor.submit(job)` runs the job out-of-band (a `BackgroundExecutor`
    daemon-thread pool in the host runtime; a recording fake in tests, so the enqueue
    is observable without a real training run); `job` is the zero-arg callable that
    performs ONE consolidation (it reads the CURRENT knowledge store when it runs).
    The scheduler owns only the TRIGGER; it holds no model, store, or MLX — the job
    does, so the scheduler stays pure and fully testable."""

    def __init__(self, *, policy, executor: JobExecutor, job: Callable[[], object]) -> None:
        self._policy = policy
        self._executor = executor
        self._job = job

    def maybe_consolidate(self, *, sleep_before: float, sleep_after: float) -> bool:
        """Enqueue a consolidation pass IFF consolidation is enabled and the `sleep`
        need just crossed the threshold (was below, now at/above — the being fell
        asleep). Returns whether a job was enqueued. NEVER blocks: it only submits, so
        the sleep tick returns at once. A tick where the being is already asleep, or
        has not yet reached the threshold, enqueues nothing (no repeat passes while
        asleep)."""
        if not self._policy.enabled:
            return False
        threshold = self._policy.sleep_threshold
        crossed_rising_edge = sleep_before < threshold <= sleep_after
        if not crossed_rising_edge:
            return False
        self._executor.submit(self._job)
        return True


def run_consolidation(
    *,
    chunks,
    model,
    policy,
    finetune_policy,
    serve_policy=None,
    workspace: str,
    model_run_repo=None,
    unit_of_work=None,
    timestamp: datetime,
    do_serve: bool = True,
):
    """Perform ONE knowledge-consolidation pass — the job the scheduler enqueues and
    `make consolidate` forces. Refuses LOUDLY off the Mac host (no MLX), so it never
    fakes training or wastes a build-time synthesis call. On a ready host it:

      1. synthesizes consolidation Q/A pairs FROM `chunks` via `model` (Claude at
         build time) — the accumulated read knowledge, distilled;
      2. reuses R1's GATED LoRA runner (`finetune.run_finetune`) over those pairs,
         recording a `ModelRun` (ADR 0017) exactly like a document fine-tune; and
      3. reuses R2's GATED serve pipeline (`serve.run_serve_pipeline`: re-fuse ->
         GGUF -> `ollama create`) so the consolidated model is re-served and the
         facts are later recalled WITHOUT retrieval.

    Returns the fine-tune metrics, augmented with the consolidation pair count (and
    the re-served model name when `do_serve`)."""
    if not mlx_available():
        raise RuntimeError("cannot consolidate: " + _CONSOLIDATION_REQUIREMENT)

    pairs = synthesize_consolidation_pairs(chunks, model, policy)
    document = pairs_to_document(pairs, source=policy.source)

    metrics = dict(
        finetune.run_finetune(
            document=document,
            policy=finetune_policy,
            workspace=workspace,
            model_run_repo=model_run_repo,
            unit_of_work=unit_of_work,
            timestamp=timestamp,
        )
    )
    metrics["consolidation_pairs"] = len(pairs)

    if do_serve and serve_policy is not None:
        serve.run_serve_pipeline(policy=serve_policy, workspace=workspace)
        metrics["served_model"] = serve_policy.model_name

    return metrics


def _open_repos():
    """The Postgres-backed knowledge-chunk + model-run repositories and their shared
    session when `DATABASE_URL` is configured, else `(None, None, None)` so a
    consolidation with no database fails clearly (there is nothing accumulated to
    consolidate). Returns the open session too so `main` can close it (ADR 0005:
    env-only connection)."""
    if not os.environ.get("DATABASE_URL"):
        return None, None, None

    from app.db.session import create_db_engine, session_factory
    from app.repositories import (
        PostgresKnowledgeChunkRepository,
        PostgresModelRunRepository,
    )

    session = session_factory(create_db_engine())()
    return (
        PostgresKnowledgeChunkRepository(session),
        PostgresModelRunRepository(session),
        session,
    )


def main(argv: Optional[List[str]] = None) -> None:
    """Force ONE knowledge-consolidation pass NOW — the `make consolidate` dev override
    for the automatic sleep trigger. Reads the being's accumulated knowledge-store
    chunks, synthesizes consolidation pairs (build-time model), LoRA-fine-tunes over
    them, and re-serves. Config/env-driven; refuses LOUDLY off the Mac host rather than
    pretending to consolidate."""
    from app.config_service import ConfigService

    config_root = os.environ.get("CONFIG_ROOT", str(_DEFAULT_CONFIG_ROOT))
    workspace = os.environ.get("LANGUAGE_WORKSPACE", str(_DEFAULT_WORKSPACE))
    config = ConfigService.from_files(config_root)
    policy = config.consolidation_policy()

    print(
        "consolidating read knowledge into our model's weights "
        f"(sleep-triggered at need >= {policy.sleep_threshold}; forced now): "
        f"up to {policy.pair_count} pairs synthesized from the knowledge store -> "
        "host-native MLX-LM LoRA -> re-serve"
    )

    if not mlx_available():
        raise SystemExit("cannot consolidate: " + _CONSOLIDATION_REQUIREMENT)

    knowledge_repo, model_run_repo, session = _open_repos()
    if knowledge_repo is None:
        raise SystemExit(
            "cannot consolidate: no DATABASE_URL set, so there is no accumulated "
            "knowledge store to consolidate. Ingest documents first (reading R3)."
        )

    # Build-time pair synthesis uses our Claude adapter (never the being's runtime
    # voice); runtime inference stays 100% local.
    from app.adapters.claude_language_model import ClaudeLanguageModel

    from app.db.unit_of_work import SessionUnitOfWork

    try:
        chunks = knowledge_repo.all()
        metrics = run_consolidation(
            chunks=chunks,
            model=ClaudeLanguageModel(),
            policy=policy,
            finetune_policy=config.finetune_policy(),
            serve_policy=config.serve_policy(),
            workspace=workspace,
            model_run_repo=model_run_repo,
            unit_of_work=SessionUnitOfWork(session),
            timestamp=datetime.now(timezone.utc),
        )
    finally:
        if session is not None:
            session.close()

    print(
        f"consolidated {metrics.get('consolidation_pairs', 0)} pair(s) from the "
        f"knowledge store into {metrics.get('base_model')!r}\n"
        f"  -> adapter: {config.finetune_policy().adapter_path}\n"
        f"  -> re-served as {metrics.get('served_model', '(serve skipped)')!r} — the being now "
        "recalls these facts WITHOUT retrieval"
    )


if __name__ == "__main__":
    main()

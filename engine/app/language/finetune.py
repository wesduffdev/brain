"""finetune — a HOST-NATIVE MLX-LM LoRA fine-tune of our own base model over an
ingested document (reading R1, ADR 0036).

This is how the being learns from what it reads: it LoRA-fine-tunes an
open-source base (Qwen2.5-3B-Instruct by default) on the document's chunks,
saving a LoRA ADAPTER that IS "our model", and samples a generation so you can
watch it write in the corpus's style. The training is GPU work: on macOS the
Apple-Silicon Metal GPU is reachable only HOST-NATIVE (not inside the Linux/
Docker VM, ADR 0036 / READING_VOICEBOX §5), so it runs via MLX-LM on the Mac
host and the engine container calls the served model behind `LanguageModelPort`
later (reading R2).

`mlx_lm` is a host-only, Apple-Silicon dependency, so it is NEVER imported at
module load. The command-building (`lora_command` / `generate_command` /
`lora_config_dict`) is pure and testable with no MLX; `run_finetune` GUARDS on
`mlx_available()` and refuses LOUDLY — naming exactly what the host needs — when
MLX is absent, mirroring the torch / kafka / espeak availability gates elsewhere.
It never fakes a training run.

Public surface:
  - `mlx_available()` — whether this host can run the fine-tune.
  - `lora_command(...)` / `generate_command(...)` / `lora_config_dict(...)` — the
    exact, config-driven MLX-LM invocations (pure).
  - `run_finetune(...)` — ingest-doc + policy -> written dataset -> MLX-LM LoRA
    train -> sampled generation -> a recorded `ModelRun`. Gated behind MLX.
  - `main()` — the `make train-language DOC=<path>` entry.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.domain.model_run import ModelRun
from app.language.ingest import IngestedDocument, ingest_document, write_dataset

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_ROOT = _REPO_ROOT / "config"
_DEFAULT_WORKSPACE = _REPO_ROOT / "models" / "language" / "workspace"

# The single, reusable explanation of what a host must have to fine-tune — used
# by the runner's guard AND the CLI, so the requirement is stated in one place.
_MLX_REQUIREMENT = (
    "the LoRA fine-tune runs HOST-NATIVE on an Apple-Silicon Mac's Metal GPU via "
    "MLX-LM; it needs `mlx_lm` installed on the HOST (pip install mlx-lm), which is "
    "available only on macOS/arm64. Run `make train-language DOC=<path>` on the Mac "
    "host itself — not inside the Linux/Docker container, where the Metal GPU is not "
    "passed through (see docs/adr/0036 / READING_VOICEBOX.md §5)."
)


def mlx_available() -> bool:
    """True when `mlx_lm` is importable — i.e. this host can run the fine-tune.
    Checked WITHOUT importing mlx_lm (find_spec only), so the guard itself never
    pulls in the host-only dependency."""
    return importlib.util.find_spec("mlx_lm") is not None


def lora_config_dict(policy) -> Dict[str, object]:
    """The LoRA-specific hyperparameters as the small config document MLX-LM's
    LoRA trainer reads (`lora_parameters`), driven entirely from `policy` so rank
    / scale / dropout are config, never hard-coded."""
    return {
        "lora_parameters": {
            "rank": int(policy.rank),
            "scale": float(policy.scale),
            "dropout": float(policy.dropout),
        }
    }


def lora_command(policy, *, data_dir, adapter_path, config_path) -> List[str]:
    """The exact `python -m mlx_lm.lora --train ...` invocation for `policy` — the
    host-native LoRA fine-tune of the base model over the written dataset. Pure:
    it builds argv, it does not run anything."""
    return [
        sys.executable, "-m", "mlx_lm.lora",
        "--model", str(policy.base_model),
        "--train",
        "--data", str(data_dir),
        "--adapter-path", str(adapter_path),
        "--config", str(config_path),
        "--iters", str(policy.iters),
        "--batch-size", str(policy.batch_size),
        "--num-layers", str(policy.num_layers),
        "--learning-rate", str(policy.learning_rate),
        "--max-seq-length", str(policy.max_seq_length),
        "--seed", str(policy.seed),
    ]


def generate_command(policy, *, adapter_path) -> List[str]:
    """The `python -m mlx_lm.generate ...` invocation that samples the fine-tuned
    adapter, so you can read a generation in the corpus's style. Pure."""
    return [
        sys.executable, "-m", "mlx_lm.generate",
        "--model", str(policy.base_model),
        "--adapter-path", str(adapter_path),
        "--prompt", str(policy.sample_prompt),
        "--max-tokens", str(policy.sample_max_tokens),
    ]


def run_finetune(
    *,
    document: IngestedDocument,
    policy,
    workspace: str,
    model_run_repo=None,
    unit_of_work=None,
    timestamp: datetime,
) -> Dict[str, object]:
    """Fine-tune our base model on `document` and record the run — the
    `make train-language` core. Refuses LOUDLY (a clear RuntimeError naming the
    host requirement) when MLX is unavailable, so it never silently no-ops or
    fakes training. When MLX is present: writes the LoRA dataset + config into
    `workspace`, runs the MLX-LM LoRA trainer (its loss streams to the console —
    "watch it train"), samples a generation from the trained adapter, and — when a
    `model_run_repo` is present — records one `ModelRun` (adapter path, metrics,
    the injected `timestamp`) in one unit of work (ADR 0017). Returns the metrics."""
    if not mlx_available():
        raise RuntimeError("cannot fine-tune: " + _MLX_REQUIREMENT)

    from app.db.unit_of_work import NullUnitOfWork

    unit_of_work = unit_of_work or NullUnitOfWork()
    workspace_path = Path(workspace)
    workspace_path.mkdir(parents=True, exist_ok=True)
    data_dir = workspace_path / "data"
    config_path = workspace_path / "lora_config.yaml"
    adapter_path = Path(policy.adapter_path)
    adapter_path.mkdir(parents=True, exist_ok=True)

    dataset = write_dataset(document, str(data_dir), valid_fraction=policy.valid_fraction)
    # A JSON document is valid YAML, so MLX-LM's yaml loader reads this directly.
    config_path.write_text(json.dumps(lora_config_dict(policy), indent=2))

    train_cmd = lora_command(
        policy, data_dir=data_dir, adapter_path=adapter_path, config_path=config_path
    )
    # Inherit stdout/stderr so the training loss streams live to the console.
    subprocess.run(train_cmd, check=True)

    gen_cmd = generate_command(policy, adapter_path=adapter_path)
    sampled = subprocess.run(gen_cmd, check=True, capture_output=True, text=True)
    sample_generation = (sampled.stdout or "").strip()

    metrics: Dict[str, object] = {
        "source": document.source,
        "base_model": policy.base_model,
        "num_chunks": len(document.chunks),
        "train_count": dataset["train_count"],
        "valid_count": dataset["valid_count"],
        "iters": policy.iters,
        "rank": policy.rank,
        "learning_rate": policy.learning_rate,
        "sample_generation": sample_generation,
    }

    if model_run_repo is not None:
        with unit_of_work.begin():
            model_run_repo.add(
                ModelRun(
                    artifact_path=str(adapter_path),
                    finished_at=timestamp,
                    metrics=dict(metrics),
                )
            )

    return metrics


def _open_model_run_repo():
    """The Postgres-backed model-run repository when `DATABASE_URL` is configured,
    else `(None, None)` so the fine-tune runs standalone with no database. Returns
    the open session too so `main` can close it (ADR 0005: env-only connection)."""
    if not os.environ.get("DATABASE_URL"):
        return None, None

    from app.db.session import create_db_engine, session_factory
    from app.repositories import PostgresModelRunRepository

    session = session_factory(create_db_engine())()
    return PostgresModelRunRepository(session), session


def main(argv: Optional[List[str]] = None) -> None:
    """Ingest DOC, fine-tune our base model on it (host-native MLX-LM LoRA), and
    record a `model_runs` row when a database is configured — the
    `make train-language DOC=<path>` entry. The document path is the first CLI arg
    (or `LANGUAGE_DOC`); paths + tuning are config/env-driven. When MLX is absent
    it exits LOUDLY with exactly what the host needs, rather than pretending."""
    from app.config_service import ConfigService

    argv = sys.argv[1:] if argv is None else argv
    doc_path = (argv[0] if argv else os.environ.get("LANGUAGE_DOC", "")).strip()
    if not doc_path:
        raise SystemExit(
            "usage: make train-language DOC=<path>  "
            "(or: python -m app.language.finetune <document-path>)"
        )

    config_root = os.environ.get("CONFIG_ROOT", str(_DEFAULT_CONFIG_ROOT))
    workspace = os.environ.get("LANGUAGE_WORKSPACE", str(_DEFAULT_WORKSPACE))
    config = ConfigService.from_files(config_root)
    policy = config.finetune_policy()

    document = ingest_document(
        doc_path,
        max_chars=policy.max_chars,
        overlap=policy.overlap,
        min_chunk_chars=policy.min_chunk_chars,
    )
    print(
        f"ingested {doc_path!r}: {len(document.chunks)} chunk(s) "
        f"-> fine-tuning {policy.base_model} (LoRA, host-native MLX)"
    )

    if not mlx_available():
        raise SystemExit("cannot fine-tune: " + _MLX_REQUIREMENT)

    model_run_repo, session = _open_model_run_repo()
    unit_of_work = None
    if session is not None:
        from app.db.unit_of_work import SessionUnitOfWork

        unit_of_work = SessionUnitOfWork(session)
    try:
        metrics = run_finetune(
            document=document,
            policy=policy,
            workspace=workspace,
            model_run_repo=model_run_repo,
            unit_of_work=unit_of_work,
            timestamp=datetime.now(timezone.utc),
        )
    finally:
        if session is not None:
            session.close()

    print(
        f"fine-tuned {metrics['base_model']} on {metrics['source']!r} "
        f"(chunks={metrics['num_chunks']}, iters={metrics['iters']})\n"
        f"  -> adapter: {policy.adapter_path}\n"
        f"  sample generation:\n{metrics['sample_generation']}"
    )


if __name__ == "__main__":
    main()

"""serve — the HOST-NATIVE pipeline that SERVES our fine-tuned model via Ollama and
reaches it behind the existing `LanguageModelPort` (reading R2, ADR 0037).

R1 (`finetune.py`) produces a LoRA ADAPTER that IS "our model". This module makes
that model answerable at runtime: it **fuses** the adapter into the base, **exports
GGUF**, and `ollama create`s a named model that **Ollama serves** on `:11434`
(READING_VOICEBOX §5/§6). The engine — containerized — then calls it through the
UNCHANGED S2 `LocalLanguageModel` adapter (`{base_url}/api/generate`), reaching the
Mac host at `host.docker.internal:11434`. No second adapter is built: R2 is a serve
pipeline plus config wiring, so the served model name (`serve.model_name`) IS the
`narrator.local.model` the adapter calls.

Like the R1 fine-tune, serving is Apple-Silicon Metal work and a host-only
toolchain, so:
  - `mlx_lm` (fuse + GGUF export) and the `ollama` CLI are NEVER imported/required at
    module load; the command-building (`fuse_command` / `ollama_create_command` /
    `serve_command`) and the Modelfile render (`render_modelfile`) are PURE and
    testable with neither installed.
  - `run_serve_pipeline` GUARDS on `mlx_available()` + `ollama_available()` + the
    presence of R1's adapter, and refuses LOUDLY — naming exactly what the host
    needs (Apple-Silicon Mac + `mlx_lm` + Ollama + the R1 adapter) — when any is
    missing, mirroring the finetune / torch / kafka / espeak availability gates. It
    never fakes serving.

Public surface:
  - `ollama_available()` / `mlx_available()` — whether this host can serve.
  - `fuse_command(...)` / `ollama_create_command(...)` / `serve_command(...)` /
    `render_modelfile(...)` — the exact, config-driven invocations + Modelfile (pure).
  - `run_serve_pipeline(...)` — fuse -> GGUF -> Modelfile -> `ollama create`. Gated.
  - `main()` — the `make serve-language` entry.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Reuse R1's MLX availability check — one source of truth for "can this host fuse".
from app.language.finetune import mlx_available

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_ROOT = _REPO_ROOT / "config"
_DEFAULT_WORKSPACE = _REPO_ROOT / "models" / "language" / "workspace"

# The single, reusable explanation of what a host must have to SERVE — used by the
# runner's guard AND the CLI, so the requirement is stated in exactly one place.
_SERVE_REQUIREMENT = (
    "serving our fine-tuned model runs HOST-NATIVE on an Apple-Silicon Mac: it needs "
    "(1) `mlx_lm` to fuse R1's LoRA adapter into the base and export GGUF "
    "(pip install mlx-lm; macOS/arm64 only), (2) the `ollama` CLI installed with its "
    "server running to create + serve the model on :11434 (brew install ollama; then "
    "`ollama serve`), and (3) R1's trained LoRA adapter present at the configured "
    "adapter_path — run `make train-language DOC=<path>` first. Run `make "
    "serve-language` on the Mac HOST itself, not inside the Linux/Docker container "
    "where the Metal GPU is not passed through (see docs/adr/0037 / "
    "READING_VOICEBOX.md §5)."
)


def ollama_available() -> bool:
    """True when the `ollama` CLI is on PATH — i.e. this host can create + serve the
    model. Checked without invoking it, so the guard never shells out."""
    return shutil.which("ollama") is not None


def fuse_command(policy) -> List[str]:
    """The exact `python -m mlx_lm.fuse ...` invocation for `policy` — fuse R1's LoRA
    adapter into the base and export a GGUF in one step, host-native on Metal. Pure:
    it builds argv, it does not run anything."""
    return [
        sys.executable, "-m", "mlx_lm.fuse",
        "--model", str(policy.base_model),
        "--adapter-path", str(policy.adapter_path),
        "--save-path", str(policy.fused_path),
        "--export-gguf",
        "--gguf-path", str(policy.gguf_file),
    ]


def render_modelfile(policy) -> str:
    """The Ollama Modelfile for `policy` — `FROM` the exported GGUF, one `PARAMETER`
    per configured generation knob (config-driven; nothing hard-coded), and an
    optional `SYSTEM` preamble. Pure text; `run_serve_pipeline` writes it to disk for
    `ollama create -f`."""
    lines = [f"FROM {policy.gguf_path}"]
    for key, value in (policy.params or {}).items():
        lines.append(f"PARAMETER {key} {value}")
    if policy.system:
        lines.append(f'SYSTEM """{policy.system}"""')
    return "\n".join(lines) + "\n"


def ollama_create_command(policy, *, modelfile_path) -> List[str]:
    """The `ollama create <model_name> -f <Modelfile>` invocation that registers our
    fused + GGUF model under `serve.model_name` — the name the `local` narrator calls.
    Pure."""
    return ["ollama", "create", str(policy.model_name), "-f", str(modelfile_path)]


def serve_command(policy) -> List[str]:
    """The `ollama serve` invocation that serves the created model on the configured
    port (bind host/port come from Ollama's own `OLLAMA_HOST` env at deploy). Pure —
    the runner does not start it; Ollama's daemon typically already serves :11434."""
    return ["ollama", "serve"]


def run_serve_pipeline(
    *,
    policy,
    workspace: str,
    timestamp=None,
) -> Dict[str, object]:
    """Fuse R1's adapter into the base, export GGUF, render the Modelfile, and
    `ollama create` our model — the `make serve-language` core. Refuses LOUDLY (a
    clear RuntimeError naming the host requirement) when MLX or Ollama is missing, or
    when R1's adapter is absent, so it never silently no-ops or fakes serving. When
    the host is ready: runs the MLX-LM fuse + GGUF export, writes the Modelfile into
    `workspace`, and runs `ollama create`; Ollama's server then serves the model on
    :11434. Returns the served-model metadata."""
    if not mlx_available() or not ollama_available():
        raise RuntimeError("cannot serve: " + _SERVE_REQUIREMENT)
    adapter_path = Path(policy.adapter_path)
    if not adapter_path.exists():
        raise RuntimeError("cannot serve: " + _SERVE_REQUIREMENT)

    workspace_path = Path(workspace)
    workspace_path.mkdir(parents=True, exist_ok=True)
    Path(policy.fused_path).mkdir(parents=True, exist_ok=True)

    # Inherit stdout/stderr so the fuse + GGUF export progress streams to the console.
    subprocess.run(fuse_command(policy), check=True)

    modelfile_path = workspace_path / "Modelfile"
    modelfile_path.write_text(render_modelfile(policy))

    subprocess.run(
        ollama_create_command(policy, modelfile_path=str(modelfile_path)), check=True
    )

    return {
        "model_name": policy.model_name,
        "base_model": policy.base_model,
        "adapter_path": str(adapter_path),
        "gguf_path": policy.gguf_path,
        "modelfile": str(modelfile_path),
        "port": policy.port,
    }


def main(argv: Optional[List[str]] = None) -> None:
    """Fuse R1's adapter, export GGUF, and `ollama create` our model — the
    `make serve-language` entry. Paths + params are config/env-driven. When the host
    lacks MLX or Ollama (or R1's adapter) it exits LOUDLY with exactly what's needed,
    rather than pretending to serve."""
    from app.config_service import ConfigService

    config_root = os.environ.get("CONFIG_ROOT", str(_DEFAULT_CONFIG_ROOT))
    workspace = os.environ.get("LANGUAGE_WORKSPACE", str(_DEFAULT_WORKSPACE))
    config = ConfigService.from_files(config_root)
    policy = config.serve_policy()

    print(
        f"serving our fine-tuned model as {policy.model_name!r}: fuse "
        f"{policy.adapter_path} into {policy.base_model} -> GGUF "
        f"({policy.gguf_path}) -> `ollama create`"
    )

    if not mlx_available() or not ollama_available() or not Path(policy.adapter_path).exists():
        raise SystemExit("cannot serve: " + _SERVE_REQUIREMENT)

    metrics = run_serve_pipeline(policy=policy, workspace=workspace)

    print(
        f"created Ollama model {metrics['model_name']!r} (from {metrics['gguf_path']}).\n"
        f"  ensure Ollama is serving on :{metrics['port']} (`ollama serve`), then set\n"
        f"  narrator.kind: local in config/language.yaml — the being answers from our\n"
        f"  model. From the engine CONTAINER, point the adapter at the Mac host:\n"
        f"  OLLAMA_BASE_URL=http://host.docker.internal:{metrics['port']}"
    )


if __name__ == "__main__":
    main()

"""Behavior: the reading faculty scaffolds a host-native pipeline that SERVES our
fine-tuned model via Ollama and wires it to the existing `LanguageModelPort`
(reading R2, ADR 0037). The pipeline — fuse R1's LoRA into the base, export GGUF,
`ollama create` a named model that Ollama serves on :11434 — runs ONLY on an
Apple-Silicon Mac with `mlx_lm` + Ollama; so here (neither present) the runner
refuses LOUDLY and names exactly what the host needs. The config-driven command
construction, the Modelfile render, and the config wiring that ties R1's adapter
and the served model name into the `local` narrator endpoint ARE exercised, with
no MLX, no Ollama, and no network — the adapter->endpoint contract is proven
against a MOCKED HTTP client. A live `complete()` against a real Ollama is gated
and skips here.
"""
from __future__ import annotations

import os

import pytest

from app.adapters.local_language_model import LocalLanguageModel
from app.config_service import ConfigService
from app.language import serve

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

_SERVE_CFG = {
    "finetune": {
        "base_model": "Qwen/Qwen2.5-3B-Instruct",
        "adapter_path": "models/language/adapter",
    },
    "serve": {
        "model_name": "jarvis-reader",
        "fused_path": "models/language/fused",
        "gguf_file": "jarvis-reader-f16.gguf",
        "port": 11434,
        "params": {"temperature": 0.7, "top_p": 0.9, "num_ctx": 4096},
        "system": "",
    },
    "narrator": {
        "kind": "local",
        "local": {"base_url": "http://localhost:11434", "model": "jarvis-reader"},
    },
}


def _config(language=_SERVE_CFG) -> ConfigService:
    return ConfigService.from_dict(tick_rates={}, emotions={}, language=language)


# --- the serve policy: config-driven, reusing R1's base + adapter -----------


def test_serve_policy_reads_the_configured_values():
    policy = _config().serve_policy()
    assert policy.model_name == "jarvis-reader"
    assert policy.fused_path == "models/language/fused"
    assert policy.gguf_file == "jarvis-reader-f16.gguf"
    assert policy.port == 11434
    assert policy.params["temperature"] == 0.7


def test_serve_policy_reuses_the_finetune_base_and_adapter():
    # base_model + adapter_path are R1's — one source of truth, not re-declared.
    policy = _config().serve_policy()
    assert policy.base_model == "Qwen/Qwen2.5-3B-Instruct"
    assert policy.adapter_path == "models/language/adapter"


def test_serve_policy_gguf_path_joins_the_fused_dir_and_file():
    policy = _config().serve_policy()
    assert policy.gguf_path == "models/language/fused/jarvis-reader-f16.gguf"


# --- pure command builders (no MLX, no Ollama) ------------------------------


def test_fuse_command_fuses_the_adapter_into_the_base_and_exports_gguf():
    policy = _config().serve_policy()
    cmd = serve.fuse_command(policy)
    assert "mlx_lm.fuse" in cmd                 # the host-native MLX-LM fuse entry
    assert policy.base_model in cmd
    assert policy.adapter_path in cmd
    assert "--export-gguf" in cmd               # fuse -> GGUF in one step
    assert policy.gguf_file in cmd


def test_ollama_create_command_names_the_model_and_modelfile(tmp_path):
    policy = _config().serve_policy()
    modelfile = str(tmp_path / "Modelfile")
    cmd = serve.ollama_create_command(policy, modelfile_path=modelfile)
    assert cmd[0] == "ollama"
    assert "create" in cmd
    assert policy.model_name in cmd
    assert modelfile in cmd


def test_modelfile_renders_from_the_gguf_with_config_driven_params():
    policy = _config().serve_policy()
    text = serve.render_modelfile(policy)
    assert text.startswith(f"FROM {policy.gguf_path}")
    assert "PARAMETER temperature 0.7" in text
    assert "PARAMETER top_p 0.9" in text


# --- the absent-toolchain guard: refuse loudly, never fake ------------------


@pytest.mark.skipif(
    serve.mlx_available() and serve.ollama_available(),
    reason="both MLX and Ollama present — the loud-refusal path only fires when the host lacks them",
)
def test_serve_without_the_host_toolchain_refuses_and_names_the_requirement(tmp_path):
    policy = _config().serve_policy()
    with pytest.raises(RuntimeError) as excinfo:
        serve.run_serve_pipeline(policy=policy, workspace=str(tmp_path / "ws"))
    message = str(excinfo.value).lower()
    assert "ollama" in message         # names the missing server
    assert "host" in message           # and that it must run on the Mac host
    assert "adapter" in message        # and that R1's adapter is required


# --- the config wiring: our fine-tuned model reaches the LanguageModelPort ---


def test_the_local_adapter_posts_the_configured_served_model_name():
    # The adapter->endpoint contract, proven offline against a mocked HTTP client:
    # LocalLanguageModel issues the right request to the configured Ollama endpoint
    # and returns the model text, selecting OUR served model name (no network).
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "our own model, speaking"}

    class _Client:
        def __init__(self):
            self.last_url = None
            self.last_json = None

        def post(self, url, json=None):
            self.last_url = url
            self.last_json = json
            return _Resp()

    policy = _config().local_model_policy()
    client = _Client()
    model = LocalLanguageModel(
        base_url=policy.base_url, model=policy.model, client=client, env={}
    )

    out = model.complete("a grounded prompt")

    assert out == "our own model, speaking"
    assert client.last_url == "http://localhost:11434/api/generate"
    assert client.last_json["model"] == "jarvis-reader"


def test_shipped_config_wires_the_served_model_name_into_the_local_narrator():
    # One source of truth: the model `serve` creates is the model the `local`
    # narrator endpoint calls, on the shipped config.
    config = ConfigService.from_files(_CONFIG_ROOT)
    serve_policy = config.serve_policy()
    local_policy = config.local_model_policy()
    assert local_policy.model == serve_policy.model_name


# --- a live serve is gated: needs a real Ollama on the endpoint -------------


def test_served_model_answers_over_the_live_endpoint():
    # The genuine end-to-end call: our fused+GGUF model, created in Ollama and
    # served on :11434, answering through the LanguageModelPort. It needs a live
    # Ollama server with the model loaded, so it is skipped everywhere but a Mac
    # host that has run `make serve-language`.
    if not serve.ollama_available() or not os.environ.get("OLLAMA_LIVE_TEST"):
        pytest.skip(
            "requires a live Ollama server with our model; run `make serve-language` "
            "on the Mac host and set OLLAMA_LIVE_TEST=1 to exercise it"
        )
    config = ConfigService.from_files(_CONFIG_ROOT)
    policy = config.local_model_policy()
    model = LocalLanguageModel(
        base_url=policy.base_url, model=policy.model, base_url_env=policy.base_url_env
    )
    assert model.complete("Say hello in one word.").strip()

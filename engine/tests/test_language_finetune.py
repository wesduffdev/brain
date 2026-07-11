"""Behavior: the reading faculty scaffolds a host-native MLX-LM LoRA fine-tune of
our own base model (reading R1, ADR 0036). The actual training runs ONLY on an
Apple-Silicon Mac with `mlx_lm` (Metal GPU) — so here, where MLX is absent, the
runner refuses LOUDLY and names exactly what the host needs, and the end-to-end
training behavior is gated (skipped). The config-driven command construction and
the config accessor ARE exercised, with no MLX.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config_service import ConfigService
from app.language import finetune
from app.language.ingest import ingest_text

_FIXED_TIME = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)

_FINETUNE_CFG = {
    "finetune": {
        "base_model": "Qwen/Qwen2.5-3B-Instruct",
        "adapter_path": "models/language/adapter",
        "ingest": {"max_chars": 800, "overlap": 80, "min_chunk_chars": 1, "valid_fraction": 0.1},
        "lora": {
            "iters": 123,
            "batch_size": 4,
            "learning_rate": 0.00002,
            "num_layers": 8,
            "rank": 16,
            "scale": 20.0,
            "dropout": 0.0,
            "max_seq_length": 512,
            "seed": 7,
        },
        "sample": {"prompt": "Say what you read:", "max_tokens": 64},
    }
}


def _config(finetune_cfg=_FINETUNE_CFG):
    return ConfigService.from_dict(tick_rates={}, emotions={}, language=finetune_cfg)


def test_finetune_policy_reads_the_configured_values():
    policy = _config().finetune_policy()
    assert policy.base_model == "Qwen/Qwen2.5-3B-Instruct"
    assert policy.adapter_path == "models/language/adapter"
    assert policy.iters == 123
    assert policy.rank == 16
    assert policy.seed == 7
    assert policy.max_chars == 800
    assert policy.sample_prompt == "Say what you read:"
    assert policy.sample_max_tokens == 64


def test_finetune_policy_defaults_to_the_qwen_base_when_unconfigured():
    policy = ConfigService.from_dict(tick_rates={}, emotions={}).finetune_policy()
    assert policy.base_model == "Qwen/Qwen2.5-3B-Instruct"
    assert policy.adapter_path == "models/language/adapter"


def test_lora_command_targets_the_configured_base_model_and_dataset(tmp_path):
    policy = _config().finetune_policy()
    cmd = finetune.lora_command(
        policy,
        data_dir=str(tmp_path / "data"),
        adapter_path=str(tmp_path / "adapter"),
        config_path=str(tmp_path / "lora.yaml"),
    )
    assert "mlx_lm.lora" in cmd            # the host-native MLX-LM LoRA entry
    assert "--train" in cmd
    assert policy.base_model in cmd
    assert str(tmp_path / "data") in cmd
    assert str(tmp_path / "adapter") in cmd
    assert str(policy.iters) in cmd


def test_generate_command_samples_the_finetuned_adapter(tmp_path):
    policy = _config().finetune_policy()
    cmd = finetune.generate_command(policy, adapter_path=str(tmp_path / "adapter"))
    assert "mlx_lm.generate" in cmd
    assert policy.base_model in cmd
    assert policy.sample_prompt in cmd
    assert str(tmp_path / "adapter") in cmd


def test_lora_config_carries_the_configured_rank():
    policy = _config().finetune_policy()
    params = finetune.lora_config_dict(policy)["lora_parameters"]
    assert params["rank"] == policy.rank


@pytest.mark.skipif(finetune.mlx_available(), reason="MLX present — the loud-refusal path only fires when it is absent")
def test_finetune_without_mlx_refuses_and_names_the_requirement(tmp_path):
    doc = ingest_text("A little corpus to learn from.", source="mem", max_chars=1000)
    policy = _config().finetune_policy()
    with pytest.raises(RuntimeError) as excinfo:
        finetune.run_finetune(
            document=doc,
            policy=policy,
            workspace=str(tmp_path / "ws"),
            timestamp=_FIXED_TIME,
        )
    message = str(excinfo.value).lower()
    assert "mlx" in message              # names the missing toolchain
    assert "host" in message             # and that it must run on the Mac host


def test_finetuned_model_generates_in_corpus_style(tmp_path):
    # The genuine end-to-end LoRA fine-tune + sampled generation. It needs MLX
    # (Apple-Silicon Metal GPU) AND the multi-GB base-model weights, so it is
    # skipped everywhere but a Mac host running `make train-language`.
    pytest.importorskip("mlx_lm")
    pytest.skip(
        "requires Apple-Silicon Metal GPU + the base-model weights; "
        "run `make train-language DOC=<path>` on the Mac host to watch it train"
    )

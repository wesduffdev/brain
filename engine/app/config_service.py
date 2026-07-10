"""ConfigService — the one place that knows configuration exists.

It turns authored config (YAML files, or a dict in tests) into typed policies
the services consume. Consumers never see file paths, YAML, or raw dicts; they
ask for `need_policies()`, `emotion_rules()`, and so on. This is the seam the
brief calls for: fine-tuning happens in `config/*.yaml`, and only this module
changes shape if the config format ever does.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping

from app.policies import EmotionRule, NeedTickPolicy


class ConfigService:
    def __init__(self, tick_rates: Mapping, emotions: Mapping):
        self._tick_rates = tick_rates
        self._emotions = emotions

    # --- construction -----------------------------------------------------

    @classmethod
    def from_dict(cls, tick_rates: Mapping, emotions: Mapping) -> "ConfigService":
        """Build from already-parsed config. Used by tests so behavior is
        pinned to explicit values, not to whatever the shipped files hold."""
        return cls(tick_rates, emotions)

    @classmethod
    def from_files(cls, config_root: str) -> "ConfigService":
        """Load the authored YAML under `config_root`. `yaml` is imported here,
        lazily, so the pure-Python core imports with zero third-party deps."""
        import yaml  # noqa: PLC0415 — kept out of module import path on purpose

        root = Path(config_root)
        tick_rates = yaml.safe_load((root / "tick_rates.yaml").read_text())
        emotions = yaml.safe_load((root / "emotions.yaml").read_text())
        return cls(tick_rates, emotions)

    # --- ticks / needs ----------------------------------------------------

    def tick_duration_ms(self) -> int:
        return int(self._tick_rates["tick"]["duration_ms"])

    def need_policies(self) -> Dict[str, NeedTickPolicy]:
        policies: Dict[str, NeedTickPolicy] = {}
        for name, spec in self._tick_rates["needs"].items():
            policies[name] = NeedTickPolicy(
                name=name,
                direction=spec["direction"],
                amount=int(spec["amount"]),
                every_ticks=int(spec["every_ticks"]),
                min_value=int(spec["min"]),
                max_value=int(spec["max"]),
                start=int(spec["start"]),
            )
        return policies

    def initial_needs(self) -> Dict[str, int]:
        return {name: policy.start for name, policy in self.need_policies().items()}

    # --- emotions ---------------------------------------------------------

    def emotion_rules(self) -> List[EmotionRule]:
        return [
            EmotionRule(
                emotion=rule["emotion"],
                need=rule["need"],
                op=rule["op"],
                value=int(rule["value"]),
            )
            for rule in self._emotions.get("rules", [])
        ]

    def default_emotion(self) -> str:
        return self._emotions.get("default", "calm")

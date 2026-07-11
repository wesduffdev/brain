"""TraitService — the being's slow personality, drifting from what it lives (v6).

Where a preference is fast and object-specific, a TRAIT is slow and being-wide: a
tendency that shifts a little with each experience and, over many, settles into an
individual temperament. This service holds two — a CAUTION tendency and a CURIOSITY
tendency — and does the three things a personality does:

- **it drifts** (`observe_interaction`): a NEGATIVE experience — an outcome that
  eroded the being on balance (a burn: felt safety and comfort falling) — nudges
  CAUTION up; a POSITIVE exploration (a safe, non-harmful interaction) nudges
  CURIOSITY up. Which way an experience pushes the being is its VALENCE, the
  felt-consequence net effect (`OutcomeEffectPolicy.net_effect`) — the same signed
  "was that good or bad for me?" the learned preference reads. Each nudge is a small
  `drift_rate` fraction toward the trait's ceiling (the saturating curve
  confidence/familiarity use), so a single interaction barely moves the being but
  repetition forms a stable disposition. (In the current perception model the being
  senses an object's properties truly, so its rule layer already foresees a burn —
  literal prediction-*surprise* is structurally 0; the felt negative outcome is what
  the being learns caution from. Weighting caution by genuine surprise is a natural
  extension once the being can misperceive.)
- **it modulates behaviour** (`modulate`): the CURRENT caution level amplifies the
  being's aversion to its bad memories — a being that has been hurt and grown wary
  drops a risky action's score more for the same remembered burn — while curiosity
  amplifies its draw toward the memories that turned out well. It reshapes the
  learned-preference bias the decision already computes; it never manufactures a bias
  where the being remembers nothing, and it only touches the *safe* candidates the
  preference map is built from, so no trait can push the being past the safety floor;
- **it exposes itself** (`levels`): the traits ride on the being's state snapshot, so
  the individual temperament the being has grown is observable.

Both the drift rates and the decision gains live in `config/traits.yaml`
(`TraitPolicy`); with the default (zero) gains a being's traits drift but do not yet
steer behaviour, and with the default (zero) rates they do not drift — so a config
with no `traits` block leaves behaviour byte-identical to the pre-v6 baseline.
Nothing here reads YAML.
"""
from __future__ import annotations

from typing import Dict, Mapping, Sequence, Tuple

from app.policies import OutcomeEffectPolicy, TraitPolicy


class TraitService:
    def __init__(self, policy: TraitPolicy):
        self._policy = policy
        self._caution = policy.caution.start
        self._curiosity = policy.curiosity.start

    def levels(self) -> Dict[str, float]:
        """The being's current temperament — its caution and curiosity tendencies,
        each in ``[0, 1]`` — as a plain map for the state snapshot."""
        return {"caution": self._caution, "curiosity": self._curiosity}

    def observe_interaction(
        self,
        *,
        expected: Sequence[str],
        observed: Sequence[str],
        outcome_effects: OutcomeEffectPolicy,
    ) -> None:
        """Fold one finished interaction into the being's personality. A harmful
        outcome (its valence net-negative) lifts caution; a safe/rewarding one lifts
        curiosity. Slow by construction — a nudge toward the trait's ceiling, not a
        jump. `expected` is accepted for when a future perception model lets genuine
        surprise weight the drift; today the felt outcome valence is the signal."""
        valence = outcome_effects.net_effect(observed)
        if valence < 0:
            self._caution = self._policy.caution.drift(self._caution, 1.0)
        else:
            self._curiosity = self._policy.curiosity.drift(self._curiosity, 1.0)

    def modulate(
        self, biases: Mapping[Tuple[str, str], float]
    ) -> Dict[Tuple[str, str], float]:
        """The learned-preference `biases` reshaped by the being's temperament: an
        aversive (negative) bias is amplified by current caution, an appealing
        (positive) one by current curiosity, each through its config `decision_gain`.
        Returns a new map; an empty input stays empty (a wary being with nothing to
        fear behaves as a bold one would)."""
        caution_gain = 1.0 + self._policy.caution.decision_gain * self._caution
        curiosity_gain = 1.0 + self._policy.curiosity.decision_gain * self._curiosity
        modulated: Dict[Tuple[str, str], float] = {}
        for key, bias in biases.items():
            modulated[key] = bias * (caution_gain if bias < 0 else curiosity_gain)
        return modulated

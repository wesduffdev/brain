"""TemperamentService — the being's ADAPTIVE instinct temperament (INS-TEMPERAMENT,
ADR 0031).

Where `InstinctRuntimePolicy` sets the being's BASELINE reaction thresholds — the
probability at or above which each protective reaction fires (INS-RT, ADR 0026) —
this service is the slow PERSONALIZATION of those thresholds from lived experience:
the instinct-layer sibling of the v6 slow trait drift (`TraitService`). It holds one
EFFECTIVE threshold per reaction label, seeded from the config baseline, and drifts it
with the being's OWN felt-harm signal — its `pain` need (no parallel harm detector):

- HABITUATION — a startle that FIRES and proves HARMLESS (pain did not rise that tick)
  nudges that label's threshold UP, toward the policy ceiling. So a repeated harmless
  startle (a ball that rushes in but never hurts) gradually stops triggering — the
  being learns it is nothing to fear.
- SENSITIZATION — a HARMFUL outcome (pain spiked) nudges EVERY threshold DOWN, toward
  the policy floor. So after being hurt the being is jumpier: a previously
  sub-threshold stimulus may now fire.

The `InstinctService` consults `threshold(label)` here instead of the raw config
threshold when this service is wired, so the SAME stimulus provokes DIFFERENT reactions
as the being accrues experience — the slice's observable outcome. Selection is still
the consumer's concern and can never bypass the safety floor (ADR 0026/0029):
temperament shifts only the reaction GATING (which reaction fires), never safety, and
never whether an action is allowed. `pain` rising is the harm cue precisely because it
is the being's felt-harm need (ADR 0014); the drift is otherwise slow and config-driven.

Relation to the CAUTION trait (v6, `TraitService`): both are harm-driven and REINFORCE
a hurt being's defensiveness, yet they act on DIFFERENT layers and are NOT
double-counted — caution reshapes the DELIBERATE decision (amplifying aversion to bad
MEMORIES), while sensitization reshapes the FAST pre-conceptual REACTION threshold. One
harmful experience thus leaves the being both more cautious in what it CHOOSES and
jumpier in what STARTLES it, through two orthogonal mechanisms (see ADR 0031). The two
also read complementary facets of the same harmful outcome: caution reads its negative
VALENCE (net erosion), sensitization reads the acute PAIN spike.

Transient in-process, like the ADR 0020 familiarity signal and the v6 traits: the
drifted thresholds live here for the being's lifetime, not persisted. With both drift
rates 0 (the default) `threshold(label)` returns the baseline exactly — byte-identical
to the static-threshold consumer.
"""
from __future__ import annotations

from typing import Dict, Mapping, Set

from app.policies import ReactionTemperamentPolicy


class TemperamentService:
    def __init__(
        self, policy: ReactionTemperamentPolicy, *, base_thresholds: Mapping[str, float]
    ) -> None:
        self._policy = policy
        self._base: Dict[str, float] = {str(label): float(t) for label, t in base_thresholds.items()}
        # The being's CURRENT effective thresholds, seeded from the baseline and drifted
        # by experience — one per label the runtime policy can fire.
        self._threshold: Dict[str, float] = dict(self._base)
        # Labels that FIRED this tick, awaiting the tick's harm verdict at `settle`.
        self._fired: Set[str] = set()

    def threshold(self, label: str) -> float:
        """The being's CURRENT effective threshold for `label` — the config baseline
        reshaped by habituation/sensitization. An unmanaged label falls back to its
        baseline (an unreachable 1.0 when it has none), so an unknown label is never
        made to fire by accident."""
        return self._threshold.get(label, self._base.get(label, 1.0))

    def record_reaction(self, label: str) -> None:
        """Note that a reaction of `label` FIRED this tick — a candidate to HABITUATE if
        the tick proves harmless (resolved at `settle`)."""
        self._fired.add(str(label))

    def settle(self, *, harm: bool) -> None:
        """Fold this tick's outcome into the being's temperament, then clear the tick's
        firings. HARM (the being's `pain` rose) SENSITIZES every reaction — each
        effective threshold drifts toward the floor, so the being is jumpier next time
        (a previously sub-threshold stimulus may now fire), and a startle that fired on a
        harmful tick is NOT habituated (harm takes precedence). A HARMLESS tick
        HABITUATES whatever fired — each such threshold drifts toward the ceiling, so a
        repeated harmless startle gradually stops firing. With both rates 0 neither
        branch moves a threshold (byte-identical to the static consumer)."""
        if harm:
            for label in self._threshold:
                self._threshold[label] = self._policy.sensitize(self._threshold[label])
        else:
            for label in self._fired:
                if label in self._threshold:
                    self._threshold[label] = self._policy.habituate(self._threshold[label])
        self._fired.clear()

    def thresholds(self) -> Dict[str, float]:
        """The being's current effective reaction thresholds, per label — how its
        instinct sensitivity stands after a life of startles (habituation raising them)
        and harms (sensitization lowering them). A plain map for observation (the demo /
        `Simulation.reaction_thresholds()` read it); empty when no label is managed."""
        return dict(self._threshold)

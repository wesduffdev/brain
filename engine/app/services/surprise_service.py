"""SurpriseService — how wrong the being was, and how that fades.

Surprise is the mismatch between the outcome the being EXPECTED of an action and
the outcome it OBSERVED — both already carried on every `InteractionEvent`
(`expected_outcome` vs `observed_outcome`), drawn from the outcome vocabulary. It
is measured as the symmetric difference of the two outcome sets over their union
(the Jaccard *distance*): an object that behaves exactly as predicted is
unsurprising (0.0), one that behaves entirely unlike the expectation is maximally
surprising (1.0). It is computed straight from the event, independent of whether
the neural predictor happened to record a prediction.

The service also keeps a decaying, per-object memory of recent surprise: a shock
leaves a trace that fades each tick by the config `decay`, so a lately-surprising
object stays interesting for a while and then settles. That recent-surprise trace
is one of the signals the being's curiosity is built from (`CuriosityService`).
The memory is transient (this slice keeps it in process, not persisted).
"""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

from app.policies import SurprisePolicy


class SurpriseService:
    def __init__(self, policy: SurprisePolicy):
        self._policy = policy
        # object_id -> (tick it was last recorded, its accumulated surprise then).
        self._recent: Dict[str, Tuple[int, float]] = {}

    def surprise(self, expected: Sequence[str], observed: Sequence[str]) -> float:
        """How surprising it is that `observed` happened when `expected` was
        anticipated — the share of all outcomes involved that the two sets DISAGREE
        on, in ``[0, 1]``. Identical expectations and observations score 0.0;
        wholly-different ones score 1.0. Expecting nothing and observing nothing is
        unsurprising (0.0)."""
        exp, obs = set(expected), set(observed)
        union = exp | obs
        if not union:
            return 0.0
        return len(exp ^ obs) / len(union)

    def record(
        self, *, object_id: str, tick: int, expected: Sequence[str], observed: Sequence[str]
    ) -> float:
        """Fold one interaction's surprise into the object's recent-surprise trace
        and return the surprise measured. The new shock adds onto whatever is left
        of the prior (decayed) trace, capped at 1.0, and resets the clock — so
        repeated surprises keep an object interesting."""
        measured = self.surprise(expected, observed)
        trace = min(1.0, self.recent(object_id, tick) + measured)
        self._recent[object_id] = (tick, trace)
        return measured

    def recent(self, object_id: str, tick: int) -> float:
        """The object's decayed recent surprise as of `tick` — its last recorded
        trace faded by `decay` for every tick elapsed since. 0.0 for an object that
        has never surprised the being."""
        entry = self._recent.get(object_id)
        if entry is None:
            return 0.0
        last_tick, trace = entry
        elapsed = max(0, tick - last_tick)
        return trace * (self._policy.decay ** elapsed)

"""CuriosityService — how strongly the being wants to explore a perceived object.

The being is drawn to what it cannot yet predict. This service turns what it has
lived — how FAMILIAR each perceived property has become — plus how recently an
object SURPRISED it into one curiosity number per object, composed from the four
config-weighted signals of `CuriosityWeights`:

    curiosity = novelty + uncertainty + recent_surprise - familiarity

Familiarity is held here as a per-PROPERTY level in ``[0, 1]`` that rises as the
being acts on objects showing that property (`learn`), on the same saturating
curve concept confidence uses — so the being generalizes: a never-seen object
that shares properties with things it has handled is already partly familiar,
while one made of wholly-new properties is fully novel. From an object's per-
property familiarity it derives:

- `novelty`     — the share of the object's properties it has never met;
- `familiarity` — the mean familiarity across the object's properties (pulls
                  curiosity down);
- `uncertainty` — among the properties it HAS met, how far from mastered they are
                  (met-but-not-sure).

`recent_surprise` is supplied by the caller (the SurpriseService's decayed
trace). The familiarity memory is transient this slice (kept in process). Nothing
here reads YAML; the weights arrive as a typed `CuriosityWeights`.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from app.policies import CuriosityWeights


class CuriosityService:
    def __init__(self, weights: CuriosityWeights):
        self._weights = weights
        self._familiarity: Dict[str, float] = {}

    def learn(self, perceived_properties: Sequence[str]) -> None:
        """Register one interaction with an object shown to have
        `perceived_properties`: each property grows more familiar, moving toward
        mastery by the config `familiarity_rate`."""
        for prop in set(perceived_properties):
            self._familiarity[prop] = self._weights.reinforce(self._familiarity.get(prop, 0.0))

    def curiosity(self, *, perceived_properties: Sequence[str], recent_surprise: float = 0.0) -> float:
        """The being's curiosity toward an object it perceives as
        `perceived_properties`, given its `recent_surprise` (0 when the object has
        not lately surprised it). Higher for the novel and the uncertain, lower for
        the familiar — exactly the config-weighted combination of the four
        signals."""
        props: List[str] = list(dict.fromkeys(perceived_properties))  # unique, order-stable
        if not props:
            novelty, uncertainty, familiarity = 1.0, 0.0, 0.0
        else:
            levels = [self._familiarity.get(prop, 0.0) for prop in props]
            seen = [level for level in levels if level > 0.0]
            novelty = sum(1 for level in levels if level <= 0.0) / len(props)
            familiarity = sum(levels) / len(props)
            uncertainty = (sum(1.0 - level for level in seen) / len(seen)) if seen else 0.0
        return self._weights.combine(
            novelty=novelty,
            uncertainty=uncertainty,
            recent_surprise=recent_surprise,
            familiarity=familiarity,
        )

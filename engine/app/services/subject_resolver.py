"""SubjectResolver — maps a natural-language subject term to the being's PERCEIVED
property tokens (S3, ADR 0034).

The being knows objects by what it PERCEIVES, never by a human name (ADR 0002), so
a subject query cannot be answered by matching an English label. This resolver is
the bridge: it reads a subject phrase ("hot things", "the round red thing") and
returns the PERCEIVED-property tokens it contains (`["hot"]`, `["round", "red"]`),
drawn from the perceived-property vocabulary (`config/object_properties.yaml`).
Anything that is not a perceived-property token — filler words, and any name the
being cannot see — is simply not resolved, so a term the being has no perceptual
handle on ("dragons") resolves to nothing and is answered as unknown.

Resolution is deliberately vocabulary-bounded: it maps ONLY to tokens the being
could actually perceive. Whether the being has *learned* anything about a resolved
property is a separate question the SubjectReportService answers — resolving to a
valid property it has never encountered still yields an honest "I don't know",
never a borrowed or invented lesson. The being's already-learned concept features
are also accepted (they are perceived-property tokens too), so the resolver stays
correct even where a property is learned before it is catalogued.
"""
from __future__ import annotations

import re
from typing import Iterable, List

_TOKEN = re.compile(r"[a-z0-9]+")


class SubjectResolver:
    def __init__(self, property_vocab: Iterable[str]) -> None:
        # De-duplicated, order-preserved, lower-cased perceived-property tokens.
        self._vocab = tuple(
            dict.fromkeys(str(prop).lower() for prop in property_vocab)
        )

    def resolve(self, subject: str, *, known_features: Iterable[str] = ()) -> List[str]:
        """The PERCEIVED-property tokens in ``subject``, in the order they appear,
        de-duplicated. ``known_features`` (the being's already-learned concept
        features) are accepted alongside the catalogued vocabulary. A term with no
        perceived-property token resolves to an empty list — it is unknown, and the
        caller answers it honestly rather than inventing a meaning for it."""
        vocab = set(self._vocab) | {str(feature).lower() for feature in known_features}
        resolved: List[str] = []
        for token in _TOKEN.findall(str(subject).lower()):
            if token in vocab and token not in resolved:
                resolved.append(token)
        return resolved

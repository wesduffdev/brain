"""PredictionExplanationService — turns a graph walk into a prediction's reason.

A prediction the being makes about an object — "this thing will roll if I push
it" — should not arrive bare; it should carry the ``object → property → outcome``
walk through the concept graph that justifies it. This service is the bridge from
the raw graph traversal (`ConceptPathService`) to that prediction-facing
EXPLANATION: it fixes the explanation TEMPLATE (``HAS_PROPERTY`` then
``PREDICTS`` — an object has a property, that property predicts an outcome), asks
the path service to walk it, and turns the resulting walk into an `ExplanationPath`
naming the object, the mediating property, the predicted outcome, and the walk's
aggregate confidence.

`explain` answers one prediction (the strongest walk from a given object to a
given outcome, or ``None`` when the graph supports none). `explanations` answers
the whole being: every ``object → property → outcome`` prediction the graph
supports, keeping the strongest walk per (object, outcome) so a prediction backed
by more than one property is explained by the property the being is surest of.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.domain.concept_graph import (
    HAS_PROPERTY,
    OBJECT,
    OUTCOME,
    PREDICTS,
    ConceptPath,
    ExplanationPath,
)
from app.services.concept_path_service import ConceptPathService

# The explanation walk: an object HAS_PROPERTY a property that PREDICTS an outcome.
_EXPLANATION_TEMPLATE = (HAS_PROPERTY, PREDICTS)


class PredictionExplanationService:
    def __init__(self, paths: ConceptPathService):
        self._paths = paths

    def explain(
        self, *, being_id: str, object_id: str, outcome: str
    ) -> Optional[ExplanationPath]:
        """The strongest ``object → property → outcome`` walk that justifies
        predicting `outcome` for `object_id`, or ``None`` when the graph supports
        no such walk (the being has no reason to make that prediction)."""
        walks = self._paths.paths(
            being_id=being_id,
            via_kinds=_EXPLANATION_TEMPLATE,
            source_kind=OBJECT,
            source_label=object_id,
            target_kind=OUTCOME,
            target_label=outcome,
        )
        strongest = _strongest(walks)
        return _to_explanation(strongest) if strongest is not None else None

    def explanations(self, *, being_id: str) -> List[ExplanationPath]:
        """Every prediction the being's graph supports, each with its explanation
        walk — one per (object, outcome), kept at the strongest supporting
        property so a prediction backed by several properties is explained by the
        one the being is surest of."""
        walks = self._paths.paths(
            being_id=being_id,
            via_kinds=_EXPLANATION_TEMPLATE,
            source_kind=OBJECT,
            target_kind=OUTCOME,
        )
        strongest_per_prediction: Dict[Tuple[str, str], ConceptPath] = {}
        for walk in walks:
            key = (walk.nodes[0].label, walk.nodes[-1].label)
            best = strongest_per_prediction.get(key)
            if best is None or walk.confidence > best.confidence:
                strongest_per_prediction[key] = walk
        return [_to_explanation(walk) for walk in strongest_per_prediction.values()]


def _strongest(walks: List[ConceptPath]) -> Optional[ConceptPath]:
    """The most-confident walk, or ``None`` when there are none."""
    return max(walks, key=lambda walk: walk.confidence) if walks else None


def _to_explanation(walk: ConceptPath) -> ExplanationPath:
    """Turn a raw ``object → property → outcome`` walk into a prediction-facing
    ExplanationPath."""
    return ExplanationPath(
        being_id=walk.being_id,
        object_id=walk.nodes[0].label,
        property=walk.nodes[1].label,
        outcome=walk.nodes[-1].label,
        confidence=walk.confidence,
        path=walk.labels,
    )

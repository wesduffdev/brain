"""SubjectReportService — the being answers what it KNOWS and how it FEELS about a
subject, from its own learning (S3, ADR 0034).

The subject half of the self-report surface. Where `MemorySummaryService` looks
back over what the being DID, this answers "what do you know / how do you feel
about X?" from what it has LEARNED: its concept schemas (a perceived property +
action → an outcome, with a confidence), the graph explanations that justify a
prediction (property → outcome), the per-object beliefs those concepts formed,
and the emotions its memories recorded of things bearing that property. It
resolves the subject to PERCEIVED-property tokens (via `SubjectResolver` — never a
developer label, ADR 0002), gathers the learned facts keyed on those properties,
and hands them to the narrator as the SAME kind of fact-line prompt the other
narration services build (ADR 0032) — so the deterministic template renders it
offline and a real model (S2) reads the same facts under "use only these facts".

Grounded by construction, honest about the unknown. A subject with no learned
fact — whether it resolved to no perceived property at all ("dragons"), or to a
real property the being has simply never encountered ("square things") — is
answered with the config-driven honest no-knowledge line, WITHOUT ever reaching a
model, so the being can never borrow or invent a lesson it has not lived. Like all
of the language layer it reads snapshot dicts and mutates nothing (ADR 0022).
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from app.policies import SubjectQueryPolicy
from app.ports.language_model import LanguageModelPort
from app.services.subject_resolver import SubjectResolver

# A gathered subject fact, keyed on (property, outcome): the learned generalization
# a subject bears, enriched with the action that reveals it and the emotion the
# being felt. `confidence` ranks facts; `action`/`felt`/`salience` colour the prose.
_Fact = Dict[str, object]


class SubjectReportService:
    def __init__(
        self,
        model: LanguageModelPort,
        resolver: SubjectResolver,
        *,
        policy: Optional[SubjectQueryPolicy] = None,
    ) -> None:
        self._model = model
        self._resolver = resolver
        self._policy = policy if policy is not None else SubjectQueryPolicy()

    def subject_of(self, query: str) -> Optional[str]:
        """The subject phrase a question asks about, or ``None`` when the question
        is not a subject query. A subject is the text after a `query_markers`
        connective ("what do you know ABOUT hot things" → "hot things"); a question
        with no marker ("what have you done recently?") is not a subject query and
        stays on the recent-experience path."""
        lowered = str(query).lower()
        for marker in self._policy.query_markers:
            token = " " + marker + " "
            index = lowered.find(token)
            if index != -1:
                # Slice the ORIGINAL-case query so the subject reads back naturally,
                # trimming surrounding whitespace and trailing sentence punctuation.
                subject = query[index + len(token):].strip().rstrip("?!.,;: ")
                return subject or None
        return None

    def report(
        self,
        subject: str,
        *,
        concepts: Sequence[Mapping] = (),
        beliefs: Sequence[Mapping] = (),
        explanations: Sequence[Mapping] = (),
        memories: Sequence[Mapping] = (),
    ) -> str:
        """A grounded answer for ``subject``, built ONLY from the being's learned
        concepts / beliefs / explanations and the emotions its memories recorded.
        A subject the being has learned nothing about is answered with the honest
        no-knowledge line (never a model call, never an invention)."""
        features = self._resolver.resolve(
            subject, known_features=[str(c.get("feature", "")) for c in concepts]
        )
        facts = self._gather(features, concepts, beliefs, explanations, memories)
        if not facts:
            return self._unknown(subject)
        return self._model.complete(self._prompt(subject, facts)).strip()

    # --- gathering the learned facts for the resolved properties ----------

    def _gather(
        self,
        features: Sequence[str],
        concepts: Sequence[Mapping],
        beliefs: Sequence[Mapping],
        explanations: Sequence[Mapping],
        memories: Sequence[Mapping],
    ) -> List[_Fact]:
        feature_set: Set[str] = set(features)
        if not feature_set:
            return []

        # Best learned fact per (property, outcome): an action from a concept/belief
        # (which carry one) wins over an action-less graph explanation, and the
        # confidence is the strongest supporting source's.
        best: Dict[Tuple[str, str], Dict[str, object]] = {}

        def offer(prop: str, action: str, outcome: str, confidence: float) -> None:
            if prop not in feature_set or not outcome:
                return
            key = (prop, outcome)
            current = best.get(key)
            if current is None:
                best[key] = {"action": action, "confidence": confidence}
                return
            if action and not current["action"]:
                current["action"] = action
            if confidence > float(current["confidence"]):
                current["confidence"] = confidence

        # Concepts are the primary source: a perceived feature + action → outcome.
        for concept in concepts:
            offer(
                str(concept.get("feature", "")),
                str(concept.get("action", "")),
                str(concept.get("outcome", "")),
                float(concept.get("confidence", 0.0) or 0.0),
            )

        # Explanations corroborate a property → outcome prediction (and map each
        # object to the perceived properties it shows, for the beliefs below).
        object_properties: Dict[str, Set[str]] = {}
        for explanation in explanations:
            prop = str(explanation.get("property", ""))
            offer(
                prop,
                "",
                str(explanation.get("outcome", "")),
                float(explanation.get("confidence", 0.0) or 0.0),
            )
            if prop in feature_set:
                object_properties.setdefault(
                    str(explanation.get("objectId", "")), set()
                ).add(prop)

        # Beliefs are per-object; each bears on a resolved property when the object
        # is (per the explanations) perceived to have it.
        for belief in beliefs:
            for prop in object_properties.get(str(belief.get("objectId", "")), ()):
                offer(
                    prop,
                    str(belief.get("action", "")),
                    str(belief.get("outcome", "")),
                    float(belief.get("confidence", 0.0) or 0.0),
                )

        # Memories are an episodic source too — so a being that remembers acting on
        # a thing with the property answers even before the generalization is wired
        # — and they supply the FELT emotion (the most-salient one per property).
        feeling: Dict[str, Tuple[str, float]] = {}
        for memory in memories:
            props = {str(p) for p in (memory.get("perceivedProperties") or [])}
            matched = props & feature_set
            if not matched:
                continue
            action = str(memory.get("action", ""))
            for outcome in (memory.get("observedOutcome") or []):
                for prop in matched:
                    offer(prop, action, str(outcome), 0.0)
            felt = str(memory.get("emotionAfter", ""))
            salience = float(memory.get("priority", 0.0) or 0.0)
            for prop in matched:
                current = feeling.get(prop)
                if felt and (current is None or salience >= current[1]):
                    feeling[prop] = (felt, salience)

        facts: List[_Fact] = []
        for (prop, outcome), value in best.items():
            felt, salience = feeling.get(prop, ("", 0.0))
            facts.append(
                {
                    "property": prop,
                    "action": str(value["action"]),
                    "outcome": outcome,
                    "confidence": float(value["confidence"]),
                    "felt": felt,
                    "salience": salience,
                }
            )
        # Strongest first (a deterministic tie-break keeps the offline render stable).
        facts.sort(
            key=lambda fact: (
                -float(fact["confidence"]),
                str(fact["property"]),
                str(fact["outcome"]),
            )
        )
        return facts[: self._policy.max_facts]

    # --- the narrator prompt / the honest unknown -------------------------

    @staticmethod
    def _prompt(subject: str, facts: Sequence[_Fact]) -> str:
        lines = [
            "Answer, in a few plain first-person sentences, what the being knows "
            "and feels about the subject. Use only these facts; do not invent "
            "properties, outcomes, or feelings.",
            "Subject: " + subject,
            "Facts: " + str(len(facts)),
        ]
        for fact in facts:
            parts = ["kind=subject", "property=" + str(fact["property"])]
            if fact["action"]:
                parts.append("action=" + str(fact["action"]))
            parts.append("outcome=" + str(fact["outcome"]))
            if fact["felt"]:
                parts.append("felt=" + str(fact["felt"]))
            parts.append("salience=%.2f" % float(fact["salience"]))
            parts.append("confidence=%.2f" % float(fact["confidence"]))
            lines.append("- " + " ".join(parts))
        return "\n".join(lines)

    def _unknown(self, subject: str) -> str:
        """The honest no-knowledge answer, config-driven (`{subject}` filled with
        the term). Deliberately deterministic and model-free: with nothing learned,
        there is nothing to phrase and no chance to invent."""
        return self._policy.unknown_response.replace("{subject}", subject.strip())

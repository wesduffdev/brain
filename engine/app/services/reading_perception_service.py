"""ReadingPerceptionService -- reading as a VALIDATED perception event (reading R7,
ADR 0040).

The being learns from what it PERCEIVES and from validated INTERACTIONS
(action -> observed outcome -> memory/concept), never from raw text. So when the
being reads a document, the document changes it only through that SAME door -- and
this service is the bridge that makes a read section walk through it:

  ingested section (pure text, no model)
    -> salient CONTENT TOKENS perceived of it (deterministic; ReadingPerceptionPolicy)
    -> a perceivable object routed through the REAL PerceptionService
       (which DROPS the source/developer label -- ADR 0002)
    -> the reading action VALIDATED through the ActionValidationService
       (an unknown action / an unperceived section is refused here)
    -> the SAME MemoryService / ConceptService a lived interaction uses
       (a memory keyed on perceived tokens; a concept where a token recurs)
    -> the SAME ExplorationPolicyService (curiosity updates -- the tokens grow familiar)

The language model is deliberately ABSENT from this whole path: the service holds no
`LanguageModelPort`, and text enters ONLY as perceived tokens. So a document -- even a
model's own output handed in as text -- can never write a memory/concept row; it can
only become perceived material judged at the validated door (the language-on-top
invariant, ADR 0022). Reading reads and remembers; it never lets language drive state.

Reuses the interaction loop's cognition machinery wholesale (Memory/Concept/Exploration
services) -- it duplicates none of it; it only maps a section onto their inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from app.domain.concept import ConceptSchema
from app.domain.interaction_event import InteractionEvent
from app.domain.memory import Memory
from app.domain.object_entity import ObjectEntity
from app.domain.room import Room
from app.language.ingest import IngestedDocument
from app.policies import ReadingPerceptionPolicy
from app.services.action_validation_service import ActionValidationService
from app.services.concept_service import ConceptService
from app.services.exploration_policy_service import ExplorationPolicyService
from app.services.memory_service import MemoryService
from app.services.perception_service import PerceptionService


@dataclass(frozen=True)
class ReadingObservation:
    """One read section, after it has walked the perception/cognition door: the
    perceived CONTENT TOKENS it was read as, the reading `action`, the `curiosity`
    the being felt toward the material as it read it, and the `memory` (and any
    `concepts`) that formed. `object_id` is the section's stable perceptual identity
    (``read:<source>#<index>``); there is deliberately no developer-label field."""

    source: str
    section_index: int
    object_id: str
    action: str
    perceived_properties: Tuple[str, ...]
    curiosity: float
    memory: Memory
    concepts: Tuple[ConceptSchema, ...]

    def snapshot(self) -> Dict:
        """A plain, serializable view with stable camelCase keys -- what the being
        took from the section, never the developer label (ADR 0002)."""
        return {
            "source": self.source,
            "sectionIndex": self.section_index,
            "objectId": self.object_id,
            "action": self.action,
            "perceivedProperties": list(self.perceived_properties),
            "curiosity": self.curiosity,
            "memoriesFormed": 1,
            "conceptsFormed": len(self.concepts),
        }


class ReadingPerceptionService:
    def __init__(
        self,
        *,
        memory: MemoryService,
        exploration: ExplorationPolicyService,
        validation: ActionValidationService,
        policy: ReadingPerceptionPolicy,
        concepts: Optional[ConceptService] = None,
        unit_of_work=None,
    ) -> None:
        # NOTE (ADR 0022 / R7): there is NO LanguageModelPort parameter here by
        # design -- the writer of cognition is the validated door, never an LM.
        self._memory = memory
        self._exploration = exploration
        self._validation = validation
        self._policy = policy
        self._concepts = concepts
        if unit_of_work is None:
            from app.db.unit_of_work import NullUnitOfWork  # noqa: PLC0415 -- in-memory default

            unit_of_work = NullUnitOfWork()
        self._uow = unit_of_work

    def read(
        self,
        document: IngestedDocument,
        *,
        being_id: str,
        emotion: str,
        tick_source: Callable[[], int],
    ) -> List[ReadingObservation]:
        """Read `document` section by section, forming one validated observation per
        section. `tick_source` yields the tick of each section (reading takes time --
        one perceived moment per section), so each memory has a distinct identity.
        Returns the observations, in reading order. Raises `ActionValidationError`
        (from the validated door) if the reading action is not one the being has."""
        observations: List[ReadingObservation] = []
        for index, section in enumerate(document.chunks):
            observation = self._read_section(
                source=document.source,
                index=index,
                text=section,
                being_id=being_id,
                emotion=emotion,
                tick_source=tick_source,
            )
            if observation is not None:
                observations.append(observation)
        return observations

    def _read_section(
        self,
        *,
        source: str,
        index: int,
        text: str,
        being_id: str,
        emotion: str,
        tick_source: Callable[[], int],
    ) -> Optional[ReadingObservation]:
        tokens = self._policy.salient_tokens(text)
        object_id = "read:{source}#{index}".format(source=source, index=index)

        # Route through the REAL PerceptionService: the section is a perceivable
        # object whose true properties are its content tokens and whose
        # developer_label is the source document -- perception DROPS the label
        # (ADR 0002), so the being perceives tokens only, never the file name.
        entity = ObjectEntity(
            object_id=object_id,
            developer_label=source,
            properties=tokens,
            affordances=(self._policy.action,),
        )
        perceived = PerceptionService({object_id: entity}).perceive(
            Room(room_id="reading", contains=(object_id,))
        )["objects"]
        if not perceived:
            return None
        view = perceived[0]
        perceived_tokens = tuple(view["properties"])
        visible = [obj["objectId"] for obj in perceived]

        # THE VALIDATED DOOR: an unknown reading action, or a section the being
        # cannot perceive, is refused here -- cognition changes only THROUGH it.
        self._validation.validate(
            self._policy.action, object_id, visible_object_ids=visible
        )

        tick = int(tick_source())
        outcome = (self._policy.outcome,)

        # Curiosity toward the material as it is read (from the SAME exploration
        # service a lived tick uses), before it is folded into familiarity.
        curiosity = self._exploration.curiosity_map(perceived=[view], tick=tick).get(
            object_id, 0.0
        )

        # Reading does not drive needs/emotion (language on top, ADR 0022): the
        # emotion before and after are the being's current one, and the outcome is
        # expected, so reading carries no surprise -- it informs, it does not startle.
        event = InteractionEvent(
            being_id=being_id,
            tick=tick,
            object_id=object_id,
            action=self._policy.action,
            expected_outcome=outcome,
            observed_outcome=outcome,
            emotion_before=emotion,
            emotion_after=emotion,
        )

        # One unit of work per section (ADR 0017): the memory and its concepts commit
        # together. This is the interaction loop's own MemoryService/ConceptService --
        # reading reuses the cognition machinery, it does not duplicate it.
        with self._uow.begin():
            memory = self._memory.remember(event, perceived_properties=perceived_tokens)
            concepts = (
                self._concepts.observe(
                    being_id=being_id,
                    tick=tick,
                    object_id=object_id,
                    action=self._policy.action,
                    perceived_properties=perceived_tokens,
                    observed_outcomes=outcome,
                )
                if self._concepts is not None
                else []
            )

        # Fold the material into curiosity/familiarity, so re-reading the same tokens
        # is less novel -- curiosity updates from what the being just read.
        self._exploration.observe_interaction(
            object_id=object_id,
            tick=tick,
            expected=outcome,
            observed=outcome,
            perceived_properties=perceived_tokens,
        )

        return ReadingObservation(
            source=source,
            section_index=index,
            object_id=object_id,
            action=self._policy.action,
            perceived_properties=perceived_tokens,
            curiosity=float(curiosity),
            memory=memory,
            concepts=tuple(concepts),
        )

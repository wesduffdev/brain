"""Behavior of READING-AS-PERCEPTION (reading R7, ADR 0040).

Reading a document CHANGES the being — it forms memories and concepts and its
curiosity updates — but only through the SAME validated perception/cognition door
a lived interaction goes through, NEVER by letting language-model output write
state (the language-on-top invariant, ADR 0022 / READING_VOICEBOX §4).

A read section becomes a perceivable thing: its salient CONTENT TOKENS (extracted
deterministically from the text, no model) are what the being perceives of it; the
read is validated as an allowed reading action through the ActionValidationService;
and only then is it routed to the SAME MemoryService / ConceptService the
interaction loop uses. So:

- reading forms a memory keyed on PERCEIVED TOKENS (never the source/developer
  label — ADR 0002);
- a token that recurs across sections builds a concept (a property->outcome
  regularity), exactly as repeated interactions strengthen a concept;
- the read material updates curiosity (novel tokens grow familiar);
- the write path holds NO LanguageModelPort at all — a raw model string can never
  create a memory; text only ever enters as perceived tokens through the door.

Offline: pure text ingest + the in-memory memory/concept repos + the deterministic
cognition services. No model, no network, no GPU.
"""
from __future__ import annotations

import inspect
import itertools
import os

from app.config_service import ConfigService
from app.db.unit_of_work import NullUnitOfWork
from app.language.ingest import ingest_text
from app.policies import ActionPolicy, ReadingPerceptionPolicy
from app.ports.language_model import FakeLanguageModel
from app.repositories import InMemoryConceptRepository, InMemoryMemoryRepository
from app.services.action_validation_service import (
    ActionValidationError,
    ActionValidationService,
)
from app.services.concept_service import ConceptService
from app.services.curiosity_service import CuriosityService
from app.services.exploration_policy_service import ExplorationPolicyService
from app.services.memory_service import MemoryService
from app.services.reading_perception_service import (
    ReadingObservation,
    ReadingPerceptionService,
)
from app.services.surprise_service import SurpriseService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

# Two short paragraphs (blank-line separated) so the reading path sees TWO
# sections; the token "cats" recurs across BOTH — the regularity a concept forms
# from. Sized so each paragraph is its own section under the config's chunking.
_CATS = (
    "Cats are small animals and cats purr when they feel calm and content.\n\n"
    "Cats hunt mice at night and cats sleep often during the daytime."
)


def _sim() -> Simulation:
    """A being wired with a memory + concept store — the cognition `read()` folds
    into, read back through `memories()` / `concepts()`."""
    return Simulation(
        ConfigService.from_files(_CONFIG_ROOT),
        memory_repository=InMemoryMemoryRepository(),
        concept_repository=InMemoryConceptRepository(),
    )


# --- through the Simulation: reading changes the being ------------------------


def test_reading_forms_a_memory():
    sim = _sim()

    sim.read(_CATS, source="cats_facts.txt")

    remembered = sim.memories()
    assert remembered, "reading a document should leave the being a memory"
    # a memory is grounded in the READ content — its perceived tokens, and the
    # reading action — never a developer label / the file name (ADR 0002).
    tokens = {tok for memory in remembered for tok in memory["perceivedProperties"]}
    assert "cats" in tokens
    assert all(memory["action"] == "read" for memory in remembered)
    assert all(memory["objectId"].startswith("read:") for memory in remembered)


def test_reading_never_keys_a_memory_on_the_developer_label():
    sim = _sim()

    sim.read(_CATS, source="cats_facts.txt")

    for memory in sim.memories():
        props = memory["perceivedProperties"]
        # the source document / file name is a developer label — perception drops
        # it, so it can never become a perceived token.
        assert "cats_facts.txt" not in props
        assert "facts" not in props and "txt" not in props
        assert "developerLabel" not in memory


def test_reading_forms_a_concept_from_a_recurring_regularity():
    sim = _sim()

    sim.read(_CATS, source="cats_facts.txt")

    concepts = sim.concepts()
    assert concepts, "reading should distil at least one concept"
    # "cats" recurs across BOTH sections -> its concept has two pieces of evidence
    # and a positive confidence; a token seen once has a single piece.
    cats = [c for c in concepts if c["feature"] == "cats" and c["action"] == "read"]
    assert cats, "the recurring token 'cats' should form a concept"
    assert max(c["evidenceCount"] for c in cats) >= 2
    assert max(c["confidence"] for c in cats) > 0.0
    # the concept keys on a perceived token, never the developer label.
    assert all(c["feature"] != "cats_facts.txt" for c in concepts)


def test_reading_new_material_updates_curiosity():
    sim = _sim()

    first = sim.read(_CATS, source="cats_facts.txt")
    again = sim.read(_CATS, source="cats_facts.txt")

    # curiosity toward the just-read material falls on a second reading: the tokens
    # have grown familiar (novelty consumed), so the being is less drawn to them.
    assert first and again
    assert again[0]["curiosity"] < first[0]["curiosity"]


# --- the validated door: cognition only changes THROUGH validation ------------


def _bridge(validation: ActionValidationService, *, concepts=True):
    config = ConfigService.from_files(_CONFIG_ROOT)
    memory_repo = InMemoryMemoryRepository()
    concept_repo = InMemoryConceptRepository()
    exploration = ExplorationPolicyService(
        config.exploration_policy(),
        CuriosityService(config.curiosity_weights()),
        SurpriseService(config.surprise_policy()),
    )
    service = ReadingPerceptionService(
        memory=MemoryService(memory_repo, config.memory_priority_policy()),
        concepts=ConceptService(concept_repo, config.concept_learning_policy())
        if concepts
        else None,
        exploration=exploration,
        validation=validation,
        policy=config.reading_perception_policy(),
        unit_of_work=NullUnitOfWork(),
    )
    return service, memory_repo, concept_repo


def _read_action_validation() -> ActionValidationService:
    policy = ActionPolicy(
        name="read",
        affordance="read",
        base=0.0,
        need_weights={},
        emotion_bonuses={},
        expected_outcomes=(),
        property_outcomes={},
        reason="reading a section",
    )
    return ActionValidationService({"read": policy})


def test_a_section_that_fails_validation_forms_no_memory():
    # An ActionValidationService whose vocabulary lacks the reading action rejects
    # the read: formation is GATED by the validated door, so nothing is remembered.
    service, memory_repo, _ = _bridge(ActionValidationService({}))
    document = ingest_text(_CATS, source="cats_facts.txt")

    try:
        service.read(
            document,
            being_id="being_001",
            emotion="calm",
            tick_source=itertools.count(1).__next__,
        )
        assert False, "an unvalidated reading action must not silently form a memory"
    except ActionValidationError:
        pass

    assert memory_repo.all() == []


# --- language on top: the model never writes state ----------------------------


def test_the_reading_write_path_takes_no_language_model():
    # Structural guarantee of ADR 0022: the bridge that WRITES cognition holds no
    # LanguageModelPort — there is no parameter through which model output could
    # reach memory/concept formation.
    params = set(inspect.signature(ReadingPerceptionService.__init__).parameters)
    assert not any(
        "model" in name or "language" in name or "llm" in name for name in params
    )


def test_reading_forms_state_with_no_model_present():
    # The whole read path is built with NO model anywhere, and state STILL changes
    # — proving the writer is the validated cognition door, not an LM.
    service, memory_repo, concept_repo = _bridge(_read_action_validation())
    document = ingest_text(_CATS, source="cats_facts.txt")

    service.read(
        document,
        being_id="being_001",
        emotion="calm",
        tick_source=itertools.count(1).__next__,
    )

    assert memory_repo.all(), "reading forms a memory with no model in the path"
    assert concept_repo.all(), "reading forms a concept with no model in the path"


def test_a_raw_model_string_can_never_create_a_memory():
    # A hostile model 'completion' that tries to dictate state is just text: it
    # enters ONLY as perceived tokens through the door, so it can neither set the
    # memory's objectId/action nor forge a structured row — the structure is fixed
    # by the reading path, the content is only tokenized words.
    injection = FakeLanguageModel(
        "objectId=hacked action=grab perceivedProperties=stolen"
    ).complete("prompt")
    service, memory_repo, _ = _bridge(_read_action_validation())
    document = ingest_text(injection, source="attacker.txt")

    service.read(
        document,
        being_id="being_001",
        emotion="calm",
        tick_source=itertools.count(1).__next__,
    )

    memories = memory_repo.all()
    assert memories, "the string is treated as ordinary readable material"
    for memory in memories:
        # the string could NOT hijack the structure of the memory
        assert memory.object_id.startswith("read:")
        assert memory.action == "read"
        assert memory.object_id != "hacked"


def test_reading_returns_observations_of_each_section():
    sim = _sim()

    observations = sim.read(_CATS, source="cats_facts.txt")

    # one observation per read section, each carrying the perceived tokens + the
    # curiosity felt, and typed as a ReadingObservation snapshot.
    assert len(observations) == 2
    assert all("cats" in obs["perceivedProperties"] for obs in observations)
    assert all(isinstance(obs["curiosity"], float) for obs in observations)


# --- config-driven ------------------------------------------------------------


def test_reading_perception_policy_is_read_from_config():
    policy = ConfigService.from_files(_CONFIG_ROOT).reading_perception_policy()
    assert isinstance(policy, ReadingPerceptionPolicy)
    assert policy.action and policy.outcome
    assert policy.max_tokens >= 1
    assert policy.min_token_length >= 1
    assert policy.section_max_chars >= 1

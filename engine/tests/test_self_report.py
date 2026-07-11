"""Behaviors of the SELF-REPORT surface (S1, ADR 0032): ask the being what it
has done and it answers, grounded ONLY in its own logged memories.

The report is built by the deterministic template narrator (a `LanguageModelPort`
implementation, fully offline) rendering the structured `Memory` fields into
plain first-person sentences. Two invariants are load-bearing and pinned here:

- GROUNDING: the report uses only what the being logged — it never invents an
  object, property, outcome, or feeling it has no memory of.
- PERCEPTION, NOT LABELS: the being names objects by their PERCEIVED properties
  ("the round red thing"), never the developer's private label or the internal
  object id (ADR 0002).

Language sits on TOP and mutates nothing (ADR 0022): a report reads snapshot
dicts and leaves the being exactly as it was. `/ask` runs behind the always-on
JWT guard (ADR 0005), mirrored on the auth suite's contract.
"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.adapters.template_language_model import TemplateLanguageModel
from app.config_service import ConfigService
from app.main import create_app
from app.repositories import InMemoryMemoryRepository
from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService
from app.services.self_report_service import SelfReportService
from app.simulation import Simulation

_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

_QUERY = "what have you done recently?"


def _config() -> ConfigService:
    return ConfigService.from_files(_CONFIG_ROOT)


def _self_report(config: ConfigService) -> SelfReportService:
    policy = config.self_report_policy()
    narrator = TemplateLanguageModel(
        phrasing=config.narration_phrasing(),
        salience_emphasis_threshold=policy.salience_emphasis_threshold,
        neutral_emotion=config.default_emotion(),
    )
    return SelfReportService(
        MemorySummaryService(narrator),
        NarrationService(narrator),
        recent_count=policy.recent_count,
    )


def _lived_being(object_id: str = "obj_hot_lamp", *, ticks: int = 6) -> Simulation:
    config = _config().with_room_contents([object_id])
    sim = Simulation(config, memory_repository=InMemoryMemoryRepository())
    for _ in range(ticks):
        sim.tick()
    return sim


# --- the grounded self-report -----------------------------------------------


def test_being_reports_a_recent_experience():
    sim = _lived_being("obj_red_ball", ticks=6)
    assert sim.memories(), "the being should have lived something to report"

    report = _self_report(_config()).report(
        _QUERY, memories=sim.memories(), state=sim.state()
    )

    assert isinstance(report, str) and report.strip()
    # first-person, grounded in a perceived property of the ball it acted on
    assert "I " in report
    assert "round" in report
    # names an action it actually took, phrased in plain words
    assert any(
        verb in report
        for verb in ("looked", "moved", "pushed", "touched", "backed", "grabbed", "dropped")
    )


def test_self_report_uses_only_logged_memories():
    # A hand-built log with exactly ONE perceived property set and ONE outcome:
    # everything the being says must trace back to it — nothing invented.
    memories = [
        {
            "objectId": "obj_x",
            "action": "push",
            "perceivedProperties": ["round", "red"],
            "observedOutcome": ["rolls"],
            "emotionAfter": "calm",
            "priority": 0.0,
        }
    ]

    report = _self_report(_config()).report(_QUERY, memories=memories, state={})

    # what it logged, it says:
    assert "round" in report and "red" in report
    # what it never logged, it never says (no invented properties/outcomes):
    for not_logged in ("hot", "square", "blue", "bounced", "hurt", "frightened"):
        assert not_logged not in report


def test_report_names_perceived_properties_not_developer_label():
    # obj_red_ball's developerLabel is "Red Ball" — the being must never use it,
    # nor the internal object id; it knows the thing only as it perceived it.
    sim = _lived_being("obj_red_ball", ticks=6)

    report = _self_report(_config()).report(
        _QUERY, memories=sim.memories(), state=sim.state()
    )

    assert "round" in report or "red" in report  # perceived properties
    assert "Red Ball" not in report  # never the developer label (ADR 0002)
    assert "obj_red_ball" not in report  # never the internal id


def test_a_self_report_leaves_the_being_unchanged():
    # Narration sits on top and controls nothing (ADR 0022): asking leaves both
    # the being's state and its memory log exactly as they were.
    sim = _lived_being("obj_hot_lamp", ticks=8)
    state_before = sim.state()
    memories_before = sim.memories()

    _self_report(_config()).report(
        _QUERY, memories=sim.memories(), state=sim.state()
    )

    assert sim.state() == state_before
    assert sim.memories() == memories_before


def test_a_being_with_no_experience_falls_back_to_the_present():
    # Nothing logged yet: the report still answers, grounded in the present
    # state (NarrationService), never inventing a past.
    report = _self_report(_config()).report(
        _QUERY,
        memories=[],
        state={"emotion": "calm", "perceived": {"objects": []}},
    )

    assert isinstance(report, str) and report.strip()


# --- POST /ask: behind the always-on JWT guard (ADR 0005) --------------------


class _RememberingSim:
    """A being at the Simulation seam with just the read-backs /ask needs, so the
    auth/transport contract is exercised without config or psychology."""

    def memories(self) -> list:
        return [
            {
                "objectId": "obj_red_ball",
                "action": "push",
                "perceivedProperties": ["round", "red"],
                "observedOutcome": ["rolls"],
                "emotionAfter": "calm",
                "priority": 0.0,
            }
        ]

    def state(self) -> dict:
        return {"emotion": "calm", "perceived": {"objects": []}}


def _client() -> TestClient:
    return TestClient(create_app(simulation=_RememberingSim(), tick_interval_seconds=0))


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_ask_without_a_token_is_rejected():
    resp = _client().post("/ask", json={"query": _QUERY})

    assert resp.status_code == 401


def test_ask_with_a_bad_token_is_rejected():
    resp = _client().post("/ask", json={"query": _QUERY}, headers=_bearer("not-a-real-token"))

    assert resp.status_code == 401


def test_ask_with_a_valid_token_returns_a_grounded_report(mint):
    resp = _client().post("/ask", json={"query": _QUERY}, headers=_bearer(mint()))

    assert resp.status_code == 200
    body = resp.json()
    assert body["report"].strip()
    assert "round" in body["report"]  # grounded in a real perceived property

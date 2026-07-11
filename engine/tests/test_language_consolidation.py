"""Behavior: the being CONSOLIDATES what it has read into its own weights on its
'sleep' cycle (reading R5, ADR 0041).

When the being's `sleep` need crosses the configured threshold, an ASYNC
consolidation is TRIGGERED (enqueued on an executor) and never blocks `tick()`.
The consolidation job synthesizes Q/A pairs FROM the accumulated knowledge store
via a LanguageModelPort (a Fake here; Claude at build/host time), then reuses R1's
gated LoRA fine-tune + R2's serve. Offline: pair synthesis + the sleep trigger +
the async enqueue are genuinely built and tested; the MLX fine-tune itself is
GATED (skipped) off the Mac host, where it refuses LOUDLY.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config_service import ConfigService
from app.language import consolidation
from app.language.consolidation import (
    ConsolidationScheduler,
    run_consolidation,
    synthesize_consolidation_pairs,
)
from app.language.embedding import HashingEmbedder
from app.language.ingest import ingest_text
from app.language.knowledge_store import KnowledgeStore, index_document
from app.db.unit_of_work import NullUnitOfWork
from app.policies import ConsolidationPolicy
from app.ports.language_model import FakeLanguageModel
from app.ports.retrieval import Chunk
from app.repositories import InMemoryKnowledgeChunkRepository
from app.simulation import Simulation

_FIXED_TIME = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)


class _RecordingExecutor:
    """A JobExecutor that RECORDS submitted jobs without running them — so a test
    can prove a consolidation was ENQUEUED (non-blocking) without a real training
    run ever firing on the tick thread."""

    def __init__(self):
        self.jobs = []

    def submit(self, job):
        self.jobs.append(job)
        return None


def _fast_sleep_config():
    """A being whose `sleep` need drifts up fast, so a single tick crosses the
    consolidation threshold — the sleep cycle, on demand."""
    tick_rates = {
        "tick": {"duration_ms": 1000},
        "needs": {
            "sleep": {"direction": "increase", "amount": 50, "every_ticks": 1,
                      "min": 0, "max": 100, "start": 30},
        },
    }
    return ConfigService.from_dict(tick_rates, {"rules": [], "default": "calm"})


# --- config accessor -----------------------------------------------------------

def test_consolidation_policy_reads_the_configured_values():
    cfg = ConfigService.from_dict(
        tick_rates={}, emotions={},
        language={"consolidation": {
            "enabled": True, "sleep_threshold": 75, "pair_count": 8, "source": "sleep",
        }},
    )
    policy = cfg.consolidation_policy()
    assert policy.enabled is True
    assert policy.sleep_threshold == 75
    assert policy.pair_count == 8
    assert policy.source == "sleep"


def test_consolidation_policy_defaults_to_disabled():
    policy = ConfigService.from_dict(tick_rates={}, emotions={}).consolidation_policy()
    assert policy.enabled is False        # shipped default OFF -> byte-identical tick
    assert policy.sleep_threshold == 80   # aligns with the `sleepy` emotion threshold


def test_shipped_consolidation_config_is_disabled_by_default():
    import os

    root = os.path.join(os.path.dirname(__file__), "..", "..", "config")
    assert ConfigService.from_files(root).consolidation_policy().enabled is False


# --- pair synthesis (Fake model, deterministic, offline) -----------------------

def test_pairs_are_synthesized_from_the_accumulated_knowledge_store_chunks():
    repo = InMemoryKnowledgeChunkRepository()
    store = KnowledgeStore(
        embedder=HashingEmbedder(dim=64), repository=repo, unit_of_work=NullUnitOfWork()
    )
    index_document(
        ingest_text("Cats purr when content. Cats hunt small prey at night.",
                    source="cats.txt", max_chars=30, overlap=5),
        store,
    )
    chunks = repo.all()
    assert chunks, "the store accumulated read chunks to consolidate"

    model = FakeLanguageModel(reply=lambda prompt: "Q: about it?\nA: recalled")
    pairs = synthesize_consolidation_pairs(chunks, model, ConsolidationPolicy(pair_count=50))

    assert len(pairs) == len(chunks)                       # one pair per accumulated chunk
    for chunk in chunks:                                    # each pair was built FROM a store chunk
        assert any(chunk.text in prompt for prompt in model.prompts)
    assert all(pair.text == "Q: about it?\nA: recalled" for pair in pairs)  # deterministic


def test_pair_count_caps_the_number_of_pairs_synthesized():
    chunks = [Chunk(text=f"fact number {i}", source="s") for i in range(5)]
    model = FakeLanguageModel(reply="Q: q?\nA: a.")
    pairs = synthesize_consolidation_pairs(chunks, model, ConsolidationPolicy(pair_count=2))
    assert len(pairs) == 2


# --- the sleep -> async consolidation trigger ----------------------------------

def test_a_rising_sleep_edge_enqueues_one_job_without_running_it():
    executor = _RecordingExecutor()
    ran = []
    scheduler = ConsolidationScheduler(
        policy=ConsolidationPolicy(enabled=True, sleep_threshold=80),
        executor=executor,
        job=lambda: ran.append("ran"),
    )
    assert scheduler.maybe_consolidate(sleep_before=79, sleep_after=80) is True
    assert len(executor.jobs) == 1     # a consolidation was ENQUEUED
    assert ran == []                   # ...but not RUN by the scheduler (non-blocking)


def test_consolidation_needs_a_fresh_sleep_crossing():
    executor = _RecordingExecutor()
    scheduler = ConsolidationScheduler(
        policy=ConsolidationPolicy(enabled=True, sleep_threshold=80),
        executor=executor, job=lambda: None,
    )
    # already asleep (no new edge) and never-reached-threshold both do nothing.
    assert scheduler.maybe_consolidate(sleep_before=80, sleep_after=90) is False
    assert scheduler.maybe_consolidate(sleep_before=40, sleep_after=70) is False
    assert executor.jobs == []


def test_disabled_consolidation_never_enqueues():
    executor = _RecordingExecutor()
    scheduler = ConsolidationScheduler(
        policy=ConsolidationPolicy(enabled=False, sleep_threshold=80),
        executor=executor, job=lambda: None,
    )
    assert scheduler.maybe_consolidate(sleep_before=10, sleep_after=95) is False
    assert executor.jobs == []


# --- the sleep tick, through the public Simulation surface ---------------------

def test_a_sleep_tick_enqueues_consolidation_without_blocking_the_tick():
    executor = _RecordingExecutor()
    scheduler = ConsolidationScheduler(
        policy=ConsolidationPolicy(enabled=True, sleep_threshold=80),
        executor=executor,
        # if the scheduler ever RAN the job inline the tick would blow up here:
        job=lambda: (_ for _ in ()).throw(AssertionError("must not run on the tick thread")),
    )
    sim = Simulation(_fast_sleep_config(), consolidation=scheduler)
    assert sim.state()["needs"]["sleep"] == 30

    state = sim.tick()                       # sleep 30 -> 80 : the being falls asleep

    assert state["needs"]["sleep"] == 80     # needs drifted normally
    assert sim.current_tick == 1             # the tick returned (never blocked)
    assert len(executor.jobs) == 1           # ...having enqueued exactly one consolidation


def test_a_disabled_scheduler_leaves_the_tick_byte_identical():
    base = Simulation(_fast_sleep_config())
    executor = _RecordingExecutor()
    withq = Simulation(
        _fast_sleep_config(),
        consolidation=ConsolidationScheduler(
            policy=ConsolidationPolicy(enabled=False, sleep_threshold=80),
            executor=executor, job=lambda: None,
        ),
    )
    for _ in range(3):
        assert base.tick() == withq.tick()   # identical state across a sleep crossing
    assert executor.jobs == []               # nothing enqueued while disabled


# --- the consolidation job body: gated fine-tune + serve -----------------------

@pytest.mark.skipif(
    consolidation.mlx_available(),
    reason="MLX present — the loud-refusal path only fires when it is absent",
)
def test_consolidation_without_mlx_refuses_and_names_the_requirement(tmp_path):
    cfg = ConfigService.from_dict(tick_rates={}, emotions={})
    chunks = [Chunk(text="Cats purr when they are content.", source="cats.txt")]
    with pytest.raises(RuntimeError) as excinfo:
        run_consolidation(
            chunks=chunks,
            model=FakeLanguageModel(reply="Q: q?\nA: a."),
            policy=cfg.consolidation_policy(),
            finetune_policy=cfg.finetune_policy(),
            serve_policy=cfg.serve_policy(),
            workspace=str(tmp_path / "ws"),
            timestamp=_FIXED_TIME,
        )
    message = str(excinfo.value).lower()
    assert "mlx" in message            # names the missing toolchain
    assert "host" in message           # and that it must run on the Mac host
    assert "consolidat" in message     # and what it was trying to do


def test_consolidation_finetune_and_serve_are_host_only():
    # The genuine end-to-end consolidation LoRA pass + re-serve. It needs MLX
    # (Apple-Silicon Metal GPU) + the base-model weights + Ollama, so it is skipped
    # everywhere but a Mac host running `make consolidate`.
    pytest.importorskip("mlx_lm")
    pytest.skip(
        "requires Apple-Silicon Metal GPU + base-model weights + Ollama; "
        "run `make consolidate` on the Mac host to bake read knowledge into the weights"
    )

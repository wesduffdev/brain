"""main — the transport surface for the engine core.

A thin FastAPI app over `Simulation`. `GET /state` returns the current domain
snapshot; the WebSocket endpoint advances the being on a timer and pushes each
snapshot mapped onto the ADR-0004 `being_state_update` frame (via
`RenderStateService`); `POST /command` accepts a `player_command` validated by
`CommandService`. It owns no psychology — `/state` serializes whatever
`Simulation.state()` returns and the render/command mapping is pure, so snapshots
that later slices grow (a `perceived` block, `currentAction`, …) flow through
unchanged. Time comes in through `ClockPort` so the stream can be driven by a
real clock in production and a fake clock in tests (ADR 0003).

Run it:

    cd engine
    PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
)

from app import auth
from app.auth import AuthConfig, require_auth
from app.adapters.narrator import build_narrator
from app.language.embedding import build_embedder
from app.language.knowledge_store import KnowledgeStore, index_document
from app.language.ingest import ingest_text
from app.adapters.voice import build_voice
from app.bootstrap import BuiltSimulation, build_simulation
from app.config_service import ConfigService
from app.ports.clock import ClockPort, WallClock
from app.ports.voice import VoicePort
from app.policies import VoicePolicy
from app.repositories import (
    InMemoryConversationTurnRepository,
    InMemoryKnowledgeChunkRepository,
)
from app.services.command_service import CommandError, CommandService
from app.services.conversation_service import ConversationService
from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService
from app.services.render_state_service import RenderStateService
from app.services.self_report_service import SelfReportService
from app.services.reading_qa_service import ReadingQAService
from app.services.subject_report_service import SubjectReportService
from app.services.subject_resolver import SubjectResolver
from app.simulation import Simulation

_DEFAULT_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")

# Reading a document aloud falls back to this utterance size when no VoicePolicy is
# wired (an injected voice with no policy); the served app uses config/voice.yaml.
_DEFAULT_READ_ALOUD_MAX_CHARS = 2000
# The graceful no-op message when a host has no TTS engine — the being still
# answers in text (voice is an upgrade, not a dependency; S4, ADR 0035).
_NO_VOICE_DETAIL = (
    "voice synthesis unavailable (no TTS engine on this host); returning text only"
)


def create_app(
    *,
    simulation: Optional[Simulation] = None,
    clock: Optional[ClockPort] = None,
    tick_interval_seconds: Optional[float] = None,
    config_root: Optional[str] = None,
    auth_config: Optional[AuthConfig] = None,
    render_state_service: Optional[RenderStateService] = None,
    command_service: Optional[CommandService] = None,
    self_report_service: Optional[SelfReportService] = None,
    reading_qa_service: Optional[ReadingQAService] = None,
    conversation_service: Optional[ConversationService] = None,
    knowledge_store: Optional[KnowledgeStore] = None,
    voice: Optional[VoicePort] = None,
    voice_policy: Optional[VoicePolicy] = None,
) -> FastAPI:
    """Build the app around a being, a clock, and the render/command services.

    Everything is injectable so tests can drive a fake being and a fake clock;
    left to their defaults, the being and the render/command services are loaded
    from `config/` and the clock is the wall clock, which is what
    `uvicorn app.main:app` runs. Authentication is read from the environment
    (`AuthConfig.from_env()`) unless one is injected — it is always in the code
    path and gated only by `AUTH_REQUIRED` (ADR 0005).
    """
    # When we build the being ourselves it may own a DB session; hold the handle
    # so the lifespan can close it on shutdown. An injected simulation owns its
    # own lifecycle, so there is nothing here to tear down.
    built: Optional[BuiltSimulation] = None
    if (
        simulation is None
        or tick_interval_seconds is None
        or render_state_service is None
        or command_service is None
        or self_report_service is None
        or reading_qa_service is None
        or conversation_service is None
        or knowledge_store is None
        or voice is None
    ):
        config = ConfigService.from_files(
            config_root or os.environ.get("CONFIG_ROOT", _DEFAULT_CONFIG_ROOT)
        )
        if simulation is None:
            # The bootstrap wires the Postgres repositories + shadow-mode
            # predictor when DATABASE_URL is set, so a served engine persists its
            # interactions; with no DB it is the same plain in-memory being as
            # before (ADR 0007/0011/0012).
            built = build_simulation(config)
            simulation = built.simulation
        if tick_interval_seconds is None:
            tick_interval_seconds = config.tick_duration_ms() / 1000.0
        if render_state_service is None:
            render_state_service = RenderStateService(config.render_hints())
        if command_service is None:
            command_service = CommandService(
                config.command_specs(), config.object_catalog().keys()
            )
        if self_report_service is None:
            # The grounded self-report surface (S1, ADR 0032): a narrator behind
            # the LanguageModelPort renders the being's own memories into prose.
            self_report_service = _build_self_report(config)
        if knowledge_store is None:
            # The ONE shared knowledge store (reading R3, ADR 0038): /ingest
            # WRITES into it and reading QA + conversation READ from it, so a
            # document read at runtime is immediately answerable + citable.
            # In-memory by default (per-process; not persisted across a restart).
            knowledge_store = _build_knowledge_store(config)
        if reading_qa_service is None:
            # The reading-QA surface (reading R4, ADR 0039): grounded, cited
            # answers from the being's growing knowledge store. A fresh store is
            # empty, so a being that has read nothing declines honestly.
            reading_qa_service = _build_reading_qa(config, knowledge_store)
        if conversation_service is None:
            # The multi-turn conversation surface (reading R6): a
            # ConversationService over the SAME grounded reading QA, adding
            # history so follow-ups resolve to earlier turns. A fresh turn
            # store is empty, so the first turn has no history to lean on.
            conversation_service = _build_conversation(config, knowledge_store)
        if voice is None:
            # The voicebox (S4, ADR 0035): the VoicePort engine is selected from
            # config, and the espeak-ng adapter degrades to a no-op on a host with
            # no binary (voice is an upgrade, not a dependency).
            voice = build_voice(config)
        if voice_policy is None:
            voice_policy = config.voice_policy()

    clock = clock if clock is not None else WallClock()
    auth_config = auth_config if auth_config is not None else AuthConfig.from_env()
    guard = require_auth(auth_config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Close the being's DB session on shutdown when the bootstrap opened one,
        # so the server never leaves a session idle-in-transaction on exit.
        try:
            yield
        finally:
            if built is not None:
                built.close()

    app = FastAPI(title="jarvis engine", version="0", lifespan=lifespan)

    @app.get("/health")
    async def health():
        # Public liveness probe (Docker/uptime): no token required.
        return {"status": "ok"}

    @app.get("/state", dependencies=[Depends(guard)])
    async def get_state():
        # Return the domain snapshot as-is; FastAPI serializes the whole dict, so
        # no field list is hard-coded here. Protected: the guard runs first.
        return simulation.state()

    @app.post("/command", dependencies=[Depends(guard)])
    async def post_command(command: dict = Body(...)):
        # Receive a `player_command` and let CommandService validate it against
        # the known command set and targets (ADR 0004); reject unknown/malformed
        # with 422. Protected by the same guard as /state.
        try:
            accepted = command_service.validate(command)
        except CommandError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "status": "accepted",
            "command": accepted.command,
            "targetId": accepted.target_id,
        }

    @app.post("/ask", dependencies=[Depends(guard)])
    async def post_ask(payload: dict = Body(...)):
        # Answer a natural-language question about the being's own experience,
        # grounded ONLY in its logged memories (S1, ADR 0032). Read-only: the
        # self-report reads snapshot dicts and mutates nothing (ADR 0022).
        # Protected by the same always-on JWT guard as /state (ADR 0005).
        query = str(payload.get("query", ""))
        report = self_report_service.report(
            query,
            memories=simulation.memories(),
            state=simulation.state(),
            concepts=_readback(simulation, "concepts"),
            beliefs=_readback(simulation, "beliefs"),
            explanations=_readback(simulation, "explanations"),
        )
        return {"query": query, "report": report}

    @app.post("/ask/reading", dependencies=[Depends(guard)])
    async def post_ask_reading(payload: dict = Body(...)):
        # Answer a natural-language question about what the being has READ,
        # grounded in the retrieved passages and CITING the source document; an
        # unread topic is declined honestly (reading R4, ADR 0039). Read-only:
        # touches the knowledge store + the model, never the being (ADR 0022).
        # Behind the same always-on JWT guard as /state (ADR 0005).
        query = str(payload.get("query", ""))
        answer = reading_qa_service.answer(query)
        if payload.get("speak"):
            # Speak the grounded reading answer ALOUD through the SAME VoicePort
            # (reading R8): typed question -> text + spoken answer. Without `speak`
            # the text response is byte-for-byte unchanged.
            return _voice_or_body(
                voice,
                voice_policy,
                text=answer,
                emotion=str(simulation.state().get("emotion", "")),
                silent_body={
                    "spoken": False,
                    "query": query,
                    "answer": answer,
                    "detail": _NO_VOICE_DETAIL,
                },
            )
        return {"query": query, "answer": answer}

    @app.post("/chat", dependencies=[Depends(guard)])
    async def post_chat(payload: dict = Body(...)):
        # Hold a MULTI-TURN grounded conversation about what the being has READ
        # (reading R6): each turn stays grounded in the retrieved passages and CITES
        # its source (reusing reading QA), and a follow-up ("tell me more about that")
        # resolves to earlier turns; a new unread topic is still declined honestly.
        # Read-only: touches the knowledge + turn stores, never the being (ADR 0022),
        # behind the same always-on JWT guard as /state (ADR 0005).
        conversation_id = str(payload.get("conversationId", "default"))
        message = str(payload.get("message", ""))
        answer = conversation_service.reply(conversation_id, message)
        if payload.get("speak"):
            # Speak the grounded conversational answer ALOUD through the SAME
            # VoicePort (reading R8); without `speak` the text response is unchanged.
            return _voice_or_body(
                voice,
                voice_policy,
                text=answer,
                emotion=str(simulation.state().get("emotion", "")),
                silent_body={
                    "spoken": False,
                    "conversationId": conversation_id,
                    "message": message,
                    "answer": answer,
                    "detail": _NO_VOICE_DETAIL,
                },
            )
        return {"conversationId": conversation_id, "message": message, "answer": answer}

    @app.post("/speak", dependencies=[Depends(guard)])
    async def post_speak(payload: dict = Body(...)):
        # Voice the being's grounded self-report ALOUD (S4, ADR 0035): the SAME
        # report /ask returns, rendered to audio by the VoicePort. Read-only like
        # /ask (ADR 0022), behind the same always-on JWT guard (ADR 0005), and the
        # voice tracks the being's current emotion (rate/pitch from config). When no
        # TTS engine is on this host the voice is a no-op — still 200, with the text,
        # so the being is never left mute (voice is an upgrade, not a dependency).
        query = str(payload.get("query", ""))
        state = simulation.state()
        report = self_report_service.report(
            query, memories=simulation.memories(), state=state
        )
        return _voice_or_body(
            voice,
            voice_policy,
            text=report,
            emotion=str(state.get("emotion", "")),
            silent_body={
                "spoken": False,
                "query": query,
                "report": report,
                "detail": _NO_VOICE_DETAIL,
            },
        )

    @app.post("/read", dependencies=[Depends(guard)])
    async def post_read(payload: dict = Body(...)):
        # Voice a PROVIDED document ALOUD (reading R8, reuses S4's VoicePort, ADR
        # 0035): the text is cleaned + chunked into sensible utterances (reusing the
        # R1 ingest) and each is rendered to audio by the same VoicePort /speak uses,
        # in the being's current emotion's voice. Read-only (ADR 0022): reading aloud
        # never advances or mutates the being. Behind the always-on JWT guard (ADR
        # 0005). No TTS engine on this host -> 200 with the text, so the document is
        # never left unread (voice is an upgrade, not a dependency).
        text = str(payload.get("text", ""))
        if not text.strip():
            raise HTTPException(status_code=422, detail="no document text to read aloud")
        source = str(payload.get("source") or "document")
        emotion = str(simulation.state().get("emotion", ""))
        return _voice_document(
            voice, voice_policy, text=text, source=source, emotion=emotion
        )

    @app.post("/ingest", dependencies=[Depends(guard)])
    async def post_ingest(payload: dict = Body(...)):
        # Let the being READ a PROVIDED document at runtime (INGEST-ENDPOINT). One
        # call, two validated paths: (a) INDEX the cleaned + chunked text into the
        # SHARED knowledge store (R3, ADR 0038) so /ask/reading + /chat then answer
        # about it GROUNDED + CITED (R4/R6, ADR 0039); and (b) route it through the
        # VALIDATED reading-as-perception door (R7, ADR 0040) via Simulation.read,
        # so memories/concepts form -- the language model NEVER writes state (ADR
        # 0022). Mirrors /read's 422-on-empty. Behind the always-on JWT guard (ADR
        # 0005). The store is in-memory (per-process), so an ingest is not persisted
        # across a restart.
        text = str(payload.get("text", ""))
        if not text.strip():
            raise HTTPException(status_code=422, detail="no document text to ingest")
        source = str(payload.get("source") or "document")
        # (a) index into the shared knowledge store (grounded, cited retrieval).
        chunks = index_document(ingest_text(text, source=source), knowledge_store)
        # (b) read through the validated perception/cognition door (memories/concepts).
        perceived = simulation.read(text, source=source)
        return {"source": source, "chunks": chunks, "perceived": len(perceived)}

    @app.websocket("/ws")
    async def stream(websocket: WebSocket):
        # Verify the handshake token (query `?token=` or the Authorization
        # header) before streaming; a bad token is closed with policy code 1008.
        token = websocket.query_params.get("token") or auth.bearer_token(
            websocket.headers.get("authorization")
        )
        await websocket.accept()
        try:
            auth.authenticate_ws(auth_config, token)
        except auth.AuthError:
            await websocket.close(code=1008)
            return
        try:
            while True:
                # Map the domain snapshot onto the ADR-0004 render frame before
                # it crosses the wire; the renderer sees `being_state_update`.
                frame = render_state_service.render(simulation.tick())
                await websocket.send_json(frame)
                await clock.sleep(tick_interval_seconds)
        except WebSocketDisconnect:
            return

    return app


def _voice_or_body(voice, voice_policy, *, text, emotion, silent_body):
    """Render `text` through the being's VoicePort in its current `emotion`'s voice
    and return the WAV audio — the mechanism S4's /speak established, reused here by
    /read and the spoken-answer surfaces. When no TTS engine is on this host the
    voice is a graceful no-op: return `silent_body` (200, text only) so the being is
    never left mute (voice is an upgrade, not a dependency; ADR 0035)."""
    params = voice_policy.params_for(emotion) if voice_policy is not None else None
    audio = voice.synthesize(text, params)
    if audio is None:
        return silent_body
    return Response(content=audio, media_type="audio/wav")


def _voice_document(voice, voice_policy, *, text, source, emotion):
    """Read a whole document aloud (reading R8): clean + chunk it into utterances
    (reusing R1's `ingest` at the config-driven read-aloud size, no overlap so no
    words repeat) and voice each through the SAME VoicePort, concatenating the audio.
    With no TTS engine every utterance is a no-op, so return the cleaned text (200)
    and the utterance count — the document is never left unread."""
    max_chars = (
        voice_policy.read_aloud_max_chars
        if voice_policy is not None
        else _DEFAULT_READ_ALOUD_MAX_CHARS
    )
    document = ingest_text(text, source=source, max_chars=max_chars, overlap=0)
    params = voice_policy.params_for(emotion) if voice_policy is not None else None
    audio = b"".join(
        part
        for part in (voice.synthesize(chunk, params) for chunk in document.chunks)
        if part
    )
    if not audio:
        return {
            "spoken": False,
            "source": document.source,
            "text": document.text,
            "utterances": len(document.chunks),
            "detail": _NO_VOICE_DETAIL,
        }
    return Response(content=audio, media_type="audio/wav")


def _build_self_report(config: ConfigService) -> SelfReportService:
    """Wire the self-report surface from config (S1/S2, ADR 0032). The narrator that
    backs the shared `LanguageModelPort` is provider-selected by `narrator.kind`
    (deterministic template by default; fake / claude / local otherwise) and, for a
    real model, made FALLBACK-SAFE — a model that errors or is unavailable degrades
    to the grounded deterministic template. `build_narrator` owns that selection +
    fallback; the deterministic default path is byte-identical to S1 and the suite
    never reaches a real provider (env-gated, ADR 0022)."""
    policy = config.self_report_policy()
    narrator = build_narrator(config)
    subject = SubjectReportService(
        narrator,
        SubjectResolver(config.object_property_vocab()),
        policy=config.subject_query_policy(),
    )
    return SelfReportService(
        MemorySummaryService(narrator),
        NarrationService(narrator),
        recent_count=policy.recent_count,
        subject=subject,
    )


def _build_knowledge_store(config: ConfigService) -> KnowledgeStore:
    """The being's growing knowledge store (reading R3, ADR 0038): the config-
    selected embedder over an in-memory chunk repository. ONE instance is built in
    `create_app` and SHARED by /ingest (writes) and reading QA + conversation
    (reads), so a document read at runtime is immediately answerable + citable.
    In-memory = per-process: not persisted across a restart (a durable store is a
    repository swap behind the same seam, ADR 0038)."""
    return KnowledgeStore(
        embedder=build_embedder(config.knowledge_retrieval_policy()),
        repository=InMemoryKnowledgeChunkRepository(),
    )


def _build_reading_qa(config: ConfigService, store: KnowledgeStore) -> ReadingQAService:
    """Wire the reading-QA surface from config (reading R4, ADR 0039). The being
    retrieves from its growing knowledge store (the R3 `KnowledgeStore` over the
    config-selected embedder; in-memory by default — a fresh being has read
    nothing, so it honestly declines until documents are ingested). A grounded
    answer is phrased by a GENERATIVE narrator when one is configured
    (`narrator.kind` == fake/claude/local, reusing `build_narrator`); with the
    offline template default there is no generative model, so the answer is
    EXTRACTIVE — it quotes what it read — and grounding + citation hold with no
    model call. Read-only throughout (ADR 0022)."""
    kind = config.self_report_policy().narrator_kind
    model = None if kind in ("deterministic", "template") else build_narrator(config)
    return ReadingQAService(store, model=model, policy=config.reading_qa_policy())


def _build_conversation(config: ConfigService, store: KnowledgeStore) -> ConversationService:
    """Wire the multi-turn conversation surface from config (reading R6, extends ADR
    0039). It reuses `_build_reading_qa` for the grounded, cited single-turn answer
    (so citation + unread-honesty carry over unchanged) and adds an in-memory
    conversation-turn store plus the `conversation_policy` tuning (history window +
    follow-up cues). A served engine with a DB would hand it the Postgres turn
    repository + a real unit of work instead (ADR 0017); the default here is the
    offline in-memory store, so a fresh being converses with no database. Read-only
    throughout (ADR 0022)."""
    return ConversationService(
        _build_reading_qa(config, store),
        InMemoryConversationTurnRepository(),
        policy=config.conversation_policy(),
    )


def _readback(simulation, name: str):
    """A `Simulation` read-back (`concepts`/`beliefs`/`explanations`) if the being
    exposes it, else an empty list — so a subject query works over a real being and
    a duck-typed fake alike, degrading (never erroring) when a seam is absent."""
    accessor = getattr(simulation, name, None)
    return accessor() if callable(accessor) else []


app = create_app()

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
from app.adapters.voice import build_voice
from app.bootstrap import BuiltSimulation, build_simulation
from app.config_service import ConfigService
from app.ports.clock import ClockPort, WallClock
from app.ports.voice import VoicePort
from app.policies import VoicePolicy
from app.services.command_service import CommandError, CommandService
from app.services.memory_summary_service import MemorySummaryService
from app.services.narration_service import NarrationService
from app.services.render_state_service import RenderStateService
from app.services.self_report_service import SelfReportService
from app.services.subject_report_service import SubjectReportService
from app.services.subject_resolver import SubjectResolver
from app.simulation import Simulation

_DEFAULT_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


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
    voice: Optional[VoicePort] = None,
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
    voice_policy: Optional[VoicePolicy] = None
    if (
        simulation is None
        or tick_interval_seconds is None
        or render_state_service is None
        or command_service is None
        or self_report_service is None
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
        if voice is None:
            # The voicebox (S4, ADR 0035): the VoicePort engine is selected from
            # config, and the espeak-ng adapter degrades to a no-op on a host with
            # no binary (voice is an upgrade, not a dependency).
            voice = build_voice(config)
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
        params = (
            voice_policy.params_for(str(state.get("emotion", "")))
            if voice_policy is not None
            else None
        )
        audio = voice.synthesize(report, params)
        if audio is None:
            return {
                "spoken": False,
                "query": query,
                "report": report,
                "detail": "voice synthesis unavailable (no TTS engine on this host); "
                "returning text only",
            }
        return Response(content=audio, media_type="audio/wav")

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


def _readback(simulation, name: str):
    """A `Simulation` read-back (`concepts`/`beliefs`/`explanations`) if the being
    exposes it, else an empty list — so a subject query works over a real being and
    a duck-typed fake alike, degrading (never erroring) when a seam is absent."""
    accessor = getattr(simulation, name, None)
    return accessor() if callable(accessor) else []


app = create_app()

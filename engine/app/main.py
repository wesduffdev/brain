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

from fastapi import Body, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from app import auth
from app.auth import AuthConfig, require_auth
from app.bootstrap import BuiltSimulation, build_simulation
from app.config_service import ConfigService
from app.ports.clock import ClockPort, WallClock
from app.services.command_service import CommandError, CommandService
from app.services.render_state_service import RenderStateService
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


app = create_app()

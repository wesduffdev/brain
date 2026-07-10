"""main — the transport surface for the engine core.

A thin FastAPI app over `Simulation`: `GET /state` returns the current snapshot
and a WebSocket endpoint advances the being on a timer and pushes each frame.
It owns no psychology — it serializes whatever `Simulation.state()` returns, so
snapshots that later slices grow (a `perceived` block, `currentAction`, …) flow
through unchanged. Time comes in through `ClockPort` so the stream can be driven
by a real clock in production and a fake clock in tests (ADR 0003).

Run it:

    cd engine
    PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.config_service import ConfigService
from app.ports.clock import ClockPort, WallClock
from app.simulation import Simulation

_DEFAULT_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def create_app(
    *,
    simulation: Optional[Simulation] = None,
    clock: Optional[ClockPort] = None,
    tick_interval_seconds: Optional[float] = None,
    config_root: Optional[str] = None,
) -> FastAPI:
    """Build the app around a being and a clock.

    Everything is injectable so tests can drive a fake being and a fake clock;
    left to their defaults, the being is loaded from `config/` and the clock is
    the wall clock, which is what `uvicorn app.main:app` runs.
    """
    if simulation is None or tick_interval_seconds is None:
        config = ConfigService.from_files(
            config_root or os.environ.get("CONFIG_ROOT", _DEFAULT_CONFIG_ROOT)
        )
        if simulation is None:
            simulation = Simulation(config)
        if tick_interval_seconds is None:
            tick_interval_seconds = config.tick_duration_ms() / 1000.0

    clock = clock if clock is not None else WallClock()

    app = FastAPI(title="jarvis engine", version="0")

    @app.get("/state")
    async def get_state():
        # Return the snapshot as-is; FastAPI serializes the whole dict, so no
        # field list is hard-coded here.
        return simulation.state()

    @app.websocket("/ws")
    async def stream(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                frame = simulation.tick()
                await websocket.send_json(frame)
                await clock.sleep(tick_interval_seconds)
        except WebSocketDisconnect:
            return

    return app


app = create_app()

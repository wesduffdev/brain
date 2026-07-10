# 0003 — FastAPI/WebSocket transport and an injectable clock seam

## Status

Accepted

## Date

2026-07-10

## Context

The engine core (ADR 0001) is pure Python behind `Simulation.tick()` /
`Simulation.state()`. To become observable outside a demo script — and to feed
the PixiJS renderer over the wire (BRIEF §5, §14) — it needs a transport: a way
to read the current snapshot and to receive a frame every tick as the being
runs.

Two forces shape the design:

- **The snapshot will grow.** Later slices add a `perceived` block (V0-2),
  `currentAction` (V0-4), and eventually the full render contract (V0-10). The
  transport must not encode today's field list, or every one of those slices
  would have to edit it.
- **A tick loop needs real time, and tests must not wait on it.** A live stream
  paces itself on the wall clock; a test that asserts "N frames over N ticks"
  cannot afford to sleep, and needs the stream to be deterministic. ADR 0001
  explicitly deferred the clock port until the real loop landed and something
  varied across it. It now does: wall-clock time vs. a controllable test clock.

## Decision

Add a thin transport module, `engine/app/main.py`, and one seam,
`engine/app/ports/clock.py`.

- **`create_app(...)` builds a FastAPI app** over a single `Simulation`:
  - `GET /state` returns `Simulation.state()` **verbatim** — the dict is handed
    straight to FastAPI, which serializes all of it. No field list lives in the
    transport, so snapshots grown by later slices flow through unchanged.
  - A **WebSocket endpoint `/ws`** accepts the connection, then loops:
    `tick()` the being, `send_json` the fresh `state()` frame, and `await`
    the clock between frames. It owns no psychology and makes no render
    decisions (BRIEF §17) — it moves snapshots, nothing more.
  - The being, the clock, the tick interval, and the config root are all
    **injectable** with production defaults, so the same factory serves
    `uvicorn app.main:app` and the tests.

- **`ClockPort`** is a `Protocol` with a single `async sleep(seconds)`.
  `WallClock` (production) awaits `asyncio.sleep`; tests inject a fake clock
  that lets no real time pass and bounds the stream to a deterministic number of
  frames. This is the first port in the codebase, added under the deep-module
  rule only now that something genuinely varies across it.

`fastapi` and `uvicorn[standard]` move into the active requirements; `httpx` is
added as a test-only dependency for `fastapi.testclient.TestClient`.

## Consequences

- The engine is observable over HTTP/WS: `curl /state` returns the snapshot and
  a WebSocket client sees one frame per tick. This is the surface the renderer
  (V0-11) and the render-state contract (V0-10) build on.
- Because `/state` and `/ws` serialize whatever `state()` returns, V0-2 and V0-4
  can grow the snapshot with **no transport change** — the coordination hotspot
  the execution plan flags is handled generically rather than by edits here.
- Time is testable: the WS stream is exercised end-to-end with zero real
  sleeping, and retiming the loop is a matter of the injected interval, not a
  code change to the loop.
- The clock seam is deliberately minimal (one `sleep`). If a later slice needs
  wall-clock timestamps or scheduling, it extends `ClockPort` — it does not
  reach around it.
- One shared `Simulation` backs both endpoints in the module-level `app`; the
  v0 being is single, so this is intentional. Multi-being or per-connection
  isolation, if ever needed, is a later decision.

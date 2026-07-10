# 0010 — Renderer authentication: a server-minted service token via env (no login in v0)

## Status

Accepted

## Date

2026-07-10

## Context

The engine's API is always-on JWT auth (ADR 0005): `/ws` verifies a handshake
token and `POST /command` requires a bearer token; only `GET /health` is public.
The V0-11 PixiJS renderer must therefore present a valid JWT to stream frames and
to send a `player_command` — but v0 has **no user system**, no accounts, and no
login. ADR 0004 pins *what* crosses the wire; it does not say *how* the renderer
obtains or supplies the token. Left unspecified, this is exactly where a team
either invents a premature login flow or quietly disables auth for the front-end
— both of which we want to avoid.

Two forces shape the decision:

- **The renderer is browser code.** Anything it holds (a token, a URL) is visible
  to the user. There is no server-side session to hide a secret behind in v0.
- **Local dev must exercise the real guard, not a bypass** (CLAUDE.md security
  guardrails, ADR 0005): there is no localhost/loopback exception, so the
  renderer has to carry a genuine token even in development.

## Decision

For v0 the renderer authenticates with a **service token minted server-side** and
supplied to it as a **build/serve-time environment variable** — there is no login
flow.

- A JWT is minted with `make token` (`python -m app.auth_token`), signed by the
  same `JWT_SECRET` the engine verifies with. This is the existing service-token
  path (ADR 0005), reused unchanged.
- The token is handed to the renderer as `VITE_ENGINE_TOKEN` (Vite exposes only
  `VITE_`-prefixed vars to the browser). `config.ts` resolves it, together with
  `VITE_ENGINE_HOST`, into the two endpoints the renderer uses.
- The renderer presents the token two ways, matching what the engine already
  accepts (`engine/app/main.py`):
  - **WebSocket:** as the `?token=<jwt>` query param on `ws://<host>/ws` — the
    browser `WebSocket` API cannot set an `Authorization` header, so the query
    param (which `main.py` reads first) is the supported channel.
  - **`POST /command`:** as the `Authorization: Bearer <jwt>` header.
- Under `docker compose`, the value comes from `RENDERER_TOKEN` in the untracked
  `.env` (mirrored into `VITE_ENGINE_TOKEN`); for host dev it lives in
  `renderer/.env`. Only `.env.example` templates are committed (ADR 0005).

The token is deliberately treated as **exposed to the browser** and **short-lived
and dev-only**. It is a service token, never a user credential; it grants only
what the v0 API grants (read state, present an object).

## Consequences

- The renderer runs against the **real** always-on guard with no bypass: dev and
  prod take the same code path, and `AUTH_REQUIRED=false` remains the only
  documented (dev-only) no-op, unchanged by this decision.
- No login/session/accounts machinery is built before there is a user model —
  the smallest thing that satisfies the guard. When real users arrive, this ADR
  is **superseded** by a token-exchange/login flow (e.g. the browser trades a
  short-lived credential for a scoped token); the wire contract (ADR 0004) and
  the engine guard (ADR 0005) do not have to change for that.
- The exposure is bounded and visible: a leaked dev token expires (`JWT_TTL_SECONDS`)
  and carries only v0 API scope. This is acceptable for a local simulation, and
  is documented in `renderer/.env.example`, the root `.env.example`, and
  `renderer/README.md` so it is never mistaken for a production pattern.
- The seam that authenticates lives entirely in the renderer's `config.ts`
  (token → endpoints) and the engine's `auth` module (mint/verify). Changing the
  scheme later is confined to those two places plus this ADR.

# 0005 — Always-on API authentication (HS256 JWT)

## Status

Accepted

## Date

2026-07-10

## Context

The transport (ADR 0003) exposes the being over HTTP/WebSocket: `GET /state`
returns the full snapshot and `/ws` streams a frame per tick. Once the engine
runs anywhere other than a private laptop loop — the Docker stack (V0-5), a
shared host, later a renderer over the network — those endpoints are an open
door to the being's entire state and, as commands land (V0-4/V0-10), to driving
it. The engine needs authentication before that surface widens, and it needs it
as a foundation the later slices inherit rather than a bolt-on.

Forces shaping the design:

- **Auth must be in the code path from the start, not added later.** A guard you
  can forget to apply is one that will be forgotten. It should be wired into the
  routes now, while there are only two, and be impossible to skip per-route by
  accident.
- **No "trusted network" shortcut.** A localhost/loopback bypass is the classic
  hole: it is invisible in tests, and the "trusted" assumption breaks the moment
  the service is containerised or port-forwarded. The only switch is an explicit,
  visible config flag — off is a deliberate, testable dev choice, never an
  implicit consequence of where the request came from.
- **Secrets are deploy config, not authored tuning.** The signing secret and the
  issuer/audience/TTL are environment/secret config like `DATABASE_URL`, so they
  belong in the environment (and `.env`, never committed), not in `config/*.yaml`
  which `ConfigService` owns for gameplay tuning.
- **Symmetric now, asymmetric later.** v0 is one engine minting and verifying its
  own service tokens; a shared secret (HS256) is the simplest thing that works.
  Multiple issuers or third-party verifiers would want RS256/asymmetric keys —
  that change must be confined to one module.

## Decision

Add one deep module, `engine/app/auth.py`, that owns the whole token story
behind a small surface, and wire it into the transport.

- **`AuthConfig.from_env()`** resolves settings from the environment:
  `JWT_SECRET` (required to mint/verify), `JWT_ISSUER` (default `jarvis`),
  `JWT_AUDIENCE` (default `jarvis-engine`), `JWT_TTL_SECONDS` (default `3600`),
  and `AUTH_REQUIRED` (default `true`). It is a frozen dataclass so tests can
  also construct it directly.
- **`mint_token(config, subject=...)`** signs a short-lived **HS256** token with
  `iss/aud/sub/iat/exp`; it refuses to mint without a secret. The CLI
  `python -m app.auth_token` (wired as `make token`) is the **only** mint path —
  there is deliberately no login flow and no public token-minting HTTP endpoint.
- **`require_auth(config)`** builds the FastAPI dependency used by protected
  routes. It reads `Authorization: Bearer <jwt>`, verifies signature + `exp` +
  `iss` + `aud`, and raises `401` on anything missing or invalid. It is returned
  as a closure (not a callable class instance) so FastAPI can resolve its header
  annotation under `from __future__ import annotations` — an instance has no
  `__globals__`, so the string annotation would never be evaluated.
- **`authenticate_ws(config, token)`** applies the same verification to a token
  taken from the WebSocket handshake (`?token=` query param or the
  `Authorization` header). `/ws` accepts the socket, verifies, and on failure
  `close(code=1008)` before streaming a single frame.
- **Protected:** `GET /state` and (later) player commands. **Public:**
  `GET /health` → `{"status": "ok"}` (a liveness probe needs no token).
- **Always in the code path, gated only by `AUTH_REQUIRED`.** When the flag is
  false the guard is a documented dev-only no-op that returns empty claims —
  **there is no localhost/loopback bypass**; the flag is the only switch.

Secrets are kept out of git: `.env`/`*.pem`/`*.key` are gitignored, a placeholder
`.env.example` is committed, `docker-compose.yml` interpolates `JWT_SECRET` (and
the rest) from the environment, and the `pre-commit` hook blocks a staged `.env`,
`*.pem`/`*.key`, or a PEM/AWS-key literal.

## Consequences

- The engine's state surface is closed by default: `GET /state` and `/ws` require
  a verified token, `GET /health` stays open. Demonstrated with a live server —
  `/state` 401 without a token, 200 with a minted one, `/health` 200.
- Auth is the foundation later slices inherit for free: player commands (V0-4,
  V0-10) declare the same dependency; nothing has to remember to re-secure them.
- Retuning claims/TTL and rotating the secret is an environment change, not a
  code change. Turning auth off for throwaway local dev is one explicit flag, and
  the "off" behaviour is itself covered by a test.
- The token surface is intentionally minimal: service tokens minted by one CLI,
  no login/refresh, no HTTP mint endpoint — smaller surface, less to secure.
- **Migration path:** moving to RS256/asymmetric keys (multiple issuers, external
  verifiers) is confined to `auth.py` — the algorithm, key material, and verify
  options live there; routes and the `require_auth`/`authenticate_ws` surface do
  not change. That will be its own ADR superseding this one when it lands.
- HS256 means every verifier holds the signing secret; acceptable while the
  engine is the sole issuer and verifier, and the reason the asymmetric path is
  called out above.

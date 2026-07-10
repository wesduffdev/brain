# renderer — PixiJS being view

The browser front-end for the situated-being simulation. It connects to the
engine over a WebSocket, draws the being's current **emotion** (from the engine's
visual hints) and **needs** each tick, and sends one **`player_command`**
(`present_object`) back. It owns **no** psychology or decision logic — it forwards
intent and draws frames (BRIEF §17, architectural rule #1). The wire contract it
renders is [`docs/adr/0004`](../docs/adr/0004-render-state-contract.md); how it
authenticates is [`docs/adr/0010`](../docs/adr/0010-renderer-authentication.md).

## Modules (BRIEF §7)

- `src/RenderState.ts` — parses a `being_state_update` frame; tolerates absent
  `pose`/`action`/`intensity` (V0-4 fills them) and ignores unknown fields.
- `src/SocketClient.ts` — opens `ws://…/ws?token=<jwt>` and streams parsed frames.
- `src/CommandPanel.ts` — POSTs a `player_command` to `/command` with the token.
- `src/BeingView.ts` — draws the face (from visual hints) and a bar per need.
- `src/config.ts` — resolves the engine host + token into endpoints.
- `src/main.ts` — wiring only.

## Auth — there is no login in v0

The engine requires a JWT on `/ws` and `/command` (ADR 0005). For v0 dev you
**mint a service token server-side** and hand it to the renderer via an env var —
there is no login flow.

```bash
# from the repo root, with JWT_SECRET set in the root .env (see .env.example):
make token                      # prints a JWT
cp renderer/.env.example renderer/.env
# paste the JWT as VITE_ENGINE_TOKEN in renderer/.env
```

The token is sent as the WS `?token=` query param and the `POST /command` bearer
header. It is visible to the browser — a short-lived dev service token, never a
real user credential.

## Run

```bash
npm install
npm run dev        # http://localhost:5173  (needs the engine on :8000)
npm run build      # type-check + production build to dist/
npm test           # vitest: RenderState / SocketClient / CommandPanel / config
```

Under Docker: `docker compose up` starts `engine` + `renderer`; set
`RENDERER_TOKEN` in the root `.env` (from `make token`) so the browser gets a
valid token. Open http://localhost:5173.

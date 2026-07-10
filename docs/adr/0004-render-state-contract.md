# 0004 — Render-state contract: `being_state_update` frame and `player_command`

## Status

Accepted

## Date

2026-07-10

## Context

The renderer (V0-11, a PixiJS app) and the engine's `RenderStateService`
(V0-10) are built in parallel, on opposite sides of a WebSocket. The renderer
needs to know exactly what a render frame looks like before the service that
produces it exists, and the service needs to know exactly what commands can
come back. `docs/BRIEF.md` §14 sketches both messages, but a sketch in the
brief is not a contract two teams can build against without drift.

This is also a boundary with a rule attached. `BRIEF.md` §17 and architectural
rule #1 (§19) say the renderer must own **no** psychology or decision logic —
it draws whatever the engine tells it and sends back only raw player intent.
If the frame or the command shape is left loose, that boundary erodes: a
renderer starts inferring emotion, or the engine starts trusting a command it
never validated.

Two further pressures make an early pin worthwhile:

- The frame grows across slices. Today the being's domain `state()` is
  `{beingId, tick, needs, emotion}` (see `engine/app/domain/being_state.py`).
  Actions and pose arrive with V0-4; a `perceived` block may be added by V0-2.
  A contract frozen now must be **forward-compatible**, not a snapshot of
  today's fields.
- This is a documentation-only slice by design. There is no code to test yet;
  the ADR *is* the deliverable. It becomes the single source of truth for the
  render contract specifically (the roadmap stays in `README.md`, the
  architecture in `BRIEF.md`), and V0-10 / V0-11 cite it rather than re-deriving
  the shape.

## Decision

Two message types cross the engine↔renderer WebSocket, and only these two in
v0. The engine sends `being_state_update`; the renderer sends `player_command`.

### `being_state_update` — engine → renderer

One frame per emitted state. `RenderStateService` (V0-10) maps the domain
`state()` snapshot onto this frame; it adds the presentation-only fields (the
frame `type` envelope and the `visual` hints) and makes **no psychology
decision** while doing so. Field-by-field, with what is real in v0 today versus
what a later slice fills in:

| Field       | Type                         | v0 today | Source / arrives with |
|-------------|------------------------------|----------|-----------------------|
| `type`      | const `"being_state_update"` | present  | Frame envelope added by `RenderStateService` (V0-10); constant. Not in domain `state()`. |
| `beingId`   | string                       | present  | Domain `state()` today. |
| `tick`      | integer                      | present  | Domain `state()` today. |
| `emotion`   | string (dominant emotion)    | present  | Domain `state()` today — a bare string, one of the v0 emotions below. |
| `intensity` | float `0.0–1.0`              | absent   | Domain emotion is a bare string today, so `RenderStateService` supplies a neutral default until `EmotionState` carries an intensity (emotion/action work, ~V0-4). |
| `needs`     | object `{name: int 0–100}`   | present  | Domain `state()` today — the seven needs from `config/tick_rates.yaml`. |
| `pose`      | string                       | absent   | Arrives with **V0-4** (actions / decision). Renderer treats absent as unknown/idle. |
| `action`    | string                       | absent   | Arrives with **V0-4** (`currentAction`). Absent until then. |
| `visual`    | object (see below)           | present† | Presentation hints derived by `RenderStateService` from emotion/action. †The engine may emit a minimal/empty `visual` in v0; it is never psychology, only draw hints. |
| `perceived` | object (objects + confidence)| absent   | May be added to `state()` by **V0-2** (perceived-vs-true seam). Passes through the frame when present. |

- **`emotion`** is one of the v0 emotions in `config/emotions.yaml` /
  `BRIEF.md` §9: `calm`, `curious`, `hungry`, `sleepy`, `scared`, `frustrated`
  — with `happy`, `excited`, `comforted` reachable only once interactions land.
  Emotion is always **derived** engine-side; the renderer never computes it.
- **`needs`** is a flat map of need name → integer clamped `0–100`. In v0 the
  keys are `hunger, sleep, comfort, warmth, curiosity, safety, hygiene`. The
  renderer must not assume a fixed key set — it renders whatever needs arrive.
- **`visual`** carries only draw hints: `mouth` (e.g. `small_open`), `eyes`
  (e.g. `wide`), `effects` (array, e.g. `["head_tilt"]`), `thought` (a short
  glyph such as `"?"`). These are a presentation mapping from emotion/action,
  owned entirely by `RenderStateService`; they encode no decision.

**Forward-compatibility rule (load-bearing).** Consumers **must ignore unknown
fields** and **tolerate absent optional fields**. Fields present in v0 today
(`type, beingId, tick, emotion, needs`, and a `visual` block) are the guaranteed
core; `intensity, pose, action` and any `perceived` block appear as later slices
land, and further fields may be added without a new frame `type`. A renderer
built against this ADR in V0-11 stays valid as the frame grows — it renders what
it recognizes and skips the rest. `RenderStateService` serializes whatever
`state()` returns rather than hard-coding a field list, so V0-2 / V0-4 growth
does not break the wire.

### `player_command` — renderer → engine

The renderer's only outbound message. It expresses raw player intent and nothing
more.

| Field      | Type                     | Notes |
|------------|--------------------------|-------|
| `type`     | const `"player_command"` | Discriminates the inbound message. |
| `command`  | string (from the v0 set) | v0 command set: **`present_object`** (offer/place an object into the room for the being to perceive and possibly act on). The set is small in v0 and grows in later slices. |
| `targetId` | string                   | The object id the command refers to (e.g. `obj_red_ball`), when the command needs a target. |

**Commands are validated engine-side.** A `CommandService` (V0-10) validates
every inbound command against the known command set and targets, and rejects
anything unknown or malformed; an accepted command becomes an input to the
world/engine, never a shortcut around it. The renderer owns **no**
psychology or decision logic (`BRIEF.md` §17, architectural rule #1, §19): it
does not decide what the being does, does not choose actions, and does not
interpret outcomes — it forwards intent and draws frames. The being's response
to a presented object is decided by the engine's psychology (perception →
decision → safety), exactly as if the object had appeared any other way.

### Design boundary and no-caregiver reaffirmation

This contract carries the project's design boundary onto the wire:

- **No caregiver concept.** There is no caregiver in this simulation and no
  caregiver-directed command or frame field. `player_command` expresses a
  player acting on the **world** (e.g. presenting an object), never a caregiver
  the being seeks or summons. The legacy "seek caregiver" / "cry to summon" /
  "freeze" phrasing in `BRIEF.md` §9 (the light example, `EmotionState`
  examples) is **superseded** by ADR 0001, `CLAUDE.md`, and this ADR; no such
  action or command exists. Actions the frame can report (once V0-4 lands) are
  self- and world-directed only (observe / approach / withdraw / touch / grasp
  / push …).
- **Harm stays abstract.** The frame conveys the being's state — including
  distress, `scared`, low safety — as abstract signals (emotion string,
  intensity, need levels, visual hints), never a depiction of real-world harm.
  The renderer visualizes consequences and recovery, not instruction. See
  `docs/design_boundary.md` and `BRIEF.md` §2.

## Consequences

- V0-10 (`RenderStateService`, `CommandService`) and V0-11 (the PixiJS app) can
  proceed **in parallel** against a fixed shape: V0-11 parses this frame and
  emits this command before the service that produces it exists, and V0-10
  targets this frame without waiting on the renderer.
- The frame is a superset that fills in over time. V0-10's contract test asserts
  a frame validates for a known state (core fields present, unknown fields
  tolerated); the "absent until later" cells above tell that test what is
  optional in v0. No consumer breaks when V0-2 adds `perceived` or V0-4 adds
  `pose`/`action`/`intensity`, because unknown/absent fields are ignored.
- The renderer/psychology boundary is enforced at two points: the engine derives
  every emotion/action/visual hint (renderer never computes them), and the
  engine validates every command (renderer never bypasses the world). This keeps
  architectural rule #1 checkable rather than aspirational.
- `intensity`, `pose`, and `action` are documented as engine-owned fields that
  are simply not populated yet. When the emotion model gains intensity and V0-4
  adds actions, they are filled in with no change to the wire contract or this
  ADR — the frame `type` stays `being_state_update`.
- This ADR is the source of truth for the render contract; `BRIEF.md` §14
  remains the originating sketch and is not restated elsewhere. If the contract
  must change incompatibly later, this ADR is **superseded**, not rewritten.

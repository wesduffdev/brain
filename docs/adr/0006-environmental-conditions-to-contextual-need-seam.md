# 0006 — Environmental conditions → contextual-need seam

## Status

Accepted

## Date

2026-07-10

## Context

The being has two **contextual** needs — `safety` and `warmth` — that carry no
drift of their own (ADR 0001; `tick_rates.yaml` marks them `contextual` and
`NeedService` deliberately skips them). Until now nothing moved them, so `scared`
(fear), whose rule is `safety <= 30` in `emotions.yaml`, could never fire. The
brief is explicit that the environment — a dark or loud room — is what should
move these needs and make fear possible (`docs/BRIEF.md` §9 Environmental
Conditions, §5, §13 runtime flow): "dark room → … → safety need rises → scared
emotion may become dominant", and that this is "much better than `dark =
scared`."

The perception seam (ADR 0002) already separated world-truth (`Room`,
`ObjectEntity`) from the being's perceived view and reserved this slice (V0-3)
as the point to add environment. A `Room` was pure structure (id, contents,
`base_confidence`). We need the world's ambient conditions to move the being's
contextual needs each tick — and, per the design boundary, harm (fear) must
arrive as an abstract, gradual state change with a visible cause and a recovery
path, never as a hard `dark ⇒ scared` switch.

## Decision

Introduce a single seam from **environmental conditions** to **contextual
needs**, mirroring how time drives autonomous needs and how perception bridges
world-truth to experience:

- **Conditions live on the room, as world-truth.** `Room` gains three optional
  category fields — `light`, `sound`, `temperature` — one category per
  dimension (e.g. `dark`, `loud`, `cool`). They are authored in
  `config/rooms.yaml`; an absent condition (`None`) moves nothing. The shipped
  room is `comfortable`/`normal`/`comfortable`, so a fresh being stays safe.
- **`config/environment.yaml` is the tuning surface.** It maps each category, by
  dimension, to the per-application delta it applies to a contextual need
  (`light.dark → {safety: -6}`, `sound.loud → {safety: -5}`,
  `temperature.cool → {warmth: -4}`, …), plus an `every_ticks` cadence. All
  numbers live here; no magnitude or threshold is hard-coded in service code.
- **`ConfigService` hands out a typed `EnvironmentPolicy`.** It carries the
  cadence and the `dimension → category → {need: delta}` table and knows how to
  sum the deltas for a room's current conditions. An absent file yields an empty
  policy that moves nothing (so earlier slices' pure tests are unchanged).
- **A new `EnvironmentService` is the only mover of contextual needs.** Given
  the room and the tick it resolves the room's conditions into per-need deltas
  and applies them, clamped to each need's own band. It holds no numbers: deltas
  and cadence come from the `EnvironmentPolicy`; the clamp bands come from the
  need policies, so a need's floor/ceiling keeps its single home in
  `tick_rates.yaml`. `warmth` is corrected to `contextual` to match the brief's
  canonical `tick_rates` (§10) and `CONTEXT.md`.
- **`Simulation` composes the step and owns world events.** Each `tick()` now
  applies autonomous drift, then the environmental push, then re-derives the
  emotion — so `scared` falls out of the existing emotion table, never set by
  hand. `Simulation.change_environment(light=…, sound=…, temperature=…)` lets a
  world event change the room's conditions mid-run (the demo's darkening); it is
  a world event, **not** an action of the being, and there is no caregiver, no
  "freeze"/withdraw action in this slice — only needs move and emotion
  re-derives.

A new service (not an extension of `PerceptionService`) because moving needs is
a distinct responsibility from producing a perceived view; the deletion test
passes (the resolve-conditions/sum-deltas/clamp-on-cadence behavior would move
into `Simulation`, not vanish). No environment **port** is introduced: the
environment is static config and nothing varies across such a boundary yet
(the deep-module rule from ADR 0001/0002).

## Consequences

- Fear is reachable and honest: a dark or loud room lowers `safety` gradually
  over ticks until it crosses the config threshold and `scared` becomes
  dominant; a comfortable room leaves the being calm. The path is abstract and
  gradual with a visible cause (the condition) and a recovery path (restoring
  the condition raises the need again) — the design boundary holds.
- Retuning is config-only, proven by tests: the environmental delta lives in
  `environment.yaml` and the fear threshold in `emotions.yaml`; changing either
  changes behavior with no code edit.
- The state shape is unchanged (`beingId` / `tick` / `needs` / `emotion` /
  `perceived`). Consumers (transport, render) see contextual needs now move;
  nothing new to serialize.
- The clamp band stays single-sourced in `tick_rates.yaml`; `environment.yaml`
  never restates a need's min/max.
- A room naming a category the environment config does not define fails loudly
  (ValueError) on resolution — the same vocabulary discipline as object
  properties — rather than silently doing nothing.
- `warmth` no longer drifts up on its own; it moves only with temperature.
  There is no `cold` emotion in the v0 table, so temperature has no emotion
  consequence yet — an honest need movement awaiting a future emotion rule.
- Next slices land cleanly on this seam: perception can later erode per-object
  `confidence` from the same conditions, and decision/withdraw behavior can read
  the fear this seam produces.

# 0002 — Perceived world vs. true world: the perception seam

## Status

Accepted

## Date

2026-07-10

## Context

The being now lives in a room that contains objects (`docs/BRIEF.md` §9). The
brief is explicit that the being must **never read the true world directly**: it
acts on a *perceived* world with a confidence per object, and object recognition
degrades under environmental conditions such as a dark or loud room (§9, §17,
§13 runtime flow). The brief is equally explicit that the being learns from an
object's **properties and outcomes, not its English name** — `developerLabel` is
human-facing metadata (§9, ObjectEntity).

Slice 1 (ADR 0001) gave the being internal state (needs → emotion) but no world.
This slice adds the world's structural truth (a `Room`, an `ObjectEntity`
catalog) and the being's perception of it. We need a boundary that keeps
world-truth and the being's experience of it distinct from the start, so that
later slices can erode confidence (environment), predict outcomes, and decide
actions against the *perceived* view without ever reaching around it into
ground truth.

## Decision

Introduce a single perception seam between world-truth and the being:

- **World-truth is plain data.** `Room` (`room_id`, `contains`,
  `base_confidence`) and `ObjectEntity` (`object_id`, `developer_label`,
  `properties`, `affordances`) are frozen domain dataclasses with no behavior.
  They are authored in `config/rooms.yaml` (one room, the object ids it
  contains, the room's perceptual clarity) and `config/object_properties.yaml`
  (a property/affordance **vocabulary** plus the object definitions). The
  vocabulary is the source of truth for what a property is; `ConfigService`
  rejects any object that claims a property or affordance outside it.
- **`PerceptionService` is the only bridge.** Given the true `Room` and the true
  object catalog it produces the being's **perceived view**: for each object the
  room contains and the catalog defines, `{objectId, confidence, properties,
  affordances}`. It deliberately **omits `developer_label`** — the being knows an
  object by its properties, not its name — and omits ids with no definition (the
  being cannot perceive what it has no concept of).
- **Confidence is config-driven and uniform for now.** Every perceived object
  reports the room's `base_confidence`. Nothing varies it per object yet, so
  there is no environment port; the environment slice (V0-3) will erode it and
  is the point at which a richer perception input is reassessed.
- **`Simulation.state()` exposes only the perceived view.** It gains a
  `perceived` block (`{"objects": [...]}`) composed at the `Simulation` seam
  from `PerceptionService`; the existing `beingId` / `tick` / `needs` /
  `emotion` keys are unchanged. No caller can read the true room or catalog
  through the public surface.

`PerceptionService` takes the catalog by constructor injection and the `Room`
per call, mirroring how `NeedService`/`EmotionService` receive typed policies
from `ConfigService`. No `WorldPort`/repository seam is introduced: the world is
static config this slice and nothing varies across such a boundary yet (the
deep-module rule from ADR 0001).

## Consequences

- The being's experience is a first-class, testable thing distinct from ground
  truth: behavior tests assert on `state()["perceived"]`, and the perceived view
  provably hides `developerLabel` while exposing real properties.
- Environment (V0-3) has a clean place to land: it will lower per-object
  `confidence` inside `PerceptionService` without changing the state shape or
  any consumer. Prediction, decision, and learning slices consume the perceived
  view, so they inherit the "never read true world" guarantee for free.
- Retuning perceptual clarity (`base_confidence`) or the object catalog is a
  `config/*.yaml` edit with no code change, proven by a test — the same
  config-driven discipline as drift and emotion.
- `state()` grew a key. Transport (V0-6) and render (V0-10) must serialize
  whatever `state()` returns rather than a hard-coded field list, as the v0
  execution plan already calls out.
- The vocabulary is load-bearing, not decorative: a typo'd or invented property
  fails at config-load time instead of being silently perceived.

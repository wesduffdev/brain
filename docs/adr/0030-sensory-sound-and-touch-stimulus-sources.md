# 0030 — Sensory stimulus sources: sound spike & contact (touch)

## Status

Accepted (extends [0027](0027-perception-motion-and-approach-stimulus.md);
consumes the [0026](0026-instinct-neural-model-strategy.md) frozen contract)

## Date

2026-07-11

## Context

The instinct model ([ADR 0026](0026-instinct-neural-model-strategy.md)) was
trained so a **sudden loud/unknown sound → freeze** and an **unexpected touch →
withdraw** (its seed archetypes: `sound_spike_intensity` + `unexpectedness` +
low `visibility_confidence` → freeze; `touch_intensity` + `unexpectedness` →
withdraw). But `WORLD-MOTION` ([ADR 0027](0027-perception-motion-and-approach-stimulus.md))
sourced only the **motion** features of the frozen 14-vector; it stubbed
`sound_spike_intensity` and `touch_intensity` to `0.0` through `MotionPolicy`'s
`sensory_defaults`, explicitly "until a later slice supplies a real source." With
those slots pinned at 0, the freeze and withdraw archetypes were unreachable from
real signals — the model could predict them, but the world never presented the
features that fire them. This is that later slice (`SENSORY-STIM`).

The constraints: the **frozen 14-feature contract is unchanged** (no feature
added, removed, or reordered — a retrain-forcing change); a stimulus keys on
**perceived** signals, never a `developer_label` ([ADR 0002](0002-perceived-vs-true-world.md));
sound/touch are **world/perception** concerns, never the instinct model's; and
the artifact-free path stays byte-identical (no predictor ⇒ no reaction).

## Decision

Widen the perception→instinct **stimulus seam** (ADR 0027) from one stimulus
event to a small **family**, all carrying the same frozen 14-feature payload
`{objectId, tick, features}`, all produced by the single `StimulusService` and
consumed uniformly by the `InstinctService`:

- **`being.perception.object_approached`** — object motion (unchanged, ADR 0027).
- **`being.perception.sound_spike`** — a SUDDEN transition into a configured
  loud/unknown sound category (via `change_environment`) that the being **hears
  but cannot see**. `MotionPolicy.sound_features(category)` builds a full vector
  with null motion, and config-driven `sound_spike_intensity` / `unexpectedness`
  / **low** `visibility_confidence` — exactly the freeze archetype. It is **not
  tied to a catalogued object**: its `objectId` is a perceived source token
  (`ambient_sound`), not a `developer_label`. Only the *onset* is a spike (a
  transition), not the sustained state; birth into a loud room is not a startle.
- **`being.perception.object_contacted`** — an approaching object that **crosses
  into the body** (`distance ≤ contact_distance`). `MotionPolicy.contact_features`
  layers a real `touch_intensity` (scaled by impact speed, floored so any real
  contact is felt) and a config `unexpectedness` onto the object's motion vector
  — the withdraw archetype. A crossing, not a steady state (an object resting at
  the body is not a fresh contact each tick).

The **sound `sound:` and contact `contact:` tuning live in `config/motion.yaml`**
and resolve into the existing `MotionPolicy` (the one policy `StimulusService`
already holds), rather than a new policy/seam — nothing varies across a seam here,
and the whole "perceived signal → frozen 14-vector" concern belongs in one place.
The `InstinctService` gate widens from `== OBJECT_APPROACHED` to a
`_STIMULUS_EVENTS` set; inference, selection, thresholds, cooldowns, persistence,
and the outbox are **untouched** — more features are sourced, the pipeline is not.
`unexpectedness` is sourced **only for these two sensory startles** (a sudden
sound / an unforeseen touch carry inherent surprise, config-driven); the
internal-state features (focus/stability/prior-prediction-error) stay defaulted,
and general prediction-error-driven `unexpectedness` remains future work.

## Consequences

- The being now **freezes** at a sudden loud/unknown sound and **withdraws** from
  a contact, through the existing shadow→active instinct chain (surfaced +
  interruptible per the INS-ACT flags). Demonstrated end-to-end with the trained
  `instinct.pt`: freeze (~0.80), withdraw (~0.62, clears its 0.6 threshold),
  flinch (~0.70), beside a no-instinct baseline that reacts 0 times.
- The frozen contract is **honored** — the same 14 slots, now more of them fed;
  no retrain is required and a drifted artifact is still rejected on load.
- The sound categories are authored in **two files** by concern: their slow
  contextual-need push stays in `environment.yaml` (ADR 0006), their fast
  instinct startle intensity in `motion.yaml`. Accepted split — different forces,
  different tuning surfaces — noted so a future reader expects it.
- The artifact-free path is **byte-identical**: with no predictor the chain is not
  built, so the new events change no behavior; the full suite stays green.
- `MotionPolicy` now owns sound/contact sourcing beside motion. If sound/contact
  sensing grows richer (multiple sound sources, contact hardness models), this is
  the natural split point into a dedicated `SensoryPolicy` — deferred until
  something actually varies across that seam.

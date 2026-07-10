# 0013 — Reframed design boundary: honest, possibly-lasting harm; no forced recovery

## Status

Accepted

## Date

2026-07-10

## Context

The purpose of this project is to study **simulated psychology** honestly. Two
pieces of the original design boundary work against that purpose:

- **"Every harmful path has a recovery path."** Real psychology includes
  conditioned fear, trust that does not fully return, trauma, trait drift, and
  learned helplessness. A guaranteed-recovery rule sanitizes exactly the
  dynamics the simulation exists to model.
- **A hard safety guardrail that *blocks* harmful actions** (ADR 0009, V0-4:
  `SafetyService` drops `touch`/`grab` on a `hot` object before ranking). If the
  being can never perform a harmful action, it can only ever learn "hot = bad"
  from the rule we authored — never from experience. Cause and effect does not
  teach when the effect is never allowed to land, which caps the learning the
  whole ML loop is built to produce.

Neither the boundary's ethical purpose nor the ML-safety principle ("learned
predictions never bypass safety", BRIEF §12) actually requires either of those.
The ethical purpose is served by keeping harm **abstract and non-instructional**;
the ML-safety principle is served by keeping a narrow **invariant floor** that
learned scores cannot cross. Both survive the reframe.

## Decision

Reframe the design boundary (`docs/design_boundary.md`, the CLAUDE.md
"Design boundary" section, and BRIEF §2):

- **Consequences are honest and may be lasting.** Negative outcomes produce real
  effects — conditioned fear, degraded trust, trait drift, non-recovery. There
  is **no requirement that every harm be recoverable**; recovery is modeled only
  where it plausibly exists (pain decays, withdrawing/comfort helps).
- **The being may take harmful actions and suffer for them.** That experience is
  the point — it is how cause→effect is learned. This *refines* ADR 0009: the
  safety seam stays, but what it blocks narrows from "harmful actions" to a
  minimal **invariant floor** — only actions that would break the *simulation
  itself*. Recoverable-but-harmful actions (touch the hot lamp) become
  **allowed and learnable**. (Implemented by ticket **V0-SAFE**.)
- **The one line that stays: abstract, never instructional.** Harm is always
  abstract internal state (deltas on pain / fear / stress / trust / comfort and
  the behaviors that follow), **never** step-by-step depictions of, or
  instructions for, harming a real or vulnerable being. Modeling harm inside the
  simulation is in bounds; producing real-world-harm instructions is out of
  bounds. This does not constrain the psychology, which is modeled entirely as
  internal state — so the line costs the simulation nothing.
- **The ML-safety invariant is preserved in narrowed form.** Learned/neural
  scores still never buy an action past the invariant floor (BRIEF §12–§13); they
  now govern the recoverable-risk layer instead of it being hard-coded — the
  being learns caution rather than hitting a wall.

## Consequences

- Supersedes the "every harmful path has a recovery path" framing everywhere it
  appeared (`docs/design_boundary.md`, `CLAUDE.md`, BRIEF §2). *Refines* — does
  not supersede — ADR 0009's decision/safety seam; 0009's Status now points here.
- Unblocks ticket **V0-SAFE** (reshape `SafetyService`: invariant floor + learnable
  recoverable harm) and gives the learning loop real negative signal to train on.
- The ethical anchor is unchanged and explicit: abstract, non-instructional,
  adults-only. The reframe removes sanitization, not the boundary.
- The README governance-index "Design boundary" row is updated in the same change.

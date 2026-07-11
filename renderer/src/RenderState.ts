/**
 * RenderState — parses an engine `being_state_update` frame (ADR 0004) into the
 * shape the renderer draws.
 *
 * This is the whole forward-compatibility contract in one place. The ADR makes
 * two rules load-bearing and this module is where they live:
 *   - tolerate absent optional fields (`pose`, `action`, `intensity` arrive with
 *     V0-4; `perceived` may arrive with V0-2), and
 *   - ignore unknown fields, so the frame can grow without breaking the wire.
 * It never assumes a fixed need set — it renders whatever needs arrive.
 *
 * It owns NO psychology: emotion, needs and visual hints are all decided
 * engine-side; this only reads them off the frame (BRIEF §17, architectural
 * rule #1).
 */

/** An ACTIVE instinct reaction (RENDER-RX), decided engine-side (INS-ACT) and
 * presented as draw hints stamped with the reaction `type` and `intensity`.
 * Present only while a reaction is active; absent otherwise. */
export interface ReactionVisual {
  type: string;
  intensity: number;
  mouth?: string;
  eyes?: string;
  effects?: string[];
  thought?: string;
}

export interface VisualHints {
  mouth?: string;
  eyes?: string;
  effects?: string[];
  thought?: string;
  /** Present only while an instinct reaction is active (RENDER-RX). */
  reaction?: ReactionVisual;
}

export interface RenderState {
  beingId: string;
  tick: number;
  emotion: string;
  /** 0..1; the engine supplies a neutral 0.5 default until the emotion model
   * carries a real intensity (~V0-4). Absent frames default to 0.5 here too. */
  intensity: number;
  /** Need name -> level 0..100. Not a fixed key set. */
  needs: Record<string, number>;
  /** Present from V0-4; `null` until then (renderer treats as idle/unknown). */
  pose: string | null;
  /** Present from V0-4; `null` until then. */
  action: string | null;
  visual: VisualHints;
}

const FRAME_TYPE = "being_state_update";
const NEUTRAL_INTENSITY = 0.5;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function asNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** Keep only numeric need levels; drop anything else so a malformed entry can't
 * break the draw loop. Any key is allowed — the need set is not fixed. */
function parseNeeds(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  const needs: Record<string, number> = {};
  for (const [name, level] of Object.entries(value)) {
    if (typeof level === "number" && Number.isFinite(level)) {
      needs[name] = level;
    }
  }
  return needs;
}

function parseStringArray(value: unknown): string[] | undefined {
  return Array.isArray(value)
    ? value.filter((e): e is string => typeof e === "string")
    : undefined;
}

function parseReaction(value: unknown): ReactionVisual | undefined {
  // Only surface a reaction the engine actually decided (a `type` is present);
  // anything else is treated as "no reaction active".
  if (!isRecord(value) || typeof value.type !== "string") return undefined;
  return {
    type: value.type,
    intensity: asNumber(value.intensity, 0),
    mouth: typeof value.mouth === "string" ? value.mouth : undefined,
    eyes: typeof value.eyes === "string" ? value.eyes : undefined,
    effects: parseStringArray(value.effects),
    thought: typeof value.thought === "string" ? value.thought : undefined,
  };
}

function parseVisual(value: unknown): VisualHints {
  if (!isRecord(value)) return {};
  const visual: VisualHints = {
    mouth: typeof value.mouth === "string" ? value.mouth : undefined,
    eyes: typeof value.eyes === "string" ? value.eyes : undefined,
    effects: parseStringArray(value.effects),
    thought: typeof value.thought === "string" ? value.thought : undefined,
  };
  const reaction = parseReaction(value.reaction);
  if (reaction) visual.reaction = reaction;
  return visual;
}

/** The face the being currently SHOWS: an active instinct reaction (RENDER-RX)
 * takes over the mouth / eyes / effects / thought; otherwise the emotion's hints
 * apply. This is a pure selection between two engine-supplied faces — the
 * renderer decides nothing (BRIEF §17, rule #1). A reaction that omits a token
 * falls back to the emotion's for that slot. */
export interface FaceHints {
  mouth?: string;
  eyes?: string;
  effects: string[];
  thought: string;
}

export function activeFace(visual: VisualHints): FaceHints {
  const r = visual.reaction;
  return {
    mouth: r?.mouth ?? visual.mouth,
    eyes: r?.eyes ?? visual.eyes,
    effects: r?.effects ?? visual.effects ?? [],
    thought: r?.thought ?? visual.thought ?? "",
  };
}

/** The debug-overlay readout for an active reaction — its type and intensity —
 * or the empty string when no reaction is active. Presentation only. */
export function reactionOverlayText(visual: VisualHints): string {
  const r = visual.reaction;
  return r ? `reaction: ${r.type} (${r.intensity.toFixed(2)})` : "";
}

/**
 * Parse an arbitrary decoded WS payload into a RenderState, or `null` if it is
 * not a `being_state_update` frame. Unknown fields are dropped; absent optional
 * fields fall back to safe defaults.
 */
export function parseRenderState(raw: unknown): RenderState | null {
  if (!isRecord(raw) || raw.type !== FRAME_TYPE) return null;
  return {
    beingId: asString(raw.beingId, ""),
    tick: asNumber(raw.tick, 0),
    emotion: asString(raw.emotion, "calm"),
    intensity: asNumber(raw.intensity, NEUTRAL_INTENSITY),
    needs: parseNeeds(raw.needs),
    pose: asNullableString(raw.pose),
    action: asNullableString(raw.action),
    visual: parseVisual(raw.visual),
  };
}

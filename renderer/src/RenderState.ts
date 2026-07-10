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

export interface VisualHints {
  mouth?: string;
  eyes?: string;
  effects?: string[];
  thought?: string;
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

function parseVisual(value: unknown): VisualHints {
  if (!isRecord(value)) return {};
  const effects = Array.isArray(value.effects)
    ? value.effects.filter((e): e is string => typeof e === "string")
    : undefined;
  return {
    mouth: typeof value.mouth === "string" ? value.mouth : undefined,
    eyes: typeof value.eyes === "string" ? value.eyes : undefined,
    effects,
    thought: typeof value.thought === "string" ? value.thought : undefined,
  };
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

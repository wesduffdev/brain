import { describe, it, expect } from "vitest";
import { parseRenderState } from "./RenderState";

// Behaviour of the render-frame parser (ADR 0004 `being_state_update`). The
// renderer draws whatever the engine sends; these specs pin the forward-compat
// rules the ADR makes load-bearing: tolerate absent optional fields, ignore
// unknown fields, never assume a fixed need set.

describe("parseRenderState", () => {
  it("reads emotion, needs and visual hints from a full frame", () => {
    const frame = {
      type: "being_state_update",
      beingId: "being_001",
      tick: 1024,
      emotion: "curious",
      pose: "approach",
      action: "observe",
      intensity: 0.7,
      needs: { hunger: 35, sleep: 40, comfort: 75, curiosity: 82 },
      visual: { mouth: "small_open", eyes: "wide", effects: ["head_tilt"], thought: "?" },
    };

    const state = parseRenderState(frame);

    expect(state).not.toBeNull();
    expect(state!.beingId).toBe("being_001");
    expect(state!.tick).toBe(1024);
    expect(state!.emotion).toBe("curious");
    expect(state!.intensity).toBeCloseTo(0.7);
    expect(state!.pose).toBe("approach");
    expect(state!.action).toBe("observe");
    expect(state!.needs).toEqual({ hunger: 35, sleep: 40, comfort: 75, curiosity: 82 });
    expect(state!.visual).toEqual({
      mouth: "small_open",
      eyes: "wide",
      effects: ["head_tilt"],
      thought: "?",
    });
  });

  it("tolerates a v0 frame with no pose, action or intensity yet", () => {
    // V0-4 fills pose/action/intensity in later; today they are simply absent.
    const frame = {
      type: "being_state_update",
      beingId: "being_001",
      tick: 3,
      emotion: "calm",
      needs: { hunger: 10, safety: 90 },
      visual: {},
    };

    const state = parseRenderState(frame);

    expect(state).not.toBeNull();
    expect(state!.pose).toBeNull();
    expect(state!.action).toBeNull();
    expect(state!.intensity).toBeCloseTo(0.5); // neutral default
    expect(state!.emotion).toBe("calm");
  });

  it("ignores unknown fields so a growing frame stays valid", () => {
    // V0-2 may add `perceived`; further fields may appear with no new type.
    const frame = {
      type: "being_state_update",
      beingId: "being_001",
      tick: 7,
      emotion: "scared",
      needs: { safety: 20 },
      visual: { mouth: "open" },
      perceived: { objects: [{ id: "obj_red_ball", confidence: 0.6 }] },
      mystery_future_field: 123,
    };

    const state = parseRenderState(frame);

    expect(state).not.toBeNull();
    expect(state!.emotion).toBe("scared");
    expect(state!.needs).toEqual({ safety: 20 });
    // Unknown fields are dropped, not surfaced on the parsed state.
    expect(state as unknown as Record<string, unknown>).not.toHaveProperty(
      "mystery_future_field",
    );
  });

  it("renders whatever needs arrive rather than a fixed key set", () => {
    const frame = {
      type: "being_state_update",
      beingId: "b",
      tick: 1,
      emotion: "calm",
      needs: { boredom: 42, thirst: 5, hunger: "nope" }, // non-numeric dropped
      visual: {},
    };

    const state = parseRenderState(frame);

    expect(state!.needs).toEqual({ boredom: 42, thirst: 5 });
  });

  it("returns null for a message that is not a being_state_update", () => {
    expect(parseRenderState({ type: "player_command", command: "present_object" })).toBeNull();
    expect(parseRenderState("not json object")).toBeNull();
    expect(parseRenderState(null)).toBeNull();
    expect(parseRenderState(42)).toBeNull();
  });
});

import { describe, it, expect } from "vitest";
import { postPlayerCommand } from "./CommandPanel";

// The renderer's one outbound message: a `player_command` (ADR 0004) POSTed to
// the engine's authenticated /command endpoint. These specs pin the wire shape
// and the bearer-token auth — the renderer forwards intent, it decides nothing.

describe("postPlayerCommand", () => {
  it("POSTs a player_command envelope with the bearer token", async () => {
    let capturedUrl = "";
    let capturedInit: RequestInit = {};
    const fakeFetch = async (url: string, init?: RequestInit) => {
      capturedUrl = url;
      capturedInit = init ?? {};
      return { ok: true, status: 200, json: async () => ({ status: "accepted" }) } as Response;
    };

    await postPlayerCommand(
      { commandUrl: "http://localhost:8000/command", token: "tok-123" },
      { command: "present_object", targetId: "obj_red_ball" },
      fakeFetch as unknown as typeof fetch,
    );

    expect(capturedUrl).toBe("http://localhost:8000/command");
    expect(capturedInit.method).toBe("POST");
    const headers = capturedInit.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer tok-123");
    expect(headers["Content-Type"]).toContain("application/json");
    expect(JSON.parse(capturedInit.body as string)).toEqual({
      type: "player_command",
      command: "present_object",
      targetId: "obj_red_ball",
    });
  });

  it("reports the accepted result from the engine", async () => {
    const fakeFetch = async () =>
      ({
        ok: true,
        status: 200,
        json: async () => ({ status: "accepted", command: "present_object" }),
      }) as Response;

    const result = await postPlayerCommand(
      { commandUrl: "http://localhost:8000/command", token: "t" },
      { command: "present_object", targetId: "obj_red_ball" },
      fakeFetch as unknown as typeof fetch,
    );

    expect(result.ok).toBe(true);
    expect(result.status).toBe(200);
  });

  it("surfaces a rejection (e.g. 422 unknown target) without throwing", async () => {
    const fakeFetch = async () =>
      ({ ok: false, status: 422, json: async () => ({ detail: "unknown target" }) }) as Response;

    const result = await postPlayerCommand(
      { commandUrl: "http://localhost:8000/command", token: "t" },
      { command: "present_object", targetId: "nope" },
      fakeFetch as unknown as typeof fetch,
    );

    expect(result.ok).toBe(false);
    expect(result.status).toBe(422);
  });
});

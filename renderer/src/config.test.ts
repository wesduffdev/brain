import { describe, it, expect } from "vitest";
import { loadEngineConfig } from "./config";

// The renderer has no login in v0 (ADR 0010): a service token minted with
// `make token` is supplied as VITE_ENGINE_TOKEN and must reach both the WS
// handshake and the /command bearer header. These specs pin that wiring.

describe("loadEngineConfig", () => {
  it("builds ws + command endpoints for the configured host and carries the token", () => {
    const config = loadEngineConfig({
      VITE_ENGINE_HOST: "localhost:8000",
      VITE_ENGINE_TOKEN: "minted.jwt.value",
    });

    expect(config.wsTarget.wsEndpoint).toBe("ws://localhost:8000/ws");
    expect(config.wsTarget.token).toBe("minted.jwt.value");
    expect(config.commandTarget.commandUrl).toBe("http://localhost:8000/command");
    expect(config.commandTarget.token).toBe("minted.jwt.value");
  });

  it("defaults to localhost:8000 with an empty token when nothing is set", () => {
    const config = loadEngineConfig({});

    expect(config.host).toBe("localhost:8000");
    expect(config.token).toBe("");
    expect(config.wsTarget.wsEndpoint).toBe("ws://localhost:8000/ws");
  });

  it("uses wss/https when VITE_ENGINE_SECURE is true", () => {
    const config = loadEngineConfig({
      VITE_ENGINE_HOST: "engine.example.com",
      VITE_ENGINE_TOKEN: "t",
      VITE_ENGINE_SECURE: "true",
    });

    expect(config.wsTarget.wsEndpoint).toBe("wss://engine.example.com/ws");
    expect(config.commandTarget.commandUrl).toBe("https://engine.example.com/command");
  });
});

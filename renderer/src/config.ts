/**
 * config — resolves where the engine is and the token to reach it.
 *
 * There is no login in v0 (BRIEF; ADR 0010): a service token is minted
 * server-side with `make token` and handed to the renderer as `VITE_ENGINE_TOKEN`
 * (a Vite build/serve-time env var). This module turns the env into the two
 * endpoints the renderer uses and stamps the token onto both — the WS `?token=`
 * query and the `POST /command` bearer header. It is pure over its `env`
 * argument so the token→endpoint wiring is unit-testable.
 */
import type { SocketTarget } from "./SocketClient";
import type { CommandTarget } from "./CommandPanel";

export interface EngineConfig {
  host: string;
  token: string;
  wsTarget: SocketTarget;
  commandTarget: CommandTarget;
}

interface EnvLike {
  // Index signature so Vite's `import.meta.env` (ImportMetaEnv) is assignable.
  [key: string]: unknown;
  VITE_ENGINE_HOST?: string;
  VITE_ENGINE_TOKEN?: string;
  VITE_ENGINE_SECURE?: string;
}

export function loadEngineConfig(env: EnvLike): EngineConfig {
  const host = env.VITE_ENGINE_HOST || "localhost:8000";
  const token = env.VITE_ENGINE_TOKEN || "";
  const secure = String(env.VITE_ENGINE_SECURE).toLowerCase() === "true";
  const wsProto = secure ? "wss" : "ws";
  const httpProto = secure ? "https" : "http";
  return {
    host,
    token,
    wsTarget: { wsEndpoint: `${wsProto}://${host}/ws`, token },
    commandTarget: { commandUrl: `${httpProto}://${host}/command`, token },
  };
}

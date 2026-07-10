/**
 * SocketClient — the renderer's inbound half of the engine WebSocket (ADR 0004).
 *
 * It opens `ws://…/ws?token=<jwt>` (the engine verifies the handshake token —
 * ADR 0005), decodes each `being_state_update` frame through `parseRenderState`,
 * and hands the parsed state to the caller. Malformed or non-frame messages are
 * dropped so one bad payload never stops the stream.
 *
 * The browser `WebSocket` is injected as a factory so the client can be driven
 * by a fake in tests — the seam is the socket, not the frame parsing. This
 * module owns no psychology; it forwards frames.
 */
import { parseRenderState, type RenderState } from "./RenderState";

/** The subset of the browser WebSocket this client uses. */
export interface SocketLike {
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  close(): void;
}

export type SocketFactory = (url: string) => SocketLike;

export type ConnectionStatus = "connecting" | "open" | "closed" | "error";

export interface SocketTarget {
  /** e.g. `ws://localhost:8000/ws` — the token is appended as `?token=`. */
  wsEndpoint: string;
  token: string;
}

export interface SocketHandlers {
  onState: (state: RenderState) => void;
  onStatus?: (status: ConnectionStatus) => void;
}

function withToken(endpoint: string, token: string): string {
  if (!token) return endpoint;
  const sep = endpoint.includes("?") ? "&" : "?";
  return `${endpoint}${sep}token=${encodeURIComponent(token)}`;
}

const defaultFactory: SocketFactory = (url) =>
  new WebSocket(url) as unknown as SocketLike;

export class SocketClient {
  private socket: SocketLike | null = null;

  constructor(
    private readonly target: SocketTarget,
    private readonly handlers: SocketHandlers,
    private readonly factory: SocketFactory = defaultFactory,
  ) {}

  /** Open the connection and begin reporting render state per frame. */
  connect(): void {
    const url = withToken(this.target.wsEndpoint, this.target.token);
    this.handlers.onStatus?.("connecting");
    const socket = this.factory(url);
    this.socket = socket;

    socket.onopen = () => this.handlers.onStatus?.("open");
    socket.onclose = () => this.handlers.onStatus?.("closed");
    socket.onerror = () => this.handlers.onStatus?.("error");
    socket.onmessage = (event) => this.handleMessage(event.data);
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
  }

  private handleMessage(data: unknown): void {
    let decoded: unknown;
    try {
      decoded = typeof data === "string" ? JSON.parse(data) : data;
    } catch {
      return; // not JSON — drop it, keep the stream alive
    }
    const state = parseRenderState(decoded);
    if (state) this.handlers.onState(state);
  }
}

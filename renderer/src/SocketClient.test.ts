import { describe, it, expect, vi } from "vitest";
import { SocketClient } from "./SocketClient";
import type { RenderState } from "./RenderState";

// A minimal fake standing in for the browser WebSocket. It records the URL it
// was opened with and lets a test push a message frame at the client.
class FakeSocket {
  static last: FakeSocket | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeSocket.last = this;
  }
  deliver(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
  deliverRaw(data: string) {
    this.onmessage?.({ data });
  }
  close() {
    this.closed = true;
    this.onclose?.();
  }
}

function frame(overrides: Record<string, unknown> = {}) {
  return {
    type: "being_state_update",
    beingId: "being_001",
    tick: 1,
    emotion: "curious",
    needs: { hunger: 20 },
    visual: {},
    ...overrides,
  };
}

describe("SocketClient", () => {
  it("connects to the engine with the auth token as a query param", () => {
    const factory = (url: string) => new FakeSocket(url);
    const client = new SocketClient(
      { wsEndpoint: "ws://localhost:8000/ws", token: "tok-abc.def.ghi" },
      { onState: () => {} },
      factory,
    );

    client.connect();

    expect(FakeSocket.last!.url).toBe("ws://localhost:8000/ws?token=tok-abc.def.ghi");
    client.close();
  });

  it("url-encodes the token", () => {
    const factory = (url: string) => new FakeSocket(url);
    const client = new SocketClient(
      { wsEndpoint: "ws://localhost:8000/ws", token: "a b/c+d" },
      { onState: () => {} },
      factory,
    );

    client.connect();

    expect(FakeSocket.last!.url).toContain("token=a%20b%2Fc%2Bd");
    client.close();
  });

  it("parses incoming frames and reports render state each tick", () => {
    const seen: RenderState[] = [];
    const client = new SocketClient(
      { wsEndpoint: "ws://localhost:8000/ws", token: "t" },
      { onState: (s) => seen.push(s) },
      (url) => new FakeSocket(url),
    );
    client.connect();

    FakeSocket.last!.deliver(frame({ tick: 1, emotion: "calm" }));
    FakeSocket.last!.deliver(frame({ tick: 2, emotion: "curious" }));

    expect(seen.map((s) => s.tick)).toEqual([1, 2]);
    expect(seen.map((s) => s.emotion)).toEqual(["calm", "curious"]);
    client.close();
  });

  it("ignores a malformed frame rather than crashing the stream", () => {
    const onState = vi.fn();
    const client = new SocketClient(
      { wsEndpoint: "ws://localhost:8000/ws", token: "t" },
      { onState },
      (url) => new FakeSocket(url),
    );
    client.connect();

    FakeSocket.last!.deliverRaw("}{ not json");
    FakeSocket.last!.deliver({ type: "something_else" });

    expect(onState).not.toHaveBeenCalled();
    client.close();
  });

  it("closes the underlying socket", () => {
    const client = new SocketClient(
      { wsEndpoint: "ws://localhost:8000/ws", token: "t" },
      { onState: () => {} },
      (url) => new FakeSocket(url),
    );
    client.connect();
    const sock = FakeSocket.last!;

    client.close();

    expect(sock.closed).toBe(true);
  });
});

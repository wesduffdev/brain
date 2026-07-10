/**
 * main — wires the renderer together and owns no logic of its own.
 *
 * It reads the engine config (host + minted service token), stands up the PixiJS
 * stage and the BeingView, opens the SocketClient to stream `being_state_update`
 * frames into the view, and mounts the CommandPanel that POSTs a `player_command`
 * back. Every decision (emotion, needs, the being's response to a command) is
 * the engine's; this file just connects the pieces (BRIEF §17, rule #1).
 */
import { Application } from "pixi.js";
import { loadEngineConfig } from "./config";
import { BeingView } from "./BeingView";
import { SocketClient, type ConnectionStatus } from "./SocketClient";
import { createCommandPanel, type CommandResult } from "./CommandPanel";

const statusEl = document.getElementById("status") as HTMLElement;
const stageEl = document.getElementById("stage") as HTMLElement;
const panelEl = document.getElementById("panel") as HTMLElement;

function setStatus(text: string): void {
  statusEl.textContent = text;
}

async function main(): Promise<void> {
  const config = loadEngineConfig(import.meta.env);

  const app = new Application();
  await app.init({
    width: 480,
    height: 460,
    background: 0x161b26,
    antialias: true,
  });
  stageEl.appendChild(app.canvas);

  const view = new BeingView(app.stage);

  if (!config.token) {
    setStatus(
      "no token set — mint one with `make token` and set VITE_ENGINE_TOKEN (see renderer/.env.example)",
    );
  }

  const client = new SocketClient(config.wsTarget, {
    onState: (state) => view.update(state),
    onStatus: (status: ConnectionStatus) => {
      if (status === "open") setStatus(`connected to ${config.host}`);
      else if (status === "connecting") setStatus(`connecting to ${config.host}…`);
      else if (status === "closed") setStatus("disconnected");
      else setStatus("connection error — check the engine and the token");
    },
  });
  client.connect();

  createCommandPanel(panelEl, config.commandTarget, {
    onResult: (result: CommandResult) => {
      setStatus(
        result.ok
          ? `present_object accepted (${result.status})`
          : `present_object rejected (${result.status})`,
      );
    },
  });

  window.addEventListener("beforeunload", () => client.close());
}

main().catch((err) => setStatus(`renderer failed to start: ${String(err)}`));

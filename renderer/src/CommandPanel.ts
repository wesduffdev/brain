/**
 * CommandPanel — the renderer's one outbound action: a `player_command`
 * (ADR 0004).
 *
 * The command travels over the authenticated HTTP `POST /command` (the engine's
 * `/ws` is send-only), carrying the minted service token as a bearer header
 * (ADR 0005). `postPlayerCommand` builds that request; `createCommandPanel`
 * renders a button that fires it. The renderer decides nothing — it forwards
 * raw player intent and the engine's psychology responds to it, exactly as if
 * the object had appeared any other way (BRIEF §17, architectural rule #1).
 */

export interface CommandTarget {
  /** e.g. `http://localhost:8000/command`. */
  commandUrl: string;
  token: string;
}

export interface PlayerCommand {
  command: string;
  targetId?: string;
}

export interface CommandResult {
  ok: boolean;
  status: number;
}

/** POST a `player_command` envelope with the bearer token. Returns the engine's
 * accept/reject without throwing on a 4xx, so the UI can report it. */
export async function postPlayerCommand(
  target: CommandTarget,
  command: PlayerCommand,
  fetchImpl: typeof fetch = fetch,
): Promise<CommandResult> {
  const body: Record<string, unknown> = {
    type: "player_command",
    command: command.command,
  };
  if (command.targetId !== undefined) body.targetId = command.targetId;

  const response = await fetchImpl(target.commandUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${target.token}`,
    },
    body: JSON.stringify(body),
  });

  return { ok: response.ok, status: response.status };
}

export interface CommandPanelOptions {
  onResult?: (result: CommandResult) => void;
}

/** Render the v0 command UI: a single "Present object" button that offers the
 * red ball into the room. The button is the only player affordance in v0. */
export function createCommandPanel(
  root: HTMLElement,
  target: CommandTarget,
  options: CommandPanelOptions = {},
): void {
  const button = document.createElement("button");
  button.textContent = "Present object (red ball)";
  button.addEventListener("click", () => {
    button.disabled = true;
    postPlayerCommand(target, { command: "present_object", targetId: "obj_red_ball" })
      .then((result) => options.onResult?.(result))
      .catch(() => options.onResult?.({ ok: false, status: 0 }))
      .finally(() => {
        button.disabled = false;
      });
  });
  root.appendChild(button);
}

/**
 * BeingView — draws the being from a render frame, and nothing more.
 *
 * It is a pure presentation surface: given a `RenderState`, it paints a face
 * from the engine's already-decided visual hints (mouth/eyes/effects/thought)
 * and a bar per need that arrived. It reads emotion and needs off the frame; it
 * never derives them (BRIEF §17, architectural rule #1). `pose`/`action` are
 * shown when present and simply omitted when absent (V0-4 fills them in), so the
 * view stays valid as the frame grows.
 *
 * Rendering is visual by nature — this module is exercised in the browser, not
 * by unit tests. The testable logic (frame parsing, socket, command) lives in
 * the sibling modules.
 */
import { Container, Graphics, Text, TextStyle } from "pixi.js";
import type { RenderState } from "./RenderState";

const EMOTION_TINT: Record<string, number> = {
  calm: 0x8fd3ff,
  curious: 0xffd479,
  hungry: 0xffb0b0,
  sleepy: 0xb0b4d8,
  scared: 0xd06666,
  frustrated: 0xd0a070,
  happy: 0x9be59b,
  excited: 0xffe066,
  comforted: 0xb5e8c9,
};
const DEFAULT_TINT = 0x9aa4bf;

function needColor(level: number): number {
  // Low needs run hot (red), satisfied needs run calm (green).
  if (level <= 25) return 0xe06666;
  if (level <= 60) return 0xe0c060;
  return 0x66c28a;
}

export class BeingView {
  private readonly face = new Graphics();
  private readonly needsBox = new Container();
  private readonly labels: Text;
  private readonly thought: Text;

  constructor(
    stage: Container,
    private readonly width = 480,
    private readonly height = 460,
  ) {
    const labelStyle = new TextStyle({ fill: 0xe6e9ef, fontSize: 16, fontFamily: "system-ui" });
    this.labels = new Text({ text: "", style: labelStyle });
    this.labels.position.set(16, 300);

    this.thought = new Text({
      text: "",
      style: new TextStyle({ fill: 0xffffff, fontSize: 28, fontFamily: "system-ui" }),
    });
    this.thought.position.set(this.width / 2 + 70, 40);

    this.needsBox.position.set(16, 340);

    stage.addChild(this.face);
    stage.addChild(this.labels);
    stage.addChild(this.thought);
    stage.addChild(this.needsBox);
  }

  /** Repaint everything from the latest frame. */
  update(state: RenderState): void {
    this.drawFace(state);
    this.drawText(state);
    this.drawNeeds(state.needs);
  }

  private drawFace(state: RenderState): void {
    const cx = this.width / 2;
    const cy = 150;
    const r = 80;
    const tint = EMOTION_TINT[state.emotion] ?? DEFAULT_TINT;

    const g = this.face;
    g.clear();
    // Head.
    g.circle(cx, cy, r).fill({ color: tint, alpha: 0.35 }).stroke({ color: tint, width: 3 });

    // Eyes, shaped by the hint (falls back to a plain eye for unknown hints).
    this.drawEye(g, cx - 28, cy - 15, state.visual.eyes);
    this.drawEye(g, cx + 28, cy - 15, state.visual.eyes);

    // Mouth, shaped by the hint.
    this.drawMouth(g, cx, cy + 35, state.visual.mouth);
  }

  private drawEye(g: Graphics, x: number, y: number, hint?: string): void {
    switch (hint) {
      case "wide":
        g.circle(x, y, 12).fill(0xffffff).stroke({ color: 0x1a1f2b, width: 2 });
        g.circle(x, y, 5).fill(0x1a1f2b);
        break;
      case "narrow":
        g.rect(x - 10, y - 2, 20, 4).fill(0x1a1f2b);
        break;
      case "droopy":
        g.rect(x - 9, y + 2, 18, 5).fill(0x1a1f2b);
        break;
      default: // soft / neutral / unknown
        g.circle(x, y, 8).fill(0xffffff).stroke({ color: 0x1a1f2b, width: 2 });
        g.circle(x, y, 3.5).fill(0x1a1f2b);
    }
  }

  private drawMouth(g: Graphics, x: number, y: number, hint?: string): void {
    switch (hint) {
      case "smile":
        g.arc(x, y - 6, 22, 0.15 * Math.PI, 0.85 * Math.PI).stroke({ color: 0x1a1f2b, width: 3 });
        break;
      case "frown":
        g.arc(x, y + 14, 22, 1.15 * Math.PI, 1.85 * Math.PI).stroke({ color: 0x1a1f2b, width: 3 });
        break;
      case "small_open":
        g.ellipse(x, y, 8, 6).fill(0x1a1f2b);
        break;
      case "open":
        g.ellipse(x, y, 12, 12).fill(0x1a1f2b);
        break;
      case "big_open":
        g.ellipse(x, y, 16, 18).fill(0x1a1f2b);
        break;
      default: // neutral / unknown
        g.rect(x - 16, y - 1.5, 32, 3).fill(0x1a1f2b);
    }
  }

  private drawText(state: RenderState): void {
    const parts = [
      `tick ${state.tick}`,
      `emotion: ${state.emotion} (${state.intensity.toFixed(2)})`,
    ];
    // pose/action arrive with V0-4 — only shown once present.
    if (state.pose) parts.push(`pose: ${state.pose}`);
    if (state.action) parts.push(`action: ${state.action}`);
    if (state.visual.effects && state.visual.effects.length > 0) {
      parts.push(`fx: ${state.visual.effects.join(", ")}`);
    }
    this.labels.text = parts.join("   ");
    this.thought.text = state.visual.thought ?? "";
  }

  private drawNeeds(needs: Record<string, number>): void {
    // Rebuild the bar set each frame — the need keys are not fixed (ADR 0004),
    // so we render whatever arrived.
    for (const child of this.needsBox.removeChildren()) child.destroy();

    const barWidth = 200;
    const rowHeight = 22;
    const labelStyle = new TextStyle({ fill: 0xcfd6e6, fontSize: 13, fontFamily: "system-ui" });

    Object.entries(needs).forEach(([name, level], i) => {
      const y = i * rowHeight;
      const clamped = Math.max(0, Math.min(100, level));

      const label = new Text({ text: name, style: labelStyle });
      label.position.set(0, y);
      this.needsBox.addChild(label);

      const bar = new Graphics();
      bar.roundRect(90, y, barWidth, 14, 3).fill(0x2a3550);
      bar.roundRect(90, y, (barWidth * clamped) / 100, 14, 3).fill(needColor(clamped));
      this.needsBox.addChild(bar);

      const value = new Text({ text: String(Math.round(clamped)), style: labelStyle });
      value.position.set(90 + barWidth + 8, y);
      this.needsBox.addChild(value);
    });
  }

  get size(): { width: number; height: number } {
    return { width: this.width, height: this.height };
  }
}

import { describe, it, expect } from "vitest";
import { GROK_PRIMER, PRIMER_MARKER, isPrimerText, isPrimerSummary } from "../src/grok-primer";

describe("isPrimerSummary (empty-session sweep pre-filter)", () => {
  it("matches grok's primer-derived summaries/titles", () => {
    for (const s of [
      "Grok-Build-VSCode Primer V4 Plan Mode Handling",
      "Grok Build VSCode Hidden Primer v4",
      "Grok VSCode Build Primer v4 Plan Mode Instructions",
      "Grok Build VSCode v4 Primer Plan Mode Setup",
    ]) {
      expect(isPrimerSummary(s)).toBe(true);
    }
  });

  it("does not match real session summaries or empties", () => {
    expect(isPrimerSummary("Generate Elon Musk Desert Image Using Reference")).toBe(false);
    expect(isPrimerSummary("Fix the login bug")).toBe(false);
    expect(isPrimerSummary("")).toBe(false);
    // "primer" alone, without a product/context word, is not enough.
    expect(isPrimerSummary("A primer on CSS grid")).toBe(false);
  });
});

describe("isPrimerText (host-side replay detection)", () => {
  it("matches the current primer message", () => {
    expect(isPrimerText(GROK_PRIMER)).toBe(true);
    expect(isPrimerText(PRIMER_MARKER)).toBe(true);
  });

  it("matches any primer version (v1, v2, … v17) for forward/back compat", () => {
    expect(isPrimerText("[grok-build-vscode primer v1]\n\nold")).toBe(true);
    expect(isPrimerText("[grok-build-vscode primer v2] whatever")).toBe(true);
    expect(isPrimerText("[grok-build-vscode primer v17] some future primer")).toBe(true);
  });

  it("tolerates leading whitespace (chunked replay can prepend a newline)", () => {
    expect(isPrimerText("\n  [grok-build-vscode primer v3] body")).toBe(true);
  });

  it("does not match a normal user message", () => {
    expect(isPrimerText("implement the login form")).toBe(false);
    expect(isPrimerText("")).toBe(false);
    expect(isPrimerText(undefined as unknown as string)).toBe(false);
  });

  it("only matches the marker at the START — a marker pasted mid-message is not a primer", () => {
    // A user who pastes the marker into the middle of their own text must still
    // get a real bubble; the primer is only ever at position 0 of a replayed msg.
    expect(isPrimerText("here is what I copied: [grok-build-vscode primer v3]")).toBe(false);
  });

  it("does not match a near-miss marker (wrong name / no version)", () => {
    expect(isPrimerText("[grok-build-vscode primer]")).toBe(false);
    expect(isPrimerText("[some-other primer v3]")).toBe(false);
  });
});

describe("GROK_PRIMER content (v4 — trimmed to stop pre-turn exploration)", () => {
  it("is marked v4 and starts with the marker", () => {
    expect(PRIMER_MARKER).toBe("[grok-build-vscode primer v4]");
    expect(GROK_PRIMER.startsWith(PRIMER_MARKER)).toBe(true);
    expect(isPrimerText(GROK_PRIMER)).toBe(true);
  });

  // The whole point of v4: an agentic CLI treated the old product paragraph +
  // repo URL as an invitation to go read the workspace before the user's real
  // turn. These assertions lock in that those exploration triggers are gone.
  it("dropped the product/repo paragraph that invited workspace exploration", () => {
    expect(GROK_PRIMER).not.toMatch(/open source repo/i);
    expect(GROK_PRIMER).not.toMatch(/Grok Build VS Code extension/i);
    expect(GROK_PRIMER).not.toMatch(/https?:\/\//); // no URL to chase
    expect(GROK_PRIMER).not.toMatch(/marketplace/i);
  });

  it("dropped 'Acknowledge briefly' (which licensed a verify-by-exploring turn)", () => {
    expect(GROK_PRIMER).not.toMatch(/acknowledge briefly/i);
  });

  it("adds an explicit do-NOT-act constraint and a one-word reply", () => {
    expect(GROK_PRIMER).toMatch(/do not use any tools/i);
    expect(GROK_PRIMER).toMatch(/do not read any files/i);
    expect(GROK_PRIMER).toMatch(/do not search the workspace/i);
    expect(GROK_PRIMER).toMatch(/do not take any action/i);
    expect(GROK_PRIMER).toMatch(/Reply with exactly: ok/);
  });

  it("still teaches the full plan-verdict protocol (the reason the primer exists)", () => {
    expect(GROK_PRIMER).toContain("exit_plan_mode");
    expect(GROK_PRIMER).toContain("[Plan approved]");
    expect(GROK_PRIMER).toContain("[Plan rejected]");
    expect(GROK_PRIMER).toContain("[Plan cancelled]");
    expect(GROK_PRIMER).toMatch(/Do not trust the tool result/i);
  });

  it("flags itself as a hidden system message to keep out of summaries", () => {
    expect(GROK_PRIMER).toMatch(/system message, not a user request/i);
  });
});

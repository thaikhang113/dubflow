// Unit tests for the pure plan-restore state machine — the bit that decides:
//
//   (a) what the per-session "saved plans" log looks like after a new verdict
//       (`appendPlanEntry`), and
//   (b) whether a restored session should come back in Plan mode or Agent mode
//       (`decideRestoreState`), based on the last verdict the user gave.
//
// These are the bugs that surfaced in manual testing and would re-surface
// silently if regressed:
//   - "Rejected plan disappeared on restore" → log was overwritten, not appended.
//   - "Plan text empty in restored card" → the snapshot of plan text was wiped
//     before persist (covered by sidebar wiring; here we just verify the log
//     append preserves whatever text it was given).
//   - "Cancelled session restored into Plan mode" → restore decision was
//     defaulting to Plan when last verdict was unknown / abandoned / approved.
import { describe, it, expect } from "vitest";
import {
  PlanEntry,
  appendPlanEntry,
  countsAsUserBubble,
  decideRestoreState,
} from "../src/plan-restore";

describe("countsAsUserBubble (host↔webview replay-count parity)", () => {
  // The host's replay counter must count exactly what chat.js appendUserChunk
  // bubbles — an asymmetry inflates every post-restore verdict position and
  // the plan/permission cards land at the END of the conversation on the next
  // restore (the accredia stress session's "2 messages at the end").
  it("counts real user messages, including verdicts WITH comments", () => {
    expect(countsAsUserBubble("Show me a plan")).toBe(true);
    expect(countsAsUserBubble("[Plan approved] I don't know what to do.")).toBe(true);
    expect(countsAsUserBubble("[Plan rejected] use sqlite")).toBe(true);
    expect(countsAsUserBubble('<vscode-context note="x">\nfile.ts\n</vscode-context>\n\nRevert that change')).toBe(true);
  });

  it("does NOT count what the webview never bubbles", () => {
    expect(countsAsUserBubble("[Plan cancelled]")).toBe(false);
    expect(countsAsUserBubble("  [Plan approved]  ")).toBe(false);
    expect(countsAsUserBubble("[Plan rejected]\n")).toBe(false);
    expect(countsAsUserBubble("<system-reminder>\n[Request interrupted by user]\n</system-reminder>")).toBe(false);
    expect(countsAsUserBubble("  <system-reminder> Plan mode still active </system-reminder>")).toBe(false);
  });
});

describe("appendPlanEntry", () => {
  it("creates a new list when none exists (undefined → [entry])", () => {
    const entry: PlanEntry = { text: "P1", verdict: "rejected", afterUserMessage: 1 };
    expect(appendPlanEntry(undefined, entry)).toEqual([entry]);
  });

  it("appends to the existing list in chronological order", () => {
    const existing: PlanEntry[] = [
      { text: "P1", verdict: "rejected", afterUserMessage: 1 },
      { text: "P2", verdict: "approved", afterUserMessage: 3 },
    ];
    const next: PlanEntry = { text: "P3", verdict: "abandoned", afterUserMessage: 5 };
    expect(appendPlanEntry(existing, next)).toEqual([...existing, next]);
  });

  it("does not mutate the caller's array (pure)", () => {
    const existing: PlanEntry[] = [{ text: "P1", verdict: "rejected", afterUserMessage: 1 }];
    const frozen = JSON.stringify(existing);
    appendPlanEntry(existing, { text: "P2", verdict: "approved", afterUserMessage: 2 });
    expect(JSON.stringify(existing)).toBe(frozen);
  });

  it("preserves the exact text the caller hands in (regression: lastPlanText was being wiped)", () => {
    const entry: PlanEntry = {
      text: "# TEST PLAN\n\nSimple content for rejection testing.",
      verdict: "rejected",
      afterUserMessage: 2,
    };
    const result = appendPlanEntry([], entry);
    expect(result[0].text).toBe(entry.text);
  });

  it("tolerates entries without afterUserMessage (legacy compat)", () => {
    const entry: PlanEntry = { text: "P1", verdict: "rejected" };
    const result = appendPlanEntry(undefined, entry);
    expect(result[0].afterUserMessage).toBeUndefined();
  });
});

describe("decideRestoreState", () => {
  it("no saved plans → no plan mode, CLI in act mode", () => {
    expect(decideRestoreState([])).toEqual({ planActive: false, cliMode: "default" });
  });

  it("undefined input (legacy session, never persisted) → no plan mode", () => {
    expect(decideRestoreState(undefined)).toEqual({ planActive: false, cliMode: "default" });
  });

  it("last verdict 'rejected' → restore Plan mode (user was mid-planning)", () => {
    expect(decideRestoreState([
      { text: "P1", verdict: "rejected", afterUserMessage: 1 },
    ])).toEqual({ planActive: true, cliMode: "plan" });
  });

  it("last verdict 'approved' → do NOT restore Plan mode (user said go)", () => {
    expect(decideRestoreState([
      { text: "P1", verdict: "approved", afterUserMessage: 1 },
    ])).toEqual({ planActive: false, cliMode: "default" });
  });

  it("last verdict 'abandoned' → do NOT restore Plan mode (this was the Cancel regression)", () => {
    expect(decideRestoreState([
      { text: "P1", verdict: "abandoned", afterUserMessage: 1 },
    ])).toEqual({ planActive: false, cliMode: "default" });
  });

  it("only the LAST verdict matters — earlier ones are ignored", () => {
    // Reject, reject, then approve: user was planning then went ahead.
    expect(decideRestoreState([
      { text: "P1", verdict: "rejected",  afterUserMessage: 1 },
      { text: "P2", verdict: "rejected",  afterUserMessage: 2 },
      { text: "P3", verdict: "approved",  afterUserMessage: 3 },
    ])).toEqual({ planActive: false, cliMode: "default" });

    // Approve, then reject: user re-opened planning after approving an earlier plan.
    expect(decideRestoreState([
      { text: "P1", verdict: "approved", afterUserMessage: 1 },
      { text: "P2", verdict: "rejected", afterUserMessage: 4 },
    ])).toEqual({ planActive: true, cliMode: "plan" });

    // Abandon, then reject: same as above for the gate.
    expect(decideRestoreState([
      { text: "P1", verdict: "abandoned", afterUserMessage: 1 },
      { text: "P2", verdict: "rejected",  afterUserMessage: 2 },
    ])).toEqual({ planActive: true, cliMode: "plan" });
  });
});

describe("appendPlanEntry + decideRestoreState (full lifecycle scenarios)", () => {
  // These are scenario tests that walk the exact state-machine paths the user
  // can produce in the UI. They lock in the high-level invariant: "what the
  // user clicked last is what the restore comes back to".

  it("scenario: user rejects, then closes VS Code → restore comes back in Plan mode", () => {
    let plans: PlanEntry[] | undefined;
    plans = appendPlanEntry(plans, { text: "draft 1", verdict: "rejected", afterUserMessage: 1 });
    expect(decideRestoreState(plans).planActive).toBe(true);
  });

  it("scenario: user rejects then approves → restore comes back in Agent mode", () => {
    let plans: PlanEntry[] | undefined;
    plans = appendPlanEntry(plans, { text: "draft 1", verdict: "rejected", afterUserMessage: 1 });
    plans = appendPlanEntry(plans, { text: "draft 2", verdict: "approved", afterUserMessage: 2 });
    expect(decideRestoreState(plans).planActive).toBe(false);
  });

  it("scenario: user rejects then cancels → restore comes back in Agent mode (no plan-mode lock-in)", () => {
    let plans: PlanEntry[] | undefined;
    plans = appendPlanEntry(plans, { text: "draft 1", verdict: "rejected", afterUserMessage: 1 });
    plans = appendPlanEntry(plans, { text: "draft 2", verdict: "abandoned", afterUserMessage: 2 });
    expect(decideRestoreState(plans).planActive).toBe(false);
  });

  it("scenario: legacy session (never persisted) → restore comes back in Agent mode, no surprise gate", () => {
    expect(decideRestoreState(undefined).planActive).toBe(false);
  });
});

// Pure helpers for the plan-mode persist + restore state machine. Split from
// sidebar.ts so the verdict log and the on-resume decision can be unit-tested
// without mocking vscode, the ACP client, or the filesystem.
//
// Background:
//  - The CLI's `x.ai/exit_plan_mode` treats any response as approval (see
//    research/plan-mode.md). The extension persists each resolved plan locally
//    so the live verdict and the resume view both reflect what the user
//    actually chose, not what the CLI thinks happened.
//  - Plan content + verdict + `afterUserMessage` (count of user messages sent
//    at the moment the plan was resolved) are appended via `appendPlanEntry`.
//  - On resume, `decideRestoreState` returns the plan-gate + CLI-mode the host
//    should restore to, based on the *last* verdict. "rejected" means the user
//    was still planning, so the gate goes back up. Everything else (including
//    no saved plans) leaves the gate down — safer than wrongly restoring plan
//    mode on a session the user already cancelled or approved.

export type PlanVerdict = "approved" | "rejected" | "abandoned";

/**
 * True when a REPLAYED user turn renders a user bubble in the webview. The
 * host's replay counter (`session.userMessageCount`, sidebar.ts's
 * userMessageChunk handler) must count exactly what the webview's
 * appendUserChunk bubbles — persisted plan/permission `afterUserMessage`
 * positions are drained against the webview's own count on the NEXT replay.
 * Any asymmetry inflates the host count, and every verdict persisted after a
 * restore then carries an unreachable position — its card permanently lands
 * at the END of the conversation on later restores.
 *
 * Mirrors chat.js exactly: `<system-reminder>` turns and marker-only plan
 * verdicts ("[Plan cancelled]" with no comment) render no bubble; a marker
 * WITH a comment renders the comment (counts). The primer is handled
 * separately (isPrimerText) by both sides.
 */
export function countsAsUserBubble(text: string): boolean {
  const t = text ?? "";
  if (/^\s*<system-reminder>/.test(t)) return false;
  const m = /^\s*\[Plan (approved|rejected|cancelled)\]\s*/i.exec(t);
  if (m && !t.slice(m[0].length).trim()) return false;
  return true;
}

export interface PlanEntry {
  text: string;
  verdict: PlanVerdict;
  /** Number of user messages sent before this plan was resolved. The resume
   *  view uses this to render the plan card inline with the conversation
   *  rather than at the bottom. Older saved entries may not have it. */
  afterUserMessage?: number;
}

export interface RestoreDecision {
  /** Should the client-side plan gate be raised on restore? */
  planActive: boolean;
  /** Mode to set on the CLI so its view of "am I planning?" matches the gate.
   *  "default" is grok's wire name for act mode (NOT "agent"). */
  cliMode: "plan" | "default";
}

/** Append a resolved plan to the per-session log. `current` may be undefined
 *  for sessions that haven't persisted any plans yet. */
export function appendPlanEntry(current: PlanEntry[] | undefined, entry: PlanEntry): PlanEntry[] {
  return [...(current ?? []), entry];
}

/** Decide what plan-mode state the host should restore to, given the saved log.
 *  Pure: no I/O, no globals. */
export function decideRestoreState(saved: PlanEntry[] | undefined): RestoreDecision {
  if (!saved || saved.length === 0) return { planActive: false, cliMode: "default" };
  const lastVerdict = saved[saved.length - 1].verdict;
  if (lastVerdict === "rejected") return { planActive: true, cliMode: "plan" };
  return { planActive: false, cliMode: "default" };
}

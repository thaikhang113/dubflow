// The extension's "system prompt" to grok — sent once per session (new +
// restored) before the user's first message. Hidden from live chat (no user
// bubble, no agent response shown) but does land in the CLI's session record.
// The CLI bug (`exit_plan_mode` always reports "approved") can't be patched at
// the protocol layer, so we tell grok in plain English to ignore the wire-level
// verdict and read it from the follow-up message.
//
// WHY THIS IS DELIBERATELY MINIMAL (v4): grok-build is an *agentic* CLI — it
// acts on context. The v3 primer carried two things that, combined with that
// agency, turned a meant-to-be-instant primer turn into a 15–40s exploration
// of the workspace BEFORE the user's real message even ran:
//   1. A "## Grok Build VS Code extension … open source repo, issues: <URL>"
//      paragraph. Telling an agent "you're embedded in this developer's
//      open-source extension" is an invitation to go read it. In one captured
//      session the primer turn spent 17.7s reading grok-primer.ts, searching
//      114 workspace files, and reading the primer's own test — all triggered
//      by that paragraph, none of it needed for the plan protocol.
//   2. "Acknowledge briefly so I know you've read this." — that requests a
//      genuine response turn, which an agentic model treats as license to
//      verify-by-exploring.
// The plan-protocol description itself never caused exploration. So v4 keeps
// ONLY the protocol, drops the product paragraph + URL, and replaces "acknowledge
// briefly" with an explicit do-NOT-act / reply-with-one-word constraint. With
// the eager non-blocking primer (sidebar.ensurePrimed) this now runs silently in
// the background the moment a session goes live, so the user never waits on it.
//
// Versioned: bump PRIMER_VERSION whenever the text changes meaningfully so
// future logic (re-sending the primer after compact, migrating older sessions)
// can detect drift. The on-disk session keeps whatever primer was current when
// it started; evolving the primer doesn't rewrite old sessions unless re-primed.

export const PRIMER_VERSION = 4;

/** Marker prefix on every primer message so we can identify it in session
 *  records and skip rendering it on restore. */
export const PRIMER_MARKER = "[grok-build-vscode primer v4]";

/** Matches the marker prefix of any primer version (v1, v2, …) at the start of
 *  a message. The host uses it to recognize the primer when grok replays it as
 *  a user message on restore — mirrors the webview's own PRIMER_PATTERN — so the
 *  session is marked already-primed and the bubble isn't counted toward plan
 *  positions. Version-agnostic so an older on-disk primer still counts as primed. */
export const PRIMER_PATTERN = /^\s*\[grok-build-vscode primer v\d+\]/;

/** True when `text` is (the start of) one of our hidden primer messages. */
export function isPrimerText(text: string): boolean {
  return PRIMER_PATTERN.test(text ?? "");
}

/** True when a grok-generated session summary/title reads like it was derived from
 *  the hidden primer (the first message of every extension session), e.g.
 *  "Grok Build VSCode Primer v4 Plan Mode" or "Hidden Primer v4". grok summarizes
 *  from message #1, so a primer-only session gets one of these titles. Used as the
 *  cheap pre-filter for the empty-session sweep (the authoritative check reads the
 *  chat history); deliberately conservative — it requires "primer" plus a
 *  product/context word so a real session that merely mentions "primer" won't match. */
export function isPrimerSummary(summary: string): boolean {
  const t = (summary ?? "").toLowerCase();
  if (!t.includes("primer")) return false;
  return /grok|vs ?code|plan mode|hidden/.test(t);
}

export const GROK_PRIMER = `${PRIMER_MARKER}

## HIDDEN PRIMER

This is a system message, not a user request. The user cannot see it in the UI. Skip it when discussing previous user messages or summarizing the conversation. It is informational only: **do not use any tools, do not read any files, do not search the workspace, and do not take any action in response to it.**

## Plan Mode

The \`exit_plan_mode\` tool's response is currently unreliable in this CLI version — it always reports "approved" to any client reply, regardless of what the user actually chose in the plan-review UI. **Do not trust the tool result.**

After \`exit_plan_mode\` resolves, end your turn and wait for the NEXT user message. The user's actual verdict will arrive there as a bracketed marker, optionally followed by a comment:

- \`[Plan approved]\` → implement the plan
- \`[Plan rejected]\` → stay in plan mode; if a comment follows, treat it as refinement guidance
- \`[Plan cancelled]\` → exit plan mode; if a comment follows, respond to it normally
- Anything else → treat as a normal user message

The verdict is **always** in the follow-up message, **never** in the tool result.

Reply with exactly: ok`;
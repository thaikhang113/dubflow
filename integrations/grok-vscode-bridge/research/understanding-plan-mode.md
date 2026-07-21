# Understanding Plan Mode in Grok Build (VS Code Extension) — Course

> **Goal of this course**: After completing this material you will have a correct mental model of *why* Plan mode exists, *how* it actually works (the client-side "B+" architecture), and *what* happens on every user action (Approve / Keep planning / Cancel). You will be able to predict behavior, debug surprising states, and explain the design to others.

This is the official **course** companion to the raw research notes in [research/plan-mode.md](plan-mode.md). Work through the sections in order for understanding; treat the research notes as the historical source of truth and reference for deep technical details and probe results.

---

## Lesson 1: Mental Model (The One-Page Explanation)

**Plan mode is a read-only research phase that is *enforced by the extension*, not by the grok CLI.**

When you (or the agent) enter Plan mode:
- Grok is allowed to **read** your workspace freely (`fs/read_text_file`, search tools, etc.).
- Grok is **blocked** from mutating anything inside your workspace.
  - Every `fs/write_text_file` whose target resolves inside the workspace cwd is refused.
  - Every `terminal/create` whose command is not on a curated read-only allowlist is refused.
- The only write that is deliberately allowed is grok writing its own plan to `~/.grok/sessions/<...>/plan.md` (outside your workspace). The extension *snoops* that write so it can show you the plan text.

The CLI still thinks it is in "plan mode" and will eventually emit `x.ai/exit_plan_mode`. **That protocol message cannot be used to reject a plan** (see Lesson 2). The extension therefore ignores the protocol verdict for enforcement and uses its own gate instead.

**Three user verdicts on the plan card produce three different outcomes:**

| Verdict (button)          | Gate after click | What the extension does next                                                                 | Observable result for the user |
|---------------------------|------------------|----------------------------------------------------------------------------------------------|--------------------------------|
| **Approve & implement**   | Lowered          | Drop gate, ask CLI to switch to act mode, then send the follow-up marker `[Plan approved]` (+ the user's comment if any). | Grok starts executing the plan (real writes & commands now succeed). |
| **Reject** ("Keep planning") | Stays up      | Keep gate up, cancel the false-approval turn (suppress its output), then send `[Plan rejected]` (+ the user's comment if any, which also shows as a normal user bubble). | You stay in Plan mode. Grok sees an unambiguous rejection on the wire. |
| **Cancel**                | Lowered          | Drop gate, switch CLI to act mode, send `[Plan cancelled]` (+ the user's comment if any). | You are back in normal Agent mode. Grok's understanding is reset. |

These bracketed markers are not free-form English — they are an explicit **contract** the hidden **primer** (`src/grok-primer.ts`) trained grok to recognize. The verdict is **always** carried by the follow-up message's marker, **never** by the `exit_plan_mode` tool result (which the CLI always reports as "approved"). The primer is sent lazily before the first prompt of new **and** restored sessions (re-sent on restore, not trusted from replayed history); the pure `isPrimerText()` hides it and keeps it out of the plan-position count on replay.

**The fundamental asymmetry (the thing most people get wrong on first encounter):**

- Entering Plan mode **any way at all** (picker click, agent saying "switch to plan mode", session restore) **raises the gate**.
- The gate is **only lowered** by an explicit user action on a plan card (Approve or Cancel) or by the user manually switching to Agent/YOLO.
- The CLI reporting `current_mode_update: "default"` (its name for act mode) does **not** lower the gate. This is deliberate — the buggy `exit_plan_mode` path emits "default" even when the user chose "Keep planning."

If the toolbar button ever says "Agent" but you are still seeing "Plan mode blocked..." notices, the gate is still up. The button label is derived from the client-side `planActive` flag, not from the CLI's last mode announcement.

---

## Lesson 2: Why This Architecture Exists (The Root Cause)

The grok CLI sends an `x.ai/exit_plan_mode` (or `_x.ai/...`) server request when it finishes a planning turn. The extension receives it, shows the nice review card, and the user picks a verdict.

The extension does the protocol-correct thing:
- "approved" → sends a JSON-RPC *result*
- "rejected" / "abandoned" → sends a JSON-RPC *error*

(See `src/acp-dispatch.ts:99-110` and the comment: "Reject and Abandon must be sent as JSON-RPC errors — the CLI treats any successful result as approval regardless of the outcome value.")

**The bug (re-verified on grok 0.2.3 native Windows):** the CLI treats *every* response to `exit_plan_mode` (result *or* error) as approval. It exits plan mode and proceeds to execute the plan anyway.

Because there is no wire-level way for a thin ACP client to say "no, really, don't do it," the only robust solution is to stop trusting the protocol verdict for enforcement and to gate the two calls the agent *cannot avoid* making when it wants to change state:

- `fs/write_text_file`
- `terminal/create`

This is called **Option B+** in the research notes. It is the mirror image of how YOLO is implemented (YOLO auto-approves at the permission layer; Plan blocks at the mandatory fs/terminal layer).

The cost is that the extension now owns a small but security-sensitive policy (the read-only command allowlist). The benefit is that the feature actually does what users expect, even when the agent initiates plan mode via natural language.

---

## Lesson 3: The Two Layers of Enforcement

### Layer 1 — Pure Policy (`src/plan-gate.ts`)

All the decision logic is deliberately pure (no vscode, no fs, no spawn) so it can be unit-tested exhaustively (30+ tests in `test/plan-gate.test.ts`).

Key exported pieces:

- `isInsideWorkspace(target, root)` — the containment check that understands Windows `\\?\` long paths, case-insensitivity on drive letters, POSIX case-sensitivity, and safe `..` traversal rejection.
- `isReadOnlyCommand(command)` — the conservative classifier:
  - Rejects anything containing `>`, `;`, `` ` ``, `&&`, `||`, `$(`, `<(`, `&` at start/end, `{`/`}` (script blocks).
  - For `|` pipelines: *every* stage must itself be a known read-only head.
  - Special cases for `git <subcommand>`, `npm/pnpm/yarn/bun <subcommand>`, and interpreters (`node --version` etc. only).
  - The big `READONLY_HEADS` set (ls, cat, grep, rg, Get-ChildItem, Select-Object, etc.) plus PowerShell read-only cmdlets.
- `shouldBlockWrite(path, ctx)`, `shouldBlockTerminal(command, ctx)`, `shouldRejectPermission(kind, ctx)`
- `isPlanFileWrite(path)` — the carve-out regex that recognizes `/.grok/sessions/.../plan.md` so the extension can allow + snoop it.
- `PLAN_BLOCKED_CODE = -32010` and the two user-facing messages.

When the gate is active, a blocked mutation still lets the agent continue (it receives the JSON-RPC error with the friendly message). The extension also emits `mutationBlocked` so the webview can show a small notice instead of a scary failure.

### Layer 2 — The ACP Choke Points (`src/acp.ts`)

The real handlers live here (the host in `sidebar.ts` only wires up the fs and terminal implementations):

```ts
// fs/write_text_file (approx lines 357-371)
if (isPlanFileWrite(params.path)) emit("planFileContent", ...);
if (shouldBlockWrite(...)) {
  emit("mutationBlocked", ...);
  respondError(id, PLAN_BLOCKED_CODE, PLAN_BLOCKED_WRITE_MSG);
  return;
}
await fsWrite(...); respondOk(...);
```

```ts
// terminal/create (approx lines 373-381)
if (shouldBlockTerminal(...)) {
  emit("mutationBlocked", ...);
  respondError(id, PLAN_BLOCKED_CODE, PLAN_BLOCKED_TERMINAL_MSG);
  return;
}
respondOk(id, terminal.create(...));
```

`exit_plan_mode` handling (lines 416-426) simply emits the `exitPlanRequest` event with whatever plan text it received (usually empty — the real text comes from the snoop).

The `planActive` boolean on `AcpClient` is the single source of truth that the two handlers consult on every request.

---

## Lesson 4: The State Machine in the Host (`src/sidebar.ts`)

This is the most subtle part. The key private state:

- `planActive: boolean` — the real enforcement flag. When true, the gate is up.
- `autoApprove: boolean` — YOLO. Mutually exclusive with planActive.
- `afterTurn?: () => Promise<void>` — deferred action that must run *after* the current planning prompt finishes (because you cannot start a new prompt while one is in flight).
- `suppressPlanReject` — temporary content suppression so the CLI's false "approved" ramble doesn't appear in the UI after a Reject/Cancel.
- `pendingPlanText` / `lastPlanText` — used to capture the plan for the card and for persistence.
- `userMessageCount` + `inUserMessage` — used to assign stable `afterUserMessage` numbers so historical plan cards can be placed inline during replay.

### Core methods

- `setPlanActive(v)` — sets the flag, syncs it to the live `AcpClient`, and posts the derived display mode to the webview.
- `displayMode()` — returns "plan" if `planActive`, else "yolo" if `autoApprove`, else "agent". The toolbar button is derived from this, not from the CLI.
- `setMode(id)` — enforces the three-way mutual exclusion and talks to the CLI only when needed.
- `handleExitPlan(...)` (lines 290-395) — the heart of the feature. See the detailed comment block above the method. It:
  1. Always calls `respondExitPlan` (the protocol reply, which is mostly cosmetic).
  2. Persists the verdict + plan text.
  3. For Approve: lowers gate, schedules the "implement now" follow-up.
  4. For Reject/Abandon: cancels the turn + suppresses content, keeps or drops the gate, schedules the clarifying prompt that compensates for the CLI bug.
- `modeChanged` handler (lines 531-544) — deliberately asymmetric:
  - If the CLI says "plan" → raise gate (covers agent self-initiating).
  - If the CLI says anything else → only refresh the button label. Never auto-lower the gate.
- `persistPlanVerdict` + the call to `decideRestoreState` on resume (lines 696-699) — this is what makes "Keep planning" survive a session close/reopen.

The `afterTurn` pattern exists because `exit_plan_mode` arrives *during* an in-flight `session/prompt`. You must finish responding to the current turn before you can send a new one.

---

## Lesson 5: Session Restore & Plan History

grok only keeps the *latest* `plan.md` on disk for a session. If the user went through two or three planning iterations, earlier plans would be lost.

The extension therefore maintains its own per-session log in VS Code `globalState` (`grok.sessionMeta.<sessionId>.plans`):

```ts
interface PlanEntry {
  text: string;
  verdict: "approved" | "rejected" | "abandoned";
  afterUserMessage?: number;   // how many user messages had been sent when this plan was resolved
}
```

On resume:
- The saved plans are queued before replay starts.
- As user messages are replayed, `drainPlanHistory` inserts the plan cards at the correct points in the conversation.
- `decideRestoreState` looks at the *last* verdict:
  - `"rejected"` → restore `planActive=true` and tell the CLI to be in plan mode.
  - Anything else (including no history) → gate down, normal act mode.

This is why a session you "Kept planning" on will come back with the gate already raised, even if the CLI's own mode state during replay would have suggested otherwise.

The pure helpers live in `src/plan-restore.ts` (15 unit tests).

---

## Lesson 6: Webview Surface (`media/chat.js`)

Two kinds of plan cards exist:

- **Live card** (`addPlanCard`, triggered by `exitPlanRequest`): shows the three buttons and an optional feedback textarea whose comment is sent for **any** of the three verdicts (Approve, Reject, or Cancel) — it lands as a normal user bubble and is appended after the bracketed marker on the wire — and resolves in place after the user clicks.
- **History card** (`addPlanHistoryCard`, triggered by `planHistoryQueue` during replay): read-only, shows the old verdict label if we have one.

Notices (`planNotice`, `planBlocked`) are simple one-line callouts that appear in the stream when the gate silently refuses something or when the host wants to tell the user "you are still in plan mode."

The mode popover (`openModePopover`) no longer disables the Plan entry (it used to, before B+ shipped).

---

## Lesson 7: How to Experiment Safely

### Without a real grok binary
- In a running extension host (F5), call the development helper:
  ```ts
  // from the debug console or by temporarily wiring a command
  sidebar.debugShowDummyPlan();
  ```
  This posts a realistic plan card and flips the mode button so you can click all three verdicts and watch the `afterTurn` behavior without ever spawning a CLI.

### With the real CLI (non-destructive)
The three scripts in `research/` are designed for this:
- `plan-probe.cjs` — single-turn observation (logs every server→client call).
- `plan-reject-probe.cjs` — full reject → feedback → second planning turn.
- `plan-gated-probe.cjs` — same flow but with the *shipped* `out/plan-gate.js` policy active.

They ACK writes without touching disk and are safe to run in a temp directory.

### Unit & DOM tests (always safe)
```bash
npm test
# or focused:
npx vitest run test/plan-gate.test.ts test/plan-restore.test.ts test/plan-card.dom.test.ts
```

These give you high confidence that the policy and the card rendering match the documented behavior.

---

## Lesson 8: Common Misconceptions & Debugging Tips

- **"The mode button says Agent but I'm still blocked"** — the gate (`planActive`) and the CLI's reported mode are deliberately allowed to be out of sync for safety. The button derives from the gate.
- **"Grok just wrote a file while I was in Plan mode"** — either the write was to its own `plan.md` (outside the workspace) or the gate was not actually up at that moment.
- **"I rejected the plan but Grok still started implementing"** — this should no longer happen with the shipped B+ gate. If it does, you have found a bug in the containment or the allowlist.
- **"Why did a second plan card appear after I clicked Reject?"** — because we sent a clarifying prompt on the wire. That prompt produces one extra agent turn (usually a short acknowledgment) so that grok's internal state matches reality.
- **PowerShell pipeline notice** — the current allowlist is deliberately strict. A command like `Get-ChildItem -Recurse | Select-Object ...` may be blocked on the `|` if the right-hand side isn't recognized as read-only in that context. This produces one cosmetic notice per plan in practice and does not derail the agent (it falls back to native `read_file` / `list_dir` / `grep` tools).

---

## Lesson 9: Maintenance Notes

- The read-only command allowlist, the three verdict behaviors, the restore decision table, and the clarifying prompts sent on the wire are the parts most likely to need corresponding doc updates.
- Any PR that touches `plan-gate.ts`, `plan-restore.ts`, `handleExitPlan`, or the `modeChanged` handler should update this course (and the relevant tests).
- Line numbers in this document are "as of v1.2.0 / research notes dated 2026-05-28". Treat them as helpful pointers, not eternal truths.
- This course deliberately avoids duplicating large excerpts from `research/plan-mode.md`. Link to it for the full historical narrative and probe logs.

---

## Quick Reference — File Anchors

| Concept                        | Primary location(s)                                      |
|--------------------------------|----------------------------------------------------------|
| Policy decisions               | `src/plan-gate.ts` (entire)                              |
| Restore decision table         | `src/plan-restore.ts:45-50`                              |
| Gate enforcement points        | `src/acp.ts:364-366`, `375-377`                          |
| The three verdicts + deferral  | `src/sidebar.ts:290-395` (`handleExitPlan`)              |
| Gate asymmetry on mode updates | `src/sidebar.ts:533-544`                                 |
| Session restore override       | `src/sidebar.ts:696-699`                                 |
| Plan card rendering            | `media/chat.js:1256-1353`                                |
| Wire response shapes           | `src/acp-dispatch.ts:99-110`                             |
| Full history & rationale       | `research/plan-mode.md` (especially § Resolution)        |

---

**Congratulations — you have completed the course.**

If you can explain, in your own words, why the gate is raised on agent-initiated `current_mode_update: plan` but never lowered on `current_mode_update: default`, and why the extension sends an extra clarifying prompt after a user clicks "Reject", you have the model the original authors intended.

### Further reading & practice
- [research/plan-mode.md](plan-mode.md) — the original deep research + probe findings
- The five `test/plan-*.test.ts` files (plan-card, plan-gate, plan-history-restore, plan-restore, plan-review) — executable specification of the intended behavior
- `CLAUDE.md` (the one-paragraph ACP surfaces summary)
- Try the `debugShowDummyPlan()` helper and the research probes for hands-on experience

Happy planning (and safe rejecting).
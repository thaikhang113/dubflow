# Plan mode — why it's disabled, and why disabling it isn't enough

Research notes. Status as of `grok` 0.2.3 (native Windows), extension v1.1.0, 2026-05-27.

> **Resolved (2026-05-28): Option B+ shipped.** Plan mode is re-enabled and enforced
> client-side at the two *mandatory* server→client choke points — `fs/write_text_file`
> and `terminal/create` — rather than the leaky permission layer. See
> [§ Resolution](#resolution-what-we-built) below for the empirical probe findings that
> drove the design and the final architecture. The analysis above is preserved as the
> problem statement.

## TL;DR

1. **The plan-mode bug is in the grok CLI, not in this extension.** `x.ai/exit_plan_mode`
   treats *any* client response — JSON-RPC result **or** error — as approval. There is
   no wire-level way for the client to reject a plan.
2. **Disabling Plan in the dropdown is cosmetic.** It only gates the picker's own click
   handler. The CLI owns mode state and will switch itself into plan mode — most reliably
   when you *ask Grok to*. When that happens we faithfully reflect it and then inherit the
   broken exit path. Observed in practice.
3. **We can't fix this as a thin client.** Plan-mode bookkeeping lives in the CLI by
   design. The only real levers are (a) wait for xAI to wire the rejection code path, or
   (b) stop being thin for this one feature and enforce plan/act ourselves via the
   permission gate.
4. **Kilo Code doesn't hit this** because it isn't an ACP client at all — it owns its own
   agent loop and implements "Architect" mode itself, so no provider can override its
   plan→act decision.

## Background: the thin-client contract

This extension is a thin ACP client over `grok agent stdio`. Per `CLAUDE.md`:

> Thin client — all session state, MCP servers, subagents, memory, and **plan-mode
> bookkeeping live in the CLI**.

That buys us feature-parity with the CLI for free, but it means mode state and the
plan→act transition are owned by grok. We can drive them and reflect them; we cannot
change their semantics.

## Root cause: `x.ai/exit_plan_mode` ignores rejection

When the agent finishes planning, the CLI sends an `x.ai/exit_plan_mode` request to the
client and waits for a verdict. We handle it correctly:

- Receive the request and surface it — `src/acp.ts:382-391` (`x.ai/exit_plan_mode` /
  `_x.ai/exit_plan_mode` → emit `exitPlanRequest`).
- User picks a verdict in a chat card → `exitPlanAnswer` → `respondExitPlan`
  (`src/sidebar.ts:424-425`, `src/acp.ts:246-249`).
- We even use the protocol-correct shape for "no": **approved** goes back as a JSON-RPC
  *result*; **rejected/abandoned** go back as JSON-RPC *errors* —
  `src/acp-dispatch.ts:99-110`:

  ```ts
  // Reject and Abandon must be sent as JSON-RPC errors — the CLI treats any
  // successful result as approval regardless of the outcome value.
  ```

**The bug:** grok's handler treats the error response the same as a result — it exits
plan mode and executes the full plan regardless. Re-verified against 0.2.3 (2026-05-27):
rejecting with a JSON-RPC error still ran the plan. So there is currently **no response we
can send that means "don't do it."**

Because of that, enabling a Plan UI that silently approves every plan is worse than not
shipping it, so Plan is marked disabled in the picker — `media/chat.js:88-100`
(`MODE_META.plan.disabled = true`, with a `disabledNote` explaining why).

## The part the disable doesn't cover: agent-initiated plan switches

The `disabled` flag gates exactly one thing — the picker's manual click handler:

```js
// media/chat.js:539-544
el.onclick = (e) => {
  e.stopPropagation();
  if (meta.disabled) return;   // ← the entire effect of `disabled`
  vscode.postMessage({ type: "setMode", modeId: id });
  closePopovers();
};
```

It does **nothing** to stop the CLI from entering plan mode on its own. The mode is
authoritative on the CLI side and propagates *to* us:

```
grok CLI  ──current_mode_update──►  acp-dispatch.ts:61-62  (→ modeChanged)
                                ──►  acp.ts:309-311         (set currentModeId, emit)
                                ──►  sidebar.ts:253-255     (post modeChanged to webview)
                                ──►  chat.js:1368-1370      (updateModeBtn — reflect it)
```

There is **no guard anywhere on this path**. `chat.js:140-145` `updateModeBtn("plan")`
will happily render "Plan mode" on the toolbar, and we're now in plan mode through a door
the dropdown never controlled.

**Observed trigger:** asking Grok in natural language to switch to plan mode. Grok flips
its own mode server-side, emits `current_mode_update: plan`, we reflect it — and the next
`x.ai/exit_plan_mode` lands us on the broken approval path. The dropdown being "disabled"
is irrelevant; the user never touched the dropdown.

So the true exposure is: **we can end up in plan mode without the picker, and once there,
we cannot reject the plan.** The UI disable addresses the manual entrance and leaves the
CLI-driven entrance wide open.

## Why Kilo Code doesn't have this problem

Kilo Code (Cline/Roo family) is a **thick orchestrator, not an ACP client**. It talks to
model APIs directly (xAI / OpenRouter / 500+ models) and ships its own modes — Architect
(plan), Coder, Debugger. "Supports Grok" just means it can point at a Grok *model*; it
never touches grok's CLI or its `exit_plan_mode` feature.

| | grok-build-vscode | Kilo Code |
|---|---|---|
| Talks to | `grok` CLI over ACP | model API directly |
| Owns the agent loop | ✗ grok does | ✓ Kilo does |
| Plan mode lives in | grok CLI | the extension |
| Who decides plan→act | the model/CLI (broken) | Kilo's own UI gate |

In Kilo, Architect mode is enforced client-side: restrict the toolset to read-only while
planning, and gate the transition to acting on its *own* button. The model never sends an
"exit plan mode" signal a provider can mishandle, so a provider bug can't override it.

## Options

### A. Wait for xAI to fix the CLI

Keep the thin-client design. Re-enable Plan once `exit_plan_mode` honors a JSON-RPC error
(or an explicit `outcome: "rejected"`) by staying in plan mode / not executing. Lowest
effort, no control over timeline, and **does not address agent-initiated switches** until
the CLI also stops auto-approving.

### B. Enforce plan/act client-side (mirror of YOLO)

Stop being thin for this one feature. We already have the exact inverse machinery: YOLO is
`autoApprove = true` (auto-allow every `session/request_permission`, `src/sidebar.ts:140-144`).
A client-enforced plan gate is the mirror:

- Track an `inPlan` flag.
- While `inPlan`, **auto-reject** (or hold) every `session/request_permission` whose tool
  kind is `edit`/`terminal` — the agent can read and think, but cannot mutate.
- Let the agent produce the plan as text. Release the gate only on an explicit user
  "Proceed."
- Because rejection happens at the *permission* layer (which works) rather than the
  *exit_plan_mode* layer (which doesn't), we never depend on the broken path.

This is the only option that also neutralizes the agent-initiated switch: even if grok
flips itself into plan mode, the gate decides whether anything executes — not
`exit_plan_mode`.

Cost: a real departure from the pure thin-client model, and we own the gate's correctness.

### C. Minimal stopgap: refuse agent-initiated plan switches

In the `modeChanged` handler (`src/sidebar.ts:253-255`), if the incoming mode is `plan`,
immediately call `client.setMode("agent")` to force back, and surface a notice. Cheap, and
closes the "ask Grok to switch" hole today. Downside: fights the CLI's state machine and
may produce a visible flicker / race; doesn't give us a *working* plan mode, just prevents
the broken one. Reasonable as a guard until A or B lands.

## Code reference index

| What | Location |
|---|---|
| `exit_plan_mode` request received → `exitPlanRequest` | `src/acp.ts:382-391` |
| Verdict sent back to CLI (`respondExitPlan`) | `src/acp.ts:246-249` |
| Verdict wire shape (approve=result, reject/abandon=error) | `src/acp-dispatch.ts:99-110` |
| `current_mode_update` → `modeChanged` (route) | `src/acp-dispatch.ts:61-62` |
| `modeChanged` emit + `currentModeId` (client) | `src/acp.ts:309-311` |
| `setMode` over ACP (`plan`/`agent`) | `src/acp.ts:211-216` |
| `setMode` (yolo client-side; plan/agent → CLI) | `src/sidebar.ts:140-152` |
| `modeChanged` forwarded to webview — **no guard** | `src/sidebar.ts:253-255` |
| `exitPlanAnswer` → `respondExitPlan` | `src/sidebar.ts:424-425` |
| `MODE_META.plan.disabled = true` + note | `media/chat.js:88-100` |
| Picker click gate (`if (meta.disabled) return`) | `media/chat.js:539-544` |
| Webview reflects mode — **no guard** | `media/chat.js:1368-1370` |

---

## Resolution: what we built

We took **Option B**, but moved the enforcement point. Option B as written gates at
`session/request_permission` — but that layer is *advisory*: in Agent mode the CLI skips
the permission prompt entirely for edits it judges non-sensitive, so a permission-layer
gate leaks. Instead we gate at the two requests the agent *cannot* avoid making to touch
anything: every file write goes through `fs/write_text_file`, every command through
`terminal/create`. Both are mandatory server→client calls we already implement. Call this
**B+**.

### Empirical probe (the thing that settled the design)

Before writing the gate we drove a real `grok agent stdio` (0.2.3, native Windows) through
a plan-mode turn and logged every server→client call without writing anything to disk
(`research/plan-probe.cjs`). Findings:

1. **A plan-mode turn never wrote inside the workspace.** It issued `fs/read_text_file`
   and internal search/tool calls, then wrote its plan to
   `~/.grok/sessions/<urlencoded-cwd>/<id>/plan.md` — **outside** the workspace. So the
   user's earlier hunch ("isn't the plan itself a file?") was right, and it's why the gate
   is *workspace-scoped containment*, not "block all writes": blocking everything would
   break grok's own plan persistence.
2. **`exit_plan_mode` arrives with `planContent: null`.** The plan text isn't in the
   request. We recover it by snooping the `plan.md` write (`isPlanFileWrite` →
   `planFileContent` event → `lastPlanText`) so the review card can show the plan.
3. **The turn ends after `exit_plan_mode`.** Approval doesn't auto-continue into
   execution, so on approve we drop the gate and send a follow-up "implement it now"
   prompt.
4. Re-confirmed the original bug: any response to `exit_plan_mode` (result *or* error) is
   treated as approval. That's now **harmless** — the gate, not the protocol verdict,
   decides whether anything lands. "Keep planning" simply leaves the gate up.

### Architecture (mirror of YOLO)

| | YOLO | Plan (B+) |
|---|---|---|
| Client flag | `autoApprove = true` | `planActive = true` |
| Effect | auto-allow every permission | block workspace writes + mutating commands |
| Enforced at | `session/request_permission` | `fs/write_text_file` + `terminal/create` |

- **Policy is a pure module** — `src/plan-gate.ts`, 38 unit tests in
  `test/plan-gate.test.ts` covering Windows long-path prefixes, case-insensitive
  containment, sibling-prefix false positives, `..` traversal, the read-only command
  allowlist (git/npm subcommands, interpreter `--version` only), chaining/redirection
  metacharacters, and the plan.md carve-out.
- **The gate is one of TWO enforcement pillars (since v1.4.x).** Alongside the gate, a
  hidden **primer** (`src/grok-primer.ts`) is sent before the user's first prompt
  instructing grok to disregard the always-"approved" `exit_plan_mode` result and read
  the real verdict from the *next* message as a bracketed marker — `[Plan approved]` /
  `[Plan rejected]` / `[Plan cancelled]` (+ optional comment). The gate blocks workspace
  mutation; the primer aligns grok's own behavior. The primer is sent lazily (first
  prompt of new **and** restored sessions, re-sent on restore — not trusted from replayed
  history). See [research/understanding-plan-mode.md](understanding-plan-mode.md).
- **acp.ts** gates the two handlers and emits `mutationBlocked` / `planFileContent`.
- **sidebar.ts** owns `planActive`, mutual exclusivity with YOLO, agent-initiated-plan
  sync (closes the Option-C hole for free — entering plan mode *any* way raises the gate),
  permission auto-reject while planning, and the approve→implement / keep-planning flow.
- **Read-only shell stays allowed while planning** (`git status`, `ls`, `cat`, …) so the
  agent can still explore; anything that could mutate is blocked and surfaced as a notice.

### Live validation of the reject-with-feedback flow (2026-05-28)

Two further probes drove real `grok` 0.2.3 end-to-end with the *actual flow the
extension now ships*, not just the original single-turn observation:

- `research/plan-reject-probe.cjs` — plan turn → respond to `exit_plan_mode` (the
  unavoidable "approved") → re-assert `setMode("plan")` → send the exact
  "Don't implement yet — revise…" feedback prompt → observe a second turn. ACKs
  everything (raw behavior).
- `research/plan-gated-probe.cjs` — same flow but wires in the **shipped policy**
  (`out/plan-gate.js`) and returns the real `PLAN_BLOCKED_CODE` error when the gate
  blocks, so we see what the *user* would actually experience.

Findings (consistent across runs):

1. **The reject→revise loop is iterable.** A *second* `exit_plan_mode` arrives after
   the feedback-driven revision (`exit_plan_mode count: 2`). Both turns end at
   `end_turn`; neither auto-executes.
2. **Re-asserting `setMode("plan")` mid-conversation succeeds.** Observed mode
   sequence each turn: `plan → default → plan` — the `default` is the false-approve
   flip, which our *asymmetric* `modeChanged` handler deliberately ignores (never
   lowers the gate). Matches the design exactly.
3. **grok never attempts a workspace-mutating write or command while planning** —
   in every run, *zero* workspace writes and *zero* mutating terminal commands. It
   only writes its own `plan.md` (outside the workspace, allowed) and reads via
   native tools. So the write-gate's mutation count is 0 in practice; it's pure
   defense-in-depth.
4. **The gate is quiet in practice, even on native Windows.** The earlier concern —
   that the POSIX-flavored read-only allowlist would block grok's PowerShell
   exploration and flood the user with notices — did **not** materialize. With the
   gate live, grok issues *one* recursive `Get-ChildItem … | Select-Object …`
   listing (blocked by the `|` metacharacter), then **routes around it via native
   `read_file`/`list_dir`/`grep`** (which go through `fs/read_text_file`, never
   gated) and completes planning normally. Net: ~**1 blocked-command notice per
   plan**, no derailment.

Known residual UX wart: that single recurring "Plan mode blocked a command:
`Get-ChildItem -Recurse …`" notice is harmless but can puzzle. Two non-shipped
options if it grates: (a) allow read-only PowerShell pipelines (requires permitting
`|` between read-only stages — more parsing, slightly more risk), or (b) soften the
notice copy to read as expected. Left as a deliberate, safe default: strict gate,
one cosmetic notice.

### Probe reproduction

`research/plan-probe.cjs` (single-turn observation), `research/plan-reject-probe.cjs`
(reject→revise flow, raw), and `research/plan-gated-probe.cjs` (reject→revise flow
with the shipped policy enforced) are all kept as runnable reproductions
(`node research/<file>`, need a local `grok` binary; log to stderr). All ACK writes
without touching disk, so they're non-destructive. `research/plan-probe.log` is a
captured run of the original.

# Grok Build CLI over ACP — field feedback from a thin client

Feedback for the Grok Build CLI team from building **grok-build-vscode**, a VS Code/Cursor
sidebar that is a deliberately thin ACP client for `grok agent stdio`. Everything below is
**evidence-based**: wire captures from real sessions (`test/fixtures/composer-subagent-session.jsonl`),
standalone probes (`research/*.cjs`), and a pre-release live suite (`scripts/live-tests.cjs`)
that re-verifies the load-bearing shapes against the real binary. Deep-dives live in
`research/*.md`; this document is the summary an upstream engineer can act on.

**Basis:** grok CLI **0.2.93** (native Windows, stable channel), extension **v1.5.6**, 2026-07-11.
The grok-build-family findings were re-verified against **Grok 4.5** (`grok-4.5`) — now the
default model of that family. **Grok Build** (`grok-build`) is still present for some
accounts/builds, so its observations below remain valid; where the two differ (context window,
`set_model` echo) both are called out. See **§5** for the Grok 4.5 verification run (full live
suite + probes; Composer 2.5 re-verified alongside).

---

## 1. The two agent families behave differently on the wire

Models belong to *agent types* — `grok-build`/`grok-build-plan` vs the `cursor` agent that owns
the Composer models. A client that only tested one family breaks on the other:

| Surface | grok-build agent (Grok 4.5 / Grok Build, `grok-build-plan`) | cursor agent (Composer 2.5) |
|---|---|---|
| Context window (`_meta.totalContextTokens`) | **Grok 4.5: 500K** · **Grok Build: 512K** | 200K |
| Delegation tool | `spawn_subagent` (`_meta["x.ai/tool"].name`) | `Task` |
| `subagent_type` value style | `general-purpose` (kebab) | `generalPurpose` (camel) |
| Delegation completion | Same-id `tool_call_update`, `status:"completed"`, structured `rawOutput.SubagentCompleted` (output, `tool_calls`, `turns`, `duration_ms`, `resume_from_hint`) | A **third, untitled** update (`title:""`, **no `_meta`**), `rawOutput {type:"Text", text}` — **no duration anywhere on the tool channel** |
| Background delegation | `background:true` → instant "started" ack, real result later via `get_command_or_subagent_output` (`TaskOutput.Result` with `task_id`, `duration_secs`, `output`) | not observed |
| Tool-call ids | `call-<uuid>-<n>` | `call-<uuid>-composer_call_<suffix>` — the short suffix **repeats across calls**; only the full id is unique |
| Tool titles | verb-style ("List \`src/…\`") + tool name on spawn | frequently the raw user content (a Grep is titled with its search pattern) |
| `session/set_model` echo | **Grok Build:** versioned id (`grok-build-0.1`) not in `availableModels` · **Grok 4.5:** clean (`{"model":{"Ok":"grok-4.5"}}`, resolvable) | same class of issue |
| Cross-agent switch | `MODEL_SWITCH_INCOMPATIBLE_AGENT` after the first turn (agent locked at spawn) | same |

**Ask:** treat the wire contract as one product across agents — same tool naming, same
completion shape (structured `rawOutput` with duration), same id style — or document the
differences per agent type.

---

## 2. What doesn't work — and what we had to build around it

Ordered roughly by how much client code each one cost.

### 2.1 Plan mode: `x.ai/exit_plan_mode` cannot be rejected
Any client response — JSON-RPC **result or error** — is treated as approval (re-verified
on 0.2.3; the workaround remains required and covered by the 0.2.93 live gate;
`research/understanding-plan-mode.md`). There is no wire-level "keep planning."
Consequences pile up:
- The request arrives with `planContent: null`, so the plan text isn't even in the request —
  we snoop grok's own `plan.md` file write to recover it.
- After we respond, the unblocked planning turn streams contentless filler ("I'll wait for
  your verdict…") that grok does **not** persist to history but **does** stream live.
- `current_mode_update: "default"` fires even when the user chose to keep planning.

Our workaround is a whole subsystem: a client-side write/terminal gate (`src/plan-gate.ts`)
enforced at the mandatory `fs/write_text_file` / `terminal/create` choke points, plus a hidden
**primer** message teaching the model to ignore the bogus tool result and read
`[Plan approved]`/`[Plan rejected]`/`[Plan cancelled]` from the next user message. The primer
itself then causes secondary problems (see 2.6).
**Ask:** honor a rejection (error or an explicit outcome) — this single fix collapses the
primer, the gate, the filler suppression, and half of section 2.6.

### 2.2 Slash commands: dispatch requires position 0, and TUI-only commands are advertised
- A slash command dispatches **only** when it starts the prompt's text block. Editor-injected
  context in front silently degrades `/compact` into a plain LLM turn — in our probe the
  "compact" **grew** the context 6× (`research/compact.md`). Trailing content is fine, so we
  re-order every send; but nothing over the wire tells a client this rule exists.
- `/always-approve` is advertised over ACP but mutates the **global** `config.toml` — a sticky
  cross-session side effect a sidebar can neither show nor undo per-session. We hide it.
- `/context` is advertised but renders only in the CLI's own TUI — over stdio it streams
  nothing. We hide it too (`/session-info` is the working equivalent).

**Ask:** dispatch commands regardless of position (or accept a structured command field), and
don't advertise commands that are TUI-only or config-mutating on a per-session protocol.

### 2.3 Context accounting: the client can't know the truth when it matters
- The prompt result's `_meta.totalTokens` is **0** for both `/session-info` (context untouched)
  and `/compact` (context shrunk, not emptied) — a placeholder, never a measurement. The other
  fields on a compact turn are a stale echo of the *previous* turn.
- A native `/compact` streams **no content at all** — the turn ends blank with no worked-signal.
- The persisted `signals.json` (`contextTokensUsed`) is recomputed only when the **next
  inference turn ends** — never at the compact turn's own end (probe:
  `research/signals-refresh-probe.cjs`). Right after "compact finished" the true size exists
  nowhere a client can read…
- …except in `/session-info`'s **reply prose**. Our fix is a hidden CLI-local `/session-info`
  turn whose text we scrape with a regex (`**Context:** N / M tokens`). That is as fragile as
  it sounds.
- The ACP `usage_update` notification (the RFD's standard channel for exactly this) is never
  emitted.

**Ask:** emit `usage_update` (or at minimum a truthful `totalTokens`) at the end of `/compact`
and in the `session/load` response. Never report placeholder zeros.

### 2.4 Subagents: three completion dialects, lifecycle events that never ship, titles that lie
- The `subagent_spawned`/`subagent_finished` lifecycle events (method `_x.ai/session/update`)
  are **written to `updates.jsonl` but never transmitted to the ACP client** (live-verified:
  zero arrive while the log fills). They carry exactly what the UI wants — duration_ms,
  tokens_used, the child's output. We route them anyway, hoping.
- Completion shape differs by agent (see §1) and by mode: a `background:true` spawn reports
  `status:"completed"` **immediately** with a "Subagent started in background." ack — the
  real result arrives minutes later on the poller. "Completed" that isn't.
- The child's clean output is triple-wrapped in envelope text (`<subagent_meta>`,
  `<subagent_result>`, "This is the output of the subagent:", a trailing
  "Agent ID: … (resume …)" hint) even though the same output exists structured in
  `rawOutput`.
- Tool titles embed user content: a Grep **for** `spawn_subagent` is titled exactly
  `spawn_subagent`. Only `_meta["x.ai/tool"].name` tells the truth (that field is excellent —
  see §4). The poller's own name (`get_command_or_subagent_output`) contains "subagent" while
  not being a delegation.
- Each child persists as a **top-level sibling session** in the store; clients must filter
  `session_kind:"subagent"` or every delegation adds a junk row to session history.

**Ask:** transmit the lifecycle events; make "completed" mean completed; keep the envelope out
of the text block (the structured `rawOutput` is enough); put `x.ai/tool` meta on every call.

### 2.5 Capabilities and media: the flags don't match reality
- `initialize` advertises `promptCapabilities.image: false`, but inline `{type:"image"}`
  blocks **work** — the model sees the pixels (verified since 0.2.87). A client that trusts
  the flag disables a working feature; we ship with no gate and a live test that fails the day
  the flag flips, in either direction.
- Generated media (`/imagine`, `/imagine-video`) is not returned as an ACP `image`/
  `resource_link` block — the file path is embedded in a `text` block, as JSON on
  Linux/macOS and as human **prose** on native Windows (with `\\?\` extended-length
  prefixes). We parse prose to find pictures.
- A pasted image is copied into `~/.grok/sessions/<…>/assets/` and that internal path is
  surfaced to the model — which then tries to `Read` the binary and fails, polluting the
  transcript. We bake a "do not Read" hint into every image tag.
- An image the CLI judges too small is silently dropped, leaving the model hunting the
  workspace for an attachment it never received. No error reaches the client.

**Ask:** truthful capability flags; media as structured content blocks; don't surface internal
asset paths to the model; error on dropped attachments.

### 2.6 Session catalog and restore: private storage becomes a client API
- Grok's ACP surface exposes `session/new` and `session/load`, but no list, search, rename,
  or delete operations. We enumerate private session directories, parse `summary.json`, infer
  recency from file mtimes, synthesize live sessions before the CLI flushes them, and maintain
  our own pagination, cache, and rename metadata. A client should not need to treat the CLI's
  on-disk implementation as a public API just to render session history.
- `session/set_model` echoes a **versioned id** (`grok-build-0.1`) that isn't in
  `availableModels` and carries no name or context window — still the case on **Grok Build**.
  **Grok 4.5** echoes the clean requested id (`grok-4.5`, resolvable), so the defect is
  per-model within the same agent family; the `resolveModelId` fallback stays for Grok Build,
  older sessions, and the composer agent (see §5).
- The agent type locks after the first turn; switching model families requires a full session
  restart choreographed by the client (`MODEL_SWITCH_INCOMPATIBLE_AGENT`).
- `session/load` does not replay resolved `request_permission`s (we persist and re-inject
  them) and replays `<system-reminder>` turns and protocol markers as user messages a UI must
  know not to render.
- grok titles the session from message #1 — which for us is the hidden primer — so every
  session was named "…Primer v4 Plan Mode…" until we forced display names client-side. Empty
  primer-only sessions accumulate on disk (we sweep them). `num_messages` in `summary.json`
  can be wildly inflated by one agentic turn. `chat_history.jsonl` wraps prompts in
  `<user_query>` — except when it doesn't (slash commands arrive unwrapped).
- Live prompts echo back as `user_message_chunk` since 0.2.33 (they didn't before) —
  undocumented behavior changes like this are how duplicate-bubble bugs are born.

Most of this section is downstream of the primer, which is downstream of 2.1.
**Ask:** expose a paginated `session/list` plus rename/delete operations, returning stable
metadata such as title, updated time, workspace, model, agent type, and session kind. Keep
restore replay free of internal protocol messages and include resolved interaction state.

### 2.7 Session configuration is partly out of band
- Effective permission mode is invisible over ACP. A global or project
  `permission_mode = "always-approve"` silently changes every session's behavior, so we read
  `config.toml` ourselves to avoid displaying a false "Agent" state. The client cannot disable
  that setting for one session.
- Reasoning effort is only a process-start flag (`--reasoning-effort`). Changing it requires
  killing the agent process and restoring or replacing the session; `session/new` and
  `session/load` do not report the effective value.

**Ask:** return effective permission mode and reasoning effort from `session/new` and
`session/load`, and provide session-scoped setters where supported.

### 2.8 Transport/platform (historical but instructive)
- Windows builds 0.2.61–0.2.70 didn't read stdin until **EOF** — a persistent ACP client hung
  forever on `initialize` (later builds: on `session/new`). We still carry a version pin +
  downgrade machinery. Regression tests for "read as lines arrive" would prevent a recurrence.
- `grok update` fails while any grok process (including backgrounded subagent children) holds
  the binary — clients must kill process *trees* and retry.
- `x.ai/ask_user_question` (and `exit_plan_mode`) also appear under a `_x.ai/` prefix; the
  response schema (`outcome:"accepted"` required, empty ACK rejected) had to be recovered from
  strings in the binary. Documentation would have saved a probe.

### 2.9 Terminal commands: the shell is the client's, but the agent writes for another one
In ACP mode grok never runs shell commands itself — it hands each to the client over
`terminal/create`, so the host shell is the **client's** choice. Two problems follow on Windows
(added v1.5.13; issue #46):

- **The agent writes bash-flavored commands even against a PowerShell host.** We run the agent's
  commands under PowerShell on Windows to match the standalone CLI — users expect their PowerShell
  profile functions and pipelines (`… | Format-List`) to work, which they can't under cmd.exe. But
  grok, in ACP mode, still emits POSIX-subshell idioms like `(cd dir ; cmd)` — invalid in
  PowerShell (`( )` is a grouping *expression*, not a statement list; it errors *"Missing closing
  ')'"*), even while using PowerShell cmdlets (`Get-ChildItem`, `$env:`) in the same batch.
  Standalone grok "just works" under PowerShell, so ACP-mode generation is *worse* than standalone.
  The agent self-recovers by retrying with `Set-Location dir; cmd`, but each miss is a wasted tool
  call + model turn — the exact retry cost #46 set out to remove. A client can't safely rewrite the
  agent's commands. **Ask:** tell the agent the client's shell (or let the client advertise it in
  `initialize`), or generate PowerShell-native syntax on a Windows host as the standalone CLI does.
- **The two agents use different command-execution models, and the client output surface differs.**
  grok-build **delegates** every shell command over `terminal/create` (the client runs it and
  captures stdout). The cursor agent (Composer 2.5) instead runs commands in its **own CLI-side
  persistent shell** — it never sends `terminal/create`; the result rides the completed
  `tool_call_update` (`rawOutput` = `{output, exit_code, command, truncated, current_dir, …}`,
  "Shell state persists for subsequent calls"). So a client that renders command output from the
  `terminal/*` capture gets nothing for Composer rows and must *also* read the completed update's
  `rawOutput`, matched by `toolCallId`. Two consequences worth flagging: (a) **Composer completes a
  batch OUT of issue order** (verified: 10 parallel read-only commands finished 1,2,7,6,10,8,5,3,9,4
  by call#), so any order-based correlation (FIFO) misattributes — `toolCallId` is the only safe key;
  (b) `#46`'s client-shell choice doesn't reach Composer at all, since its shell is CLI-side.
  **Ask:** converge the execution model (or document it), and surface command output the same way on
  both agents — ideally on the completed update's structured `rawOutput` for both, keyed by
  `toolCallId`.

---

## 3. What the extension silently hides from users today

A quick inventory of everything we suppress to keep the chat sane — each is a place the
protocol shows users something it shouldn't:

- `/context` and `/always-approve` (removed from autocomplete and dispatch)
- `totalTokens: 0` reports (stripped before the UI)
- The hidden primer turn and its "ok" ack — plus its replayed copy on every restore
- The hidden post-`/compact` `/session-info` turn (our own workaround, invisible by design)
- Grok's post-verdict "I'll wait for your verdict…" filler (cancelled + suppressed)
- Marker-only `[Plan approved/rejected/cancelled]` protocol messages on replay
- `<system-reminder>` turns replayed as user messages
- The subagent result envelope (`<subagent_meta>`, `<subagent_result>`, lead-ins, Agent ID hint)
- The background-spawn "started" ack pretending to be a result
- Subagent child sessions in the history list (`session_kind:"subagent"`)
- Empty primer-only sessions on disk (swept) and primer-derived session titles (renamed)

---

## 4. What works well (credit where due)

- **Streaming** `agent_message_chunk`/`agent_thought_chunk` — clean, separable reasoning.
- **`fs/*` + `terminal/*` delegation** — being mandatory made them a reliable client-side
  enforcement point (it's what makes our plan gate possible at all).
- **`session/request_permission`** — clear option kinds; `kind:"edit"` maps neatly to a diff preview.
- **`session/load` replay through the same update stream as live** — most features restored
  with zero extra code.
- **`_meta` turn accounting** and per-model `totalContextTokens` — rich and useful (modulo the zero).
- **`_meta["x.ai/tool"]`** — an authoritative, title-independent tool identity. This is the
  *right* design; it single-handedly fixed subagent misclassification. Put it on everything.
- **`session/cancel`** as an id-less notification that settles the turn `cancelled` and leaves
  the session usable — exactly what a Stop button needs.
- **Concurrent sessions** — multiple `stdio` processes on one workspace with no cross-talk.
- **Vision** actually works; **`ask_user_question`** is a good structured surface once its
  response shape is known; **`spawn_subagent` (0.2.93)** is well-structured on grok-build.

---

## 5. Grok 4.5 verification (grok 0.2.93, 2026-07-11)

Every grok-build-family fact above was re-verified against **Grok 4.5** — the current default
model of that family. **Grok Build (`grok-build`) still ships for some accounts/builds**, so the
Grok Build observations in §1–§4 stand; the differences below are per-model *within the same
`grok-build-plan` agent*, not a replacement. The full live suite (`npm run test:live` —
**12 passed · 0 skipped · 0 failed**) plus targeted probes ran against the real binary on native
Windows; Composer 2.5 was independently re-verified in the same run (`subagent-composer`).

**Model surface (`session/new` → `availableModels`):**
- `currentModelId: "grok-4.5"`, name **"Grok 4.5"**, `_meta.agentType: "grok-build-plan"`.
- `_meta.totalContextTokens: 500000` — **500K, where Grok Build reports 512K** (per-model, same
  agent). Corroborated by `/session-info` prose (`Context: N / 500000 tokens`).
- `_meta.supportsReasoningEffort: true` with `reasoningEfforts` [high (default) / medium / low]
  now advertised **in the model list itself** — previously reasoning effort was visible only as
  a process-start flag (§2.7). It is still not settable per-turn over ACP; changing it still
  restarts the process.
- Only two models advertised: `grok-4.5` and `grok-composer-2.5-fast` (Composer 2.5).

**`session/set_model` is clean on Grok 4.5.** `set_model("grok-4.5")` returns
`{"_meta":{"model":{"Ok":"grok-4.5"}}}` — the requested id verbatim, resolvable in
`availableModels`. The **versioned-id defect (§1, §2.6) still applies to Grok Build**
(`grok-build` → `grok-build-0.1`) but does **not** reproduce on Grok 4.5 — so `resolveModelId`
stays necessary for the Grok Build model.

**Delegation (`spawn_subagent`) confirmed on Grok 4.5.** A real delegation emitted genuine
`spawn_subagent` calls with kebab-case `subagent_type` values (`explore`, `general-purpose`),
the completion arriving as a **same-id `tool_call_update`, `status:"completed"`** — exactly the
§1 grok-build shape. The `get_command_or_subagent_output` poller was correctly **not** carded.
The `subagent_spawned`/`subagent_finished` lifecycle events are **still not transmitted over
ACP** (`finished=0` observed while `updates.jsonl` filled) — §2.4 holds unchanged.

**The rest of §1–§4 reproduces on Grok 4.5:**
- Tool-call ids are `call-<uuid>-<n>`; `_meta["x.ai/tool"]` carries
  `{name, kind, namespace:"grok_build", label, read_only}` — the authoritative, title-independent
  tool identity praised in §4.
- Cross-agent switch after the first turn errors `MODEL_SWITCH_INCOMPATIBLE_AGENT`
  (`activeAgentType:"grok-build-plan"` → `requiredAgentType:"cursor"`,
  `suggestion:"start_new_session"`) — the agent is locked at spawn (§2.6).
- `promptCapabilities.image:false` while inline `{type:"image"}` blocks work — the model
  correctly named a solid red PNG (§2.5).
- Plan mode: `exit_plan_mode` still can't be rejected; the client-side write/terminal gate
  contained a rejected plan (0 workspace mutations) and released an approved one (§2.1).
- Live prompts echo back as `user_message_chunk` (§2.6); `session/cancel` (Stop), two concurrent
  sessions on one workspace, session restore, and structured edit-diff restore all behave as
  documented.

**Live suite (all against Grok 4.5 except the last):** handshake, capabilities, prompt-roundtrip,
cancel-mid-turn, parallel-sessions, vision-prompt, session-restore, edit-diff-restore, plan-mode,
image-gen, subagent, subagent-composer — **12/12 green.** Grok-free floor: **808/808.**

# Changelog

## 1.5.14 — 2026-07-14

### Fixed

- **Inline-diff line numbers no longer wrap mid-digit.** In an edit's inline diff, line numbers ≥100 could break onto a second row (`147` → `14` / `7`); the gutter is now wide enough and the number never wraps. Thanks to [@jiezaichan](https://github.com/jiezaichan) (#47). ([media/chat.css](media/chat.css))

## 1.5.13 — 2026-07-13

### Fixed

- **On Windows, the agent's shell commands now run under PowerShell instead of cmd (#46)** — `pwsh.exe` when installed, else Windows PowerShell 5.1 (`powershell.exe`), else cmd.exe. The extension runs every command Grok requests (Grok delegates them over ACP), so the shell was ours to pick; matching the standalone Grok CLI means PowerShell profile functions and pipelines (`… | Format-List`) just work, instead of failing under cmd and forcing the agent into costly retry/re-wrap loops. Linux/macOS are unchanged (`/bin/sh`). ([src/terminal-manager.ts](src/terminal-manager.ts))
  - **Install PowerShell 7 (`pwsh`) for the best experience** — the Windows PowerShell 5.1 fallback rejects `&&` command chains and reports every failing command's exit code as `1`; pwsh 7 does neither.
  - New **`grok.terminalShell`** setting (`auto` | `cmd`) — an escape hatch back to `cmd.exe` on Windows if the PowerShell host ever causes trouble. ([package.json](package.json), [src/sidebar.ts](src/sidebar.ts))
- **Command output now shows in the tool row for the Composer agent too.** Composer runs shell commands in its own CLI-side shell (it doesn't delegate over ACP like Grok Build), so its command rows showed the command (IN) but no output (OUT). The captured output is now read from the completed tool-call update and attached by tool-call id — reliable even though Composer runs commands in parallel and finishes them out of order. ([media/chat.js](media/chat.js), [media/webview-helpers.js](media/webview-helpers.js))
- **A command row's one-line label no longer drags in a quoted argument.** `Write-Output '=== banner ==='` now reads "Run Write-Output", not a truncated "Run Write-Output === 1. git statu…" — a quoted arg is data, not a subcommand. ([media/webview-helpers.js](media/webview-helpers.js))

## 1.5.12 — 2026-07-13

### Added

- **Edit diffs are reviewable inline in chat, even under Auto accept (#45).** Every edit row shows an always-visible `+N −M` change count (rolled up onto collapsed "Edited N files" group headers, path-deduped) plus an expandable **inline diff** — a Codex-style line-number gutter, colored left-border stripe, subtle tint, and a `+/−` glyph for color-blind readability. It rides the same expand controls as command IN/OUT, works live and on session restore, and — because the diff data is always on the ACP wire regardless of permission mode — needs no permission card. The native `open diff →` link stays for the full side-by-side. ([media/chat.js](media/chat.js), [media/webview-helpers.js](media/webview-helpers.js), [media/chat.css](media/chat.css))

### Changed

- **The gear toggle "Expand command outputs" is now "Expand tool details"** — it governs command IN/OUT blocks **and** edit diffs, matching the *Expand All Tool Details* commands (the `grok.expandCommandOutputs` setting key is unchanged). ` ```diff ` blocks in Grok's messages now share the same Codex diff palette + left-border styling. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css), [package.json](package.json))

### Fixed

- **A shell command that exits 0 with no output** now shows a muted `✓ done · no output` marker instead of an empty `(no output)` line. ([media/chat.js](media/chat.js))

## 1.5.11 — 2026-07-13

### Added

- **Caret lands in the composer after you add context (#43).** Send Selection, Send File, @-mention, the **+** file picker, and image paste all reveal the panel *taking* focus, so you can type your prompt immediately — no click into the input first. ([src/sidebar.ts](src/sidebar.ts), [src/protocol.ts](src/protocol.ts), [media/chat.js](media/chat.js))

### Changed

- **"Grok: Send Selection" is now "Add Selection to Grok",** and a command-sent selection attaches in the **top** attachments row (removable, with its line range) like any other file — only the ambient active-editor chip stays in the bottom toolbar. ([package.json](package.json), [media/chat.js](media/chat.js))
- **"Grok: Send File" no longer silently no-ops** from the Command Palette when no file is open — it opens a file picker instead of doing nothing and dropping focus. ([src/sidebar.ts](src/sidebar.ts), [src/extension.ts](src/extension.ts))
- The internal debug command (`grok._debugDummyPlan`) is hidden from the Command Palette. ([package.json](package.json))

## 1.5.10 — 2026-07-12

### Added

- **Expand / collapse all tool details.** Two Command Palette commands — *Grok: Expand All Tool Details (This Session)* / *…Collapse All…* — open or close every tool group and command IN/OUT box, **including a batch that's still running**, and keep applying to tool calls that stream in afterward. It's a per-session latch (last action wins vs the gear setting; flipping the setting clears it) that survives Agent Dashboard focus-swaps and resets on a cold reopen — never persisted to disk. Bind them to a key if you like. ([src/extension.ts](src/extension.ts), [media/chat.js](media/chat.js), [src/sidebar.ts](src/sidebar.ts))

### Changed

- **`grok.expandCommandOutputs` now also opens command-bearing tool *groups*,** not just each command's IN/OUT detail — an Auto-accept "Ran N commands" batch is audit-visible with zero extra clicks; explore/edit-only groups stay collapsed. ([media/chat.js](media/chat.js))
- **Command rows read as "Run \<program\>"** — the executable plus a non-flag subcommand (`Run git status`, `Run npm test`, `Run node`, `Run Get-Date`), not a truncated slab of shell. The full command still lives in the row's IN/OUT detail. ([media/webview-helpers.js](media/webview-helpers.js))
- Refreshed the README — new mode-picker and image-paste screenshots, and a leaner **Install** section (the extension's onboarding installs the CLI and signs you in) with build-from-source / per-IDE scripts moved to [docs/INSTALL.md](docs/INSTALL.md). ([README.md](README.md))

### Fixed

- **Failed non-shell tools now show their real error inline** instead of a generic "Tool call failed." — the reason is mined from variant-keyed `rawOutput` blobs (e.g. `list_dir` → `NotFound`, `read_file` → `FileReadError`) when there's no `message`/`content` to read. ([media/webview-helpers.js](media/webview-helpers.js))

## 1.5.9 — 2026-07-12

### Changed

- Documentation-only patch: the README hero screenshot now shows the current UI running **Grok 4.5** ([docs/screenshots/grok_4.5.png](docs/screenshots/grok_4.5.png), replacing the v1.4.20 shot). No code changes.

## 1.5.8 — 2026-07-12

### Fixed

- **RTL text (Arabic, Hebrew, Farsi) now renders correctly** (user report). Every paragraph and block takes its direction from its own first strong character — right-aligned with punctuation on the correct side — across chat bubbles, thinking traces, plan cards, subagent results, tables, lists (markers and indent flip too), and the queued block; the composer follows as you type. Code blocks and inline code stay pinned LTR (the same rule the Codex extension uses), and the chat chrome doesn't move — only text direction changes, per block. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css), [src/sidebar.ts](src/sidebar.ts))

## 1.5.7 — 2026-07-12

### Added

- **Command details (#41).** Every shell-command row expands (trailing `›` ↔ `v`) into a Claude-Code-style **IN/OUT block**: the full command text immediately — a lone running command is expandable mid-run — and the complete captured output when it finishes (the extension executes the commands itself, so the output is byte-for-byte what grok received). Exit 0 stays silent; failures render an `[Error] exit N` marker with error-tinted output; kills render a muted `[Cancelled]`. `grok.expandCommandOutputs` (also gear → Config & debug) pre-opens every detail — the audit view for Auto-accept sessions. Live-session only: the CLI doesn't replay terminals on restore. ([src/acp.ts](src/acp.ts), [src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))

### Changed

- **Tool rows read as one scannable line** — labels trim at 40 chars (full text one click away), long content ellipsizes at the row edge instead of wrapping, and the corner-radius scale is unified (bubbles 12 → code/IN-OUT blocks 8 → inline chips 6). ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css))
- Refreshed the Marketplace description and README (new screenshots: cost control, effort picker, file chips). ([README.md](README.md), [package.json](package.json))
- Every outbound `session/cancel` is logged with its trigger (Stop click / plan verdict) in the Grok output channel, so any future spurious-cancel report (#37) is attributable at a glance. ([src/acp.ts](src/acp.ts))

### Fixed

- Private working docs no longer ship inside the public `.vsix` (they were bundled because `.vscodeignore` — not `.gitignore` — decides the package contents). ([.vscodeignore](.vscodeignore))

## 1.5.6 — 2026-07-11

### Added

- **Subagent rows, fully live.** A delegation renders as a purple *Subagent · \<task\>* row with running dots, then a duration stamp and a click-to-expand result under "Output of the subagent:" — the CLI envelope (plumbing tags, boilerplate lead-ins, one wrapping `<response>` pair, the Agent ID hint) is stripped when present, never failing. Covers grok-build's `spawn_subagent` — including `background: true` spawns, whose started-ack no longer masquerades as the result (the card completes from the output poller's `TaskOutput`, matched by task id) — and the Composer agent's `Task`. The `subagent_spawned`/`subagent_finished` lifecycle events are routed for the day the CLI transmits them (0.2.93 logs them but doesn't send them over ACP — live-verified). Real captured sessions are replayed end-to-end in the test suite. ([media/chat.js](media/chat.js), [media/webview-helpers.js](media/webview-helpers.js), [src/acp.ts](src/acp.ts), [test/fixtures/composer-subagent-session.jsonl](test/fixtures/composer-subagent-session.jsonl))

- **[docs/ACP-feedback.md](docs/ACP-feedback.md)** — an upstream-facing summary of grok-CLI/ACP friction: the grok-build vs Composer wire differences, everything the extension works around or hides (with suggested fixes), what works well, and a Grok 4.5 verification checklist. Built from the wire captures and probes in `research/`.

### Changed

- **One copy/timestamp footer per turn, shown when the turn ends.** The copy action and time sit only under the turn's final agent message (the conclusion) and appear once the turn completes — no more copy icons flickering mid-conversation while grok works; the timestamp reads as the turn's end time. Code blocks keep their own copy buttons. ([media/chat.js](media/chat.js))
- **The composer grows with your text.** 2 lines at rest (Cursor-style), expanding to 5 as you type, then scrolling; scales with `grok.chatFontScale`. ([media/chat.js](media/chat.js), [src/sidebar.ts](src/sidebar.ts))

### Fixed

- **No more fake Subagent cards while working on subagent code.** grok titles Grep/Read calls with their query/filename (a search for `spawn_subagent` is titled exactly that), so title matching false-carded ordinary tools; the classifier now treats the wire's `_meta["x.ai/tool"].name` as authoritative both ways and matches exact tool names otherwise. ([media/webview-helpers.js](media/webview-helpers.js))
- **Subagent child sessions no longer clutter history.** Every delegation persists its child as a top-level session (`session_kind: "subagent"`); the history list hides them, and pagination advances by consumed index slots (`nextOffset`) so hidden rows can't stall or duplicate load-more. ([src/sessions.ts](src/sessions.ts), [src/sidebar.ts](src/sidebar.ts))
- **Restored plan/permission cards no longer drift to the end of the conversation.** The host counted replayed `<system-reminder>` turns and marker-only verdicts toward plan positions while the webview (correctly) renders no bubble for them — so every verdict given after a session restore persisted an unreachable position and its card landed at the bottom on the next restore. The host now counts exactly what the webview bubbles (`countsAsUserBubble`). Positions persisted by older builds stay as recorded. ([src/plan-restore.ts](src/plan-restore.ts), [src/sidebar.ts](src/sidebar.ts))

## 1.5.5 — 2026-07-11

### Changed

- **Codex-inspired chat restyle.** User bubbles use a theme-independent foreground tint (fixes bubbles that vanished on Cursor dark themes), inline and fenced code share one chip surface + editor-contrast text, one 28px ghost icon-button style across header/composer/message/code actions, file refs and "open diff →" render as real links (hover-only underline), plan/permission card text matches the chat font, and the composer types in the UI font instead of the editor's monospace. ([media/chat.css](media/chat.css), [media/chat.js](media/chat.js))
- The permanent plan-cancel notice no longer says "Grok is processing the cancellation…" — the transient dots indicator carries that state. ([src/sidebar.ts](src/sidebar.ts))
- **Resolved plan cards drop the inline plan text.** Once a plan is approved/rejected/cancelled (live or restored), the card shows just the plan-file link + verdict — the file opens as an editor tab; the Show/Hide toggle remains only when no plan file exists. ([media/chat.js](media/chat.js))
- **Toolbar icons equalized.** The mode button, context donut, and mode-picker icons now use the same 16px glyph and 28px highlight height as the settings/history buttons. ([media/chat.css](media/chat.css))

### Added

- **Context popover on the donut.** Click the context donut for the exact token count (`used / window`, %). (#39) ([media/chat.js](media/chat.js))

### Fixed

- **Resolved plan cards stay resolved on re-focus.** Re-opening a live session no longer resurrects an already-answered plan review with active Approve/Reject/Cancel buttons; resolved cards replay collapsed behind Show/Hide plan with their verdict (`planResolved`, the plan twin of `permissionResolved`). ([src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js), [src/protocol.ts](src/protocol.ts))
- **`/session-info` no longer zeroes the context donut.** A turn's `totalTokens: 0` report is never a real measurement (`/compact` shrinks context, it doesn't empty it) and is now always ignored; `/context` (a CLI-TUI no-op over ACP) is hidden from autocomplete — use `/session-info`. (#39) ([src/acp-dispatch.ts](src/acp-dispatch.ts), [src/slash-filter.ts](src/slash-filter.ts))
- **The context donut is real on restore and right after `/compact`.** A restored session seeds the donut from grok's persisted `signals.json` instead of showing 0 until the first turn; and `/compact` is followed by a hidden, CLI-local `/session-info` turn (~25ms, no model call, not persisted to history) whose reply carries the exact post-compact count — parsed and pushed to the donut moments after "Compacted." (the compact turn's own meta reports 0 and the CLI recomputes `signals.json` only at the next turn's end, so this was otherwise unknowable — probe-verified). ([src/sessions.ts](src/sessions.ts), [src/acp-dispatch.ts](src/acp-dispatch.ts), [src/sidebar.ts](src/sidebar.ts), [research/signals-refresh-probe.cjs](research/signals-refresh-probe.cjs))
- **Approving a plan no longer leaks grok's post-verdict filler** ("I'll wait for your verdict…") into the chat: the planning turn the CLI unblocks on our response is cancelled and content-suppressed on Approve exactly as Reject/Cancel already did — that text never survived a session restore, so it doesn't paint live either. ([src/sidebar.ts](src/sidebar.ts))
- **The welcome logo/byline actually hides once the chat has content** (a CSS `display` rule was overriding the `hidden` attribute), and a primer-only restore keeps the welcome screen instead of showing an empty chat. ([media/chat.css](media/chat.css), [media/chat.js](media/chat.js))
- **No more forever-spinning dots after cancelling a plan.** Turn end now always clears the waiting indicator (grok's `[Plan cancelled]` ack can be contentless, which orphaned it), and a plain Cancel is silent by design: the "Plan abandoned" notice is the whole UX — the verdict still reaches grok on a hidden turn, but its ack reply no longer paints. ([media/chat.js](media/chat.js), [src/sidebar.ts](src/sidebar.ts))
- **White flash on webview load fixed** (VS Code only): an inline critical style paints the theme background immediately and holds the welcome invisible until the stylesheet loads. ([src/sidebar.ts](src/sidebar.ts), [media/chat.css](media/chat.css))

## 1.5.4 — 2026-07-11

### Changed

- **One pending message instead of a queue.** Composing more text while a message is already queued now **appends** to the single pending block (blank-line separated — exactly how it sends), rather than stacking separate queue entries. Edit pulls the whole pending text back into the composer, Remove drops it, Stop still hands it back — no more edited messages landing at the end of a queue that was going to collapse into one message anyway. (#37 follow-up) ([media/chat.js](media/chat.js), [src/sidebar.ts](src/sidebar.ts))

## 1.5.3 — 2026-07-11

### Fixed

- **Typing while Grok works no longer cancels its tools.** Enter (and the send button) doubled as a hidden Stop while a turn was running, so a mid-turn "continue" silently resolved in-flight tools as *"cancelled by the user"* — amplified by busy-state leaking across dashboard session switches. Typed text now **never cancels**: messages compose into a per-session queue shown as pending blocks at the end of the chat (italic, clock tag, per-message Edit/Remove), survive session switches, and auto-send as one combined message when that session's turn ends — even while backgrounded. Stop (square button, empty composer only) hands queued text back to the composer instead of firing it. Thanks @githubuser1256! (#37) ([media/chat.js](media/chat.js), [src/sidebar.ts](src/sidebar.ts), [src/session.ts](src/session.ts), [src/protocol.ts](src/protocol.ts))
- **Enter during CJK IME composition no longer sends mid-composition.** The composer now respects `isComposing`/`keyCode 229`, so Enter confirms the IME candidate (Claude-Code-style: first Enter picks the character, second sends). Thanks @yyu0310! (#38) ([media/chat.js](media/chat.js))

### Added

- **Live-suite coverage for the Stop contract and concurrent sessions.** `cancel-mid-turn` pins that an id-less `session/cancel` settles the turn as cancelled and leaves the session usable; `parallel-sessions` pins that two CLI processes on one workspace answer overlapping prompts independently. ([scripts/live-tests.cjs](scripts/live-tests.cjs))

## 1.5.2 — 2026-07-10

### Added

- **One-click "Move view" in the gear menu.** Gear → **Config & debug → Move view** relocates the chat to the Secondary Side Bar, Primary Side Bar, or Panel instantly — direct moves into per-location view containers, no picker — each with a matching panel icon. Especially handy in Cursor, whose side-bar context menu hides the built-in "Move To" entry. ([src/view-move.ts](src/view-move.ts), [media/chat.js](media/chat.js))
- **Install scripts detect Cursor and can target every IDE at once.** `cursor` joins the auto-detect chain, and `--all` (Windows: `-All`) builds once and installs into every detected IDE. ([scripts/](scripts/))

### Changed

- **The view now opens in the Secondary Side Bar by default** (`viewsContainers.secondarySidebar`), next to your other AI tools. This raises the minimum VS Code to **1.106** — older hosts (e.g. Antigravity, currently on base 1.104) keep the last compatible version. A placement you set yourself still wins; use the gear mover or *Reset Location* to adopt the new default.

## 1.5.1 — 2026-07-09

### Fixed

- **The mode button tells the truth when `always-approve` is set in `config.toml`.** grok's global `permission_mode = "always-approve"` (set via Shift+Tab or `/always-approve` in the TUI) auto-approves every session server-side and is invisible over ACP, so the extension used to show a misleading "Agent mode" with no permission cards. It now detects the setting (project `.grok/config.toml` overriding global `~/.grok/config.toml`) and shows **Auto accept**, plus a one-time notice that it's a global config setting. (#31) ([src/grok-config.ts](src/grok-config.ts), [src/sidebar.ts](src/sidebar.ts))

### Changed

- **Hidden the `/always-approve` slash command.** It only mutates grok's global `config.toml` — a sticky, surprising side effect — and is a no-op over ACP, so it no longer appears in autocomplete or dispatches. (#31) ([src/slash-filter.ts](src/slash-filter.ts), [src/acp.ts](src/acp.ts))
- **Typed the host↔webview message contract.** The host→webview direction was `any`; it's now a discriminated union in `src/protocol.ts` (single source of truth), with the webview keeping a synced mirror and a test asserting both sides agree — so "post one shape, handle another" drift (restore/pagination/media) is a build error. Caught two latent mismatches on the way in. ([src/protocol.ts](src/protocol.ts), [media/webview-helpers.js](media/webview-helpers.js))
- **Strengthened the test & release gates.** The `release.*` scripts now run `test:live` by default (`-SkipLive`/`--skip-live` to opt out); the real-grok plan-mode test now models the true approve/reject flows with a disk-snapshot containment canary (the old single-turn test invented an impossible state); the live suite gained a capability-drift probe and a fast `--smoke` lane; and a required `@vscode/test-electron` activation smoke now runs in CI (`npm run test:integration`, validated against a real Extension Host).
- **Documentation consistency pass:** corrected the minimum VS Code version in the README, documented the `Grok: Compact Conversation` command, added the telemetry/mode-prefs/grok-config modules to the architecture map, and trimmed change-history narrative out of `CLAUDE.md` (it points at the changelog and `research/*` instead).

## 1.5.0 — 2026-07-09

### Added

- **Paste or attach images — Grok now sees the pixels.** Ctrl+V a screenshot, drag-drop, or attach a png/jpg/gif/webp and it rides the prompt as an inline vision block (validated at send, 20 MiB cap, session-scoped `[Image #N]` tags that restore as chips; SVG stays a path chip so Grok can edit the source). Thanks @cpulxb! (#32) ([src/chips.ts](src/chips.ts), [src/prompt-builder.ts](src/prompt-builder.ts), [src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))
- **The active-editor context chip tracks your live selection** (`file.ts:8-15`), and selection snippets restore as ranged chips when a session is reopened. Thanks @cpulxb! (#32) ([src/sidebar.ts](src/sidebar.ts), [media/webview-helpers.js](media/webview-helpers.js))

### Fixed

- **`/compact` actually compacts again — and says so.** A leading context envelope silently degraded it into an ordinary LLM turn that *grew* context ~6x; confirmed slash commands now lead the text block, the context donut accepts the post-compact reset, the hidden plan-mode primer is re-sent afterwards (thanks @cpulxb! #32), and the turn now ends with a visible **"Compacted."** confirmation. ([src/prompt-builder.ts](src/prompt-builder.ts), [src/slash-filter.ts](src/slash-filter.ts), [src/sidebar.ts](src/sidebar.ts))
- **Plan mode no longer blocks safe chained commands.** `cd repo && git status` was rejected outright, which crashed grok-4.5's planning phase; chains (`&&`, `||`, `;`) now pass when **every** segment is read-only — one mutating segment still blocks the whole command. (#36) ([src/plan-gate.ts](src/plan-gate.ts))

### Changed

- **Composer polish:** one focusable card, VS Code-style webview scrollbars, and the caret lands in the input on panel open, window refocus, new session, and session switches (thanks @cpulxb! #32); pasted images that can't be read block the send instead of silently dropping, and inline images carry a do-not-read-from-disk hint so Grok stops noisily `Read`-attempting its own copy. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css))

## 1.4.31 — 2026-07-09

### Added

- **The install/uninstall scripts can target any code-compatible IDE.** Pass a CLI name or path — `./scripts/install.sh antigravity-ide` (Windows: `pwsh scripts\install.ps1 -Cli antigravity`) — or set `CODE_CLI=…`; with no argument they auto-detect `code` → `code-insiders` → Antigravity and hint at other IDEs they found. Thanks @mingminghome for the Antigravity groundwork. (#35) ([scripts/](scripts/))

### Fixed

- **Session startup no longer crashes on an invalid or unavailable `grok.defaultModel`.** A failed `setModel` on session create/load is caught and logged, falling back to the CLI's current model instead of exiting; if the configured model isn't in the CLI's list, a warning toast suggests updating the setting. Thanks @mingminghome. (#33, #34) ([src/acp.ts](src/acp.ts), [src/sidebar.ts](src/sidebar.ts))

## 1.4.30 — 2026-07-09

### Fixed

- **The sign-in (and sign-out) terminal commands actually run now.** The onboarding button typed `"C:\…\grok.exe" /login` into the terminal — the wrong command (`login` is the CLI subcommand; `/login` only works inside the interactive TUI) *and* a PowerShell parser error (a quoted path followed by arguments needs the `&` call operator). Sign-in and sign-out now launch the grok binary directly as the terminal's own process, which behaves the same on PowerShell, cmd, and POSIX shells. README examples updated to `grok login` too. ([media/chat.js](media/chat.js), [src/sidebar.ts](src/sidebar.ts), [README.md](README.md))

### Changed

- The API-key option in the sign-in onboarding no longer claims extra models — it now just says "pay per token". ([media/chat.js](media/chat.js))

## 1.4.29 — 2026-07-05

### Fixed

- **A permission request that's only an edit is now reviewable, and its diff survives a VS Code restart.** A standalone edit collapsed to a bare one-line row with no way to open the diff — while a read+edit batch stayed expandable — and on restore the diff was lost entirely. A lone edit now keeps the same collapsible tool group (chevron, "N → M lines", "open diff →") as a multi-tool batch, in both the live and resumed orderings. ([media/chat.js](media/chat.js)) (#30)

## 1.4.28 — 2026-07-01

### Fixed

- **The mode switch (Agent / Plan / Auto-accept) is now disabled while the session is starting.** Picking a mode before the session existed called `setMode` too early and surfaced *"Couldn't switch mode: no session."* The mode button is greyed out and unclickable until the session is ready — like the send button — and the toggle-mode command is guarded server-side too. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css), [src/sidebar.ts](src/sidebar.ts))

## 1.4.27 — 2026-07-01

### Added

- **Context files now tell Grok how they got there.** A file you explicitly attach is listed as **"Attached file(s)"** (strong intent); the file that's auto-included because it's open in your editor is listed separately as **"Currently open in the editor (for context)"** (weaker, ambient) — so Grok doesn't treat a file you're just looking at as one you asked it to act on. ([src/prompt-builder.ts](src/prompt-builder.ts))
- **Uploaded attachments now have their own row above the input**, each with a remove (×) button. The active-editor file stays in the bottom toolbar as before. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css), [src/sidebar.ts](src/sidebar.ts))

### Fixed

- **grok-build now shows its real name and 512K context window.** grok resolves a `set_model("grok-build")` to a *versioned* id (`grok-build-0.1`) that isn't in the model list, so the toolbar showed the raw id and the context donut fell back to the 200K default (percentage read ~2.5× too high). The id is now normalized back to the list entry, and the window recomputes on every model change. ([src/acp.ts](src/acp.ts), [src/acp-dispatch.ts](src/acp-dispatch.ts), [media/chat.js](media/chat.js))
- **The voice/mic button no longer jumps when attachments appear.** It's now anchored to the input box instead of the composer, so the new attachments row above the input doesn't shove it out of place. ([media/chat.css](media/chat.css), [src/sidebar.ts](src/sidebar.ts))
- **Attachment chips show just the filename** — in the composer, the sent-message bubble, *and* restored sessions — for files outside the workspace (Windows absolute paths were previously shown in full); the full path stays on the hover tooltip, and Grok still receives the full path. The file-path context is sent in a machine-readable `<vscode-context>` envelope so the webview can parse it back deterministically on restore instead of showing the raw replayed paths. ([media/chat.js](media/chat.js), [media/webview-helpers.js](media/webview-helpers.js), [src/prompt-builder.ts](src/prompt-builder.ts))
- **Code blocks no longer render with a doubled blank line around them.** A fenced code block was wrapped in `<br><br>` on top of its own margin (the model sends just one blank line), so it looked double-spaced; code blocks are now emitted as their own block, like tables and math. ([media/chat.js](media/chat.js))

## 1.4.26 — 2026-06-30

### Fixed

- **Updating the Grok Build CLI no longer fails with "cannot rename locked executable."** The update tore the session pool down but didn't *wait* for the grok processes to actually exit, so `grok update` raced the still-held Windows lock on `grok.exe` (`Access is denied. (os error 5)`). Teardown now resolves only once each process has truly exited, kills the whole process **tree** on Windows (`taskkill /T /F`, so grok's backgrounded subagent/command children don't keep the binary locked), and the update retries once if a lingering lock slips through. ([src/acp.ts](src/acp.ts), [src/sidebar.ts](src/sidebar.ts), [src/cli-locator.ts](src/cli-locator.ts))

### Changed

- **Directory listings show the full relative path with a trailing slash** — `List docs/` and `List docs/screenshots/` instead of the basename-only `List screenshots`. ([media/chat.js](media/chat.js))

## 1.4.25 — 2026-06-30

### Fixed

- **Empty primer-only sessions are cleaned up even when large.** A hidden-primer turn can balloon to dozens of agentic tool/reasoning messages with no real user message; the startup sweep skipped those (`num_messages` over the gate) so they lingered in history with a primer-derived title. The chat-history content check is now authoritative regardless of message count — a session with our primer and zero real user queries is swept (real and renamed sessions are still never touched). ([src/sessions.ts](src/sessions.ts), [src/sidebar.ts](src/sidebar.ts))
- **The send button now shows the spinner from the moment the panel opens.** During the initial session spin-up it briefly showed neither the send arrow nor the spinner; it now defaults to the disabled spinner until the session is live. ([media/chat.js](media/chat.js))
- **Tool rows now show the detail again for List / Search / Fetch.** A directory listing shows the folder (`List docs`), a read shows the file and line range (`Read README.md lines 1-30`), a search shows the pattern, and a web fetch shows the page URL — these had regressed to a bare verb because the rawInput field names (`target_directory`, `url`) weren't being read. Verified against real on-disk sessions. ([media/chat.js](media/chat.js))

### Changed

- **The diff-preview edit row is now a single line** — `Edit chat.js  9 → 10 lines  open diff →` instead of three stacked lines. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css))
- **Table cells no longer break mid-word.** Long header/cell words were chopped between letters, making columns look cramped and arbitrarily narrow; cells now wrap only at spaces and hyphens (an unbreakable run falls back to the table's horizontal scroll). ([media/chat.css](media/chat.css))
- **The Grokking indicator spins the other way.** ([media/chat.css](media/chat.css))
- **The scroll-to-bottom button sits slightly higher**, so its gap above the composer's top border matches the border-to-textarea gap. ([media/chat.css](media/chat.css))
- **Trimmed the README privacy section** to a short privacy-by-design summary; the full detail moved to [docs/privacy.md](docs/privacy.md). ([README.md](README.md), [docs/privacy.md](docs/privacy.md))

## 1.4.24 — 2026-06-29

> Privacy-first, opt-out anonymous usage telemetry.

### Added

- **Anonymous usage telemetry (Aptabase).** One `session_start` event per session — fired on the **first real user message** (never the primer or empty/abandoned sessions) — carrying only an anonymous install id (a random GUID, no account or grok-login identity) plus the chosen **mode / model / effort**. **No message content, code, or file paths are ever sent;** country is derived by Aptabase from the request IP and the IP is then discarded. **On by default but fully gated** — it sends only when VS Code's global `telemetry.telemetryLevel` is enabled *and* the new `grok.telemetry.enabled` setting is on; either off stops everything. The event is built synchronously (capturing the right session's mode/model/effort) but **fired asynchronously off the send path** and any error is **swallowed silently**, so telemetry can never slow, surface to, or break a turn — a failure (offline, a wrong/typo'd key → a harmless 404, a malformed event) just means nothing lands. Thin, dependency-free client (no SDK). ([src/telemetry.ts](src/telemetry.ts), [src/sidebar.ts](src/sidebar.ts), [package.json](package.json))

### Tests — 609

- New: the telemetry helpers — `aptabaseHost` (region from app key), `osNameFromPlatform`, the `shouldSendTelemetry` two-gate check, distinct prod/dev keys, `buildSessionStartEvent` (install id + mode/model/effort as props, no content), and that `postEvent` **never throws** (a circular/malformed event or a no-region key is a silent no-op) ([test/telemetry.test.ts](test/telemetry.test.ts)). The unit suite stays network-free; a separate `npm run telemetry:probe` ([scripts/telemetry-probe.cjs](scripts/telemetry-probe.cjs), with an `APTABASE_KEY` override to fire a wrong key) sends real events to a **dev** Aptabase project (the published extension always reports to prod).

## 1.4.23 — 2026-06-29

> Hidden-by-default thinking traces with an always-on progress indicator, a scroll-to-bottom button, a remembered mode preference, and the YOLO → Auto accept rename.

### Added

- **Thinking traces are hidden by default (#26).** Grok's reasoning no longer fills the chat — a muted **Thinking…** stand-in (brain icon) shows while it reasons. Turn traces back on from gear → **Config & debug → Show thinking traces** (a live switch backed by `grok.showThinking`); it reveals them on already-loaded sessions too. When shown, a thinking row now matches the tool rows — same font size, a leading **brain icon**, and the shared chevron + hover (it was a smaller 11px and icon-less). ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css), [src/sidebar.ts](src/sidebar.ts), [package.json](package.json))
- **The chat always shows live progress during a turn.** While a turn is in flight, one of **Grokking / a running tool / Thinking…** is guaranteed on screen — no dead frames, even with traces hidden. ([media/chat.js](media/chat.js))
- **Scroll to bottom (#28).** A floating button appears above the composer once you scroll up off the bottom; click it for an animated jump back down. It's anchored to the chat input area, so it stays correctly placed at any `chatFontScale` zoom. ([src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js), [media/chat.css](media/chat.css))
- **New sessions remember your last mode (#25).** The last switch between **Agent** and **Auto accept** is reapplied on new sessions (Plan is deliberately never remembered), mirroring how model & effort already persist. It's applied up-front, so the toolbar shows the right mode from the first paint — no Agent → Auto accept flash while the session primes. Backed by `grok.defaultMode`. ([src/sidebar.ts](src/sidebar.ts), [package.json](package.json))

### Changed

- **The progress indicators now share one look.** *Grokking*, the *Thinking…* stand-in, and a running tool all use the editor font size, a 15px leading icon, and the same muted color + spacing — a running tool no longer brightens to look hovered. Motion is per-indicator: *Grokking* spins a lucide **orbit** icon (it's a generic wait), while *Thinking* and tools use the **three blinking dots** (discrete progress) — both replacing the old morphing "…" pills. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css))
- **Renamed the "YOLO" mode to "Auto accept."** The mode picker and the bottom-toolbar button now read **Auto accept**; "YOLO" survives only in the picker's one-line description. The internal mode id (`yolo`) and `autoApprove` flag are unchanged. ([media/chat.js](media/chat.js))
- **A user message's copy + timestamp now appear on hover** (the bubble or the row beneath it), matching grok messages — they used to always show. ([media/chat.css](media/chat.css))
- **Trimmed the README feature descriptions** that already carry a screenshot, cutting the redundant "what it looks like" prose. ([README.md](README.md))

### Tests — 599

- New: the Auto accept label, the thinking-traces toggle (hidden-by-default body class, live flip, the **Thinking…** stand-in vs. a visible trace, the Config & debug switch), the Grokking orbit indicator, the scroll-to-bottom visibility threshold + click, and a **step-by-step turn simulation** asserting a live progress indicator after every mid-turn event with traces hidden *and* shown ([test/webview-ui.dom.test.ts](test/webview-ui.dom.test.ts), [test/webview-harness.ts](test/webview-harness.ts)); the remembered-mode policy `modeToRemember`/`startsInYolo` — Plan never persisted, applied to new sessions only (#25) ([test/mode-prefs.test.ts](test/mode-prefs.test.ts)).

## 1.4.22 — 2026-06-29

> Single-home the sidebar so it can be moved in Cursor, and stop forcing whole-file reads on attachments.

### Fixed

- **The view can be relocated again (Cursor).** We declared the `grokSidebar` container in **two** places at once (`activitybar` + `secondarySideBar`); `secondarySideBar` only exists in VS Code ≥ 1.106, so on older bases (incl. current Cursor) the stray declaration is parsed-but-unsupported — it pinned the view to the left and could even shift *other* extensions' views. The container is now single-homed to `activitybar`; relocate it with right-click the **Grok** title → **Move To → Secondary Side Bar** (it persists). ([package.json](package.json))
- **Attached files are handed to grok as paths, not `@`-reads.** A file chip used to become `@relPath`, grok's "read this whole file" convention — which slurped large files (a big CSV/log) into context and *failed outright on binaries*: an attached image or video triggered `read_file` → *"Cannot read binary file"* (grok has no vision). Chips now render as a plain **"Attached file(s):"** path list, so grok decides how to consume each — grep/range-read big text, pass image/video paths to its media tools, read small files in full. Selected-range chips still inline the exact lines you picked. ([src/prompt-builder.ts](src/prompt-builder.ts))
- **Corrected the subscription requirement.** The sign-in screen claimed *SuperGrok **Heavy*** was required for Grok Build — wrong on two counts: it's **any SuperGrok *or* X Premium+** subscription, and naming the $300/mo Heavy tier scared off eligible users. Fixed in the onboarding, README, and Marketplace description (and clarified that Grok's free tier doesn't include the CLI agent). ([media/chat.js](media/chat.js), [README.md](README.md), [package.json](package.json))

### Changed

- **Renamed the "Voice input" feature to "Voice control"** across the UI and docs. ([README.md](README.md), [src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))
- **Welcome byline reads "(The Product Compass)"** again (dropped the "Newsletter" suffix). ([src/sidebar.ts](src/sidebar.ts))

## 1.4.21 — 2026-06-29

> Documentation-only patch: the README screenshots now match the current (v1.4.20) UI.

### Changed

- **README screenshots refreshed.** New hero image, plus shots for **session history**, the redesigned **tool-call rows**, and the **permission diff-preview** card; the tool-calls description now matches the categorized/icon design. The old v1.2.0 sidebar screenshot is removed. ([README.md](README.md), [docs/screenshots/](docs/screenshots/))

## 1.4.20 — 2026-06-28

> A chat-readability overhaul plus housekeeping: tool and thinking rows get Codex-style category icons and a muted-until-hover look, failed tools finally show *why*, each narration sits above the tools it describes, and the empty "primer" sessions stop cluttering history (#24). Also renamed **Unofficial → Community**.

### Changed

- **Tool-call summaries are categorized by what the tool actually did.** Reads, globs, and greps were all rolled up as "Ran N commands"; they're now bucketed by ACP kind into "Explored N items" / "Edited N files" / "Deleted N files" / "searched web" / "Ran N commands" — so a turn that read five files reads "Explored 5 items", not "Ran 5 commands". Works on resumed sessions too: when the wire form omits `kind`, the category is recovered from the tool's title. ([media/chat.js](media/chat.js))
- **A turn's narration now interleaves with its tool groups instead of piling above them.** grok narrates each step then runs its tools (narrate → tools → narrate → tools); the narration used to coalesce into one bubble with the tool summaries stacked consecutively below it, so the summaries looked arbitrary. Each narration sentence now renders directly above the tool group it introduced, preserving grok's actual order. ([media/chat.js](media/chat.js))
- **Tool and thinking rows restyled (Codex-aligned).** Each tool row (single or group) now leads with one **lucide category icon** — `file` (read) / `folder-search` (search) / `pencil` (edit) / `square-terminal` (command, and the catch-all), picked by the strongest action in a group. Rows are flush-left in the standard font, **muted by default and brighten on hover** (no background highlight); a running group stays "active" until it completes. Expanded bodies use a thin secondary border (not blue). Thinking blocks now share the tool rows' chevron — same glyph, on the **right**, after the label — and the same expand border. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css))
- **Generated images/videos align with the message text** — dropped the extra horizontal inset they carried. ([media/chat.css](media/chat.css))
- **Renamed "Unofficial" → "Community".** The chat header, extension title, and README now read **Grok Build (Community)** / **Grok Build for VS Code (Community)**; the About fine print still notes it's unofficial, community-built, and not affiliated with xAI. ([package.json](package.json), [README.md](README.md), [src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))

### Fixed

- **Tool-call labels no longer leak raw regex/glob patterns.** A search tool used to render its bare pattern (e.g. `image_edit|/imagine`) as the whole label; it now shows `Search <pattern>`, and any tool we didn't predict falls back to grok's own formatted title instead of scraping arbitrary raw input. ([media/chat.js](media/chat.js))
- **Failed tool calls now show their reason instead of being silently dropped.** A `status: "failed"` tool update (e.g. *"Tool `image_to_video` failed: image reference not readable: …"* — grok occasionally malforms an image argument) used to render as nothing, so grok just looked like it gave up. The row now goes error-colored with the failure message beneath it (and a collapsed group with a failed child tints its icon red). ([media/webview-helpers.js](media/webview-helpers.js), [media/chat.js](media/chat.js), [media/chat.css](media/chat.css))
- **Empty "primer" sessions stop piling up in history (#24).** Each time the extension opened it left behind an empty, primer-only session (the ones titled "… Primer v4 Plan Mode …"). Now abandoning an empty session — New Session, or switching to another — deletes it on the spot, so at most one untitled **New session** ever exists; and a one-shot startup sweep clears the empties earlier runs left behind, each confirmed primer-only by **reading its chat history** so a real or non-extension session is never touched. Detection is content-based and agent-agnostic — it counts both `<user_query>`-wrapped prompts and the **unwrapped** ones grok/composer sends for slash commands like `/imagine` (so a real composer session is never mistaken for empty) — verified against real on-disk sessions from both the `grok-build` and `cursor` (composer) agents. The live untitled session always shows as **New session**, never grok's primer-derived title. ([src/sidebar.ts](src/sidebar.ts), [src/sessions.ts](src/sessions.ts), [src/grok-primer.ts](src/grok-primer.ts))

### Tests — 582

- New: tool-call categorization rebuilt from real Grok + Composer transcripts, the raw-pattern-leak fix, the unpredicted-tool fallback, narration↔tool-group interleaving, plan/permission cards landing below the interleaved lead-up, the per-row **category icons** (strongest-action pick), and **failed-tool surfacing**, driving the real `media/chat.js` ([test/tool-summary.dom.test.ts](test/tool-summary.dom.test.ts)); the thinking↔tool **chevron unification** ([test/webview-ui.dom.test.ts](test/webview-ui.dom.test.ts)); empty-primer-session detection incl. unwrapped composer prompts — `extractUserQueries` / `classifyUserQueries` / `isEmptyPrimerSession` ([test/sessions.test.ts](test/sessions.test.ts)) and `isPrimerSummary` ([test/grok-primer.test.ts](test/grok-primer.test.ts)).

## 1.4.19 — 2026-06-28

> Card-UX polish from a live image-generation session: permission cards read in order and minimize once answered, restored plans start collapsed, and background-task notices stop polluting the chat.

### Fixed

- **Grok's reply after a permission prompt now renders *below* the card, not above it.** A permission request arrives mid-turn, so streaming kept appending to the agent bubble already on screen *above* the new card — only a fresh user turn pushed the conversation past it. The card now finalizes the in-flight turn first (the `commitAgentTurn()` the plan card already used), so everything after the answer lands beneath it, in order. ([media/chat.js](media/chat.js))
- **Answered permission cards no longer reappear *active* when you re-focus a backgrounded session.** Re-focusing replays the session's post buffer, but the answer (a webview-only collapse) was never in it, so an already-decided card came back fully expanded with live buttons. The host now records a `permissionResolved` marker in the buffer on answer, so the replayed card comes back collapsed. ([src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))

### Added

- **Answered permission cards now persist across a full reload.** The CLI doesn't replay `session/request_permission` on `session/load`, so resumed sessions used to lose every approval you'd made. The extension now persists each answered card (title + allowed/rejected + the gated tool-call id) and replays it as a **collapsed** card **anchored to the exact tool it gated** — by tool-call id, or by the tool's title when no id was captured (the card title *is* the tool's title) — so it lands where you answered it, mid-turn, not at the turn boundary (with a user-message-position fallback if the tool never replays). ([src/sidebar.ts](src/sidebar.ts), [src/session.ts](src/session.ts), [src/sessions.ts](src/sessions.ts), [src/acp-dispatch.ts](src/acp-dispatch.ts), [media/chat.js](media/chat.js))

### Changed

- **Answered permission cards collapse to one muted line.** Picking an option used to leave the full card with greyed-out buttons and a "you chose: …" note in the transcript. It now minimizes to a single non-interactive line — a colored `Allowed` / `Rejected` verb plus what it applied to — matching the resolved question/plan cards, with the "Grokking…" indicator underneath until grok resumes. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css))
- **Restored plan cards start collapsed.** Resuming a long session no longer dumps full plan text — each restored plan shows its title, verdict, and a `Show plan` / `Hide plan` toggle (the body stays in the DOM, just hidden). ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css))
- **Background-task completion is a one-shot toast, not a chat bubble.** When grok backgrounds a long command (e.g. a nested `grok -p …` image/video job), the CLI emits a structured `task_completed` update *and* feeds the result back as a `user_message_chunk` wrapped in `<system-reminder>…`. The extension now routes `task_backgrounded` / `task_completed` to their own events, pops a single `showInformationMessage` (with **Show Logs**) on completion — skipped during session replay — and drops the replayed `<system-reminder>` turn so it never surfaces as a fake user bubble on restore. ([src/acp-dispatch.ts](src/acp-dispatch.ts), [src/acp.ts](src/acp.ts), [src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))

### Tests — 545

- New: `task_backgrounded` / `task_completed` routing, `summarizeBackgroundCommand`, and `permissionOutcomeFor` ([test/acp-dispatch.test.ts](test/acp-dispatch.test.ts)); permission-card ordering + collapse + re-focus survival + restored-collapsed-card interleaving, restored-plan collapse toggle, and `<system-reminder>` suppression on restore, driving the real `media/chat.js` ([test/card-collapse-tasks.dom.test.ts](test/card-collapse-tasks.dom.test.ts)).

## 1.4.18 — 2026-06-28

> Grok CLI fixed the #22 Windows session-start regression (0.2.71, now on stable as 0.2.72) — adopt it and re-enable updates.

### Fixed

- **Sessions start on the latest Grok CLI again, and Windows updates are no longer paused (#22).** xAI fixed the `agent stdio` regression that hung session start on Windows across 0.2.61–0.2.70 (initialize on 0.2.61–0.2.64, then `session/new` on 0.2.67–0.2.70). The fix landed in **0.2.71** and is now on the **stable** channel as **0.2.72**. Verified end-to-end on native Windows — the `session/new` stdin-open probe passes and the full live ACP gate is green (handshake, prompt round-trip, session restore, plan-mode, subagent). The extension now treats **0.2.72 as the supported build**: it pins the bounded broken range **0.2.61–0.2.70** up to 0.2.72 before starting, and the gear → **Update Grok Build CLI** action (and the silent on-upgrade update) work normally again on Windows. The reactive downgrade-on-failure remains a backstop for any *future* still-broken build above 0.2.72. ([src/cli-locator.ts](src/cli-locator.ts), [src/sidebar.ts](src/sidebar.ts))

## 1.4.17 — 2026-06-27

> Pin Windows to the last working Grok CLI for *any* newer build — 0.2.61–0.2.69 all break session start (#22).

### Changed

- **The #22 Windows guard now pins *any* Grok CLI build above 0.2.60 back to 0.2.60 before starting**, instead of tracking a fixed broken range. 0.2.61–0.2.64 hang at `initialize`; 0.2.67 (stable) and 0.2.69 (alpha) answer `initialize` but hang at `session/new` — the bug has persisted on every build above 0.2.60, with no fix on either channel. Rather than widen a range per build (and eat a ~120s reactive hang on each new one), the extension treats everything newer than the supported 0.2.60 as broken on Windows. When xAI ships a build that passes the `session/new` check, raising the supported version one line adopts it; the reactive downgrade-on-failure stays as a backstop. ([src/cli-locator.ts](src/cli-locator.ts))

## 1.4.16 — 2026-06-26

> Clearer listing and docs; lighter changelog.

### Changed

- **README rewritten** to lead with what the extension does for you — diff-preview approvals, `@file` context, inline image/video, voice — instead of internals, with a trimmed feature list.
- **Listing clarified** as an **unofficial community extension** (display name + description).
- **Changelog slimmed:** releases before 1.4.0 moved to [docs/CHANGELOG-ARCHIVE.md](docs/CHANGELOG-ARCHIVE.md); entries stay terse going forward.

## 1.4.15 — 2026-06-26

> Cover the #22 Windows session-start bug on newer Grok CLI builds (through 0.2.67) and when the hang moves to session start.

### Fixes

- **The Windows session-start workaround now covers Grok CLI 0.2.65–0.2.67 and a `session/new`-stage hang (#22).** Grok CLI 0.2.67 *looked* fixed — the ACP `initialize` handshake answers again — but the stdin-until-EOF regression only **moved**: the next request, `session/new`, now hangs instead (with stdin held open, as any live client must), so a real session still can't start. v1.4.14 only knew the 0.2.61–0.2.64 range and only recognized an `initialize`-stage hang, so anyone landing on 0.2.65–0.2.67 was left stuck. Now: the proactive pin covers the full confirmed-broken range **0.2.61–0.2.67** and pins the CLI back to the last fully-working **0.2.60** before starting; and the evidence-driven reactive recovery also fires on a **`session/new` / `session/load`** timeout, not just `initialize` — so a future still-broken build self-heals on the observed failure regardless of which startup request hangs. Verified with a controlled stdin-open probe (`initialize` then `session/new`) against real 0.2.67. ([src/cli-locator.ts](src/cli-locator.ts), [src/sidebar.ts](src/sidebar.ts))

### Docs

- Recorded that **0.2.67 does not fix #22** — the hang moved from `initialize` to `session/new` — with the reproduction probe in [research/stdio-eof-regression.md](research/stdio-eof-regression.md). Rewrote CLAUDE.md's status into a concise current-state project map (per-version history lives here in the changelog, not there).

## 1.4.14 — 2026-06-25

> Smoother diff review on permission cards.

### Features

- **Diff previews don't nag you to save, auto-open, and clean up after themselves (#21).** Closing a diff preview **no longer prompts you to save**: every diff the extension opens — whether from the *open diff preview →* link on an edit card or auto-opened on a permission card — is now backed by read-only virtual documents instead of scratch buffers, so there's nothing to save (and you also get proper syntax highlighting now). On a permission card the diff also **opens automatically** (the *open diff →* button stays, to re-open it) and **closes itself** when you click **Allow / Reject**. The preview reuses a single tab across Grok's many small sequential edits and keeps focus on the chat, so reviewing a stream of edits is just: glance, decide, repeat. ([src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))

## 1.4.13 — 2026-06-25

> Self-healing recovery if a *future* Grok CLI build ships the same Windows bug. _(Not released on its own — rolled into the 1.4.14 release.)_

### Fixes

- **Auto-recovers from a still-broken future CLI build, not just the known ones (#22).** v1.4.12 pins the CLI back to 0.2.60 when it detects one of the *known* broken builds (0.2.61–0.2.64) before starting. But if xAI ships a **new** build (0.2.65+) that still has the bug, that closed range wouldn't catch it and the session would hang with no automatic fix. The extension now also recovers **reactively**: if a session fails to start on Windows with the regression's signature (the `initialize` handshake timing out / *"exited (code null)"*) and the CLI is on any build newer than the supported 0.2.60, it automatically downgrades to 0.2.60 and **retries the start once** — triggered by the actual failure rather than a hardcoded version list, so it self-heals on builds that don't exist yet. If you later update the CLI by hand onto another broken build, the same recovery runs again on the next failure. Every automatic downgrade (proactive or reactive) shows a notification explaining what happened. If the downgrade can't run, you still get the manual-workaround message as before. ([src/cli-locator.ts](src/cli-locator.ts), [src/sidebar.ts](src/sidebar.ts))

### Internal

- Verified on macOS (Apple Silicon) that the regression is **Windows-only** — grok 0.2.64, the build that hangs on Windows, completes the stdin-open ACP `initialize` handshake in ~450ms (4/4 runs) — so the whole workaround stays correctly gated to Windows. Recorded in [research/stdio-eof-regression.md](research/stdio-eof-regression.md) with a reproduction probe. ([research/stdio-eof-mac-probe.cjs](research/stdio-eof-mac-probe.cjs))

## 1.4.12 — 2026-06-25

> Works around a Grok CLI 0.2.61+ bug that stopped sessions from starting.

### Fixes

- **Sessions start again on Grok CLI 0.2.61–0.2.64 (#22).** A regression in the Grok CLI broke `grok agent stdio`: the agent no longer reads its first line of input until the input stream is closed, which never happens for a live connection — so the extension's startup handshake hung forever and you saw *"Grok exited (code null)"* / *"ACP request timed out: initialize"*. The last working build is **0.2.60**. Since the extension can't make the CLI read its input, it now **detects a broken CLI version on startup and automatically pins it back to 0.2.60** before connecting, with a one-time notice — no manual downgrade needed. Once the CLI is healthy again nothing is changed. If the automatic downgrade can't run, the start-failure message now tells you exactly how to fix it by hand (`grok update --version 0.2.60`). The version range is bounded to the known-broken builds so a future fixed release won't be needlessly downgraded. (The regression has so far only been reported on Windows, so the automatic pin and the update guard below currently apply there.) ([src/cli-locator.ts](src/cli-locator.ts), [src/sidebar.ts](src/sidebar.ts))
- **"Update Grok Build CLI" won't move you onto a broken build.** Because Grok CLI 0.2.61+ is unusable by the extension (above), the gear → **About** update action is now **disabled with a note** when you're on the latest supported version (0.2.60) or newer — so a one-click update can't reinstall a broken build. It stays enabled only when you're on something *older* than 0.2.60, and in that case it updates **to 0.2.60** (never to an unsupported `latest`). The silent on-upgrade CLI update follows the same rule. ([src/cli-locator.ts](src/cli-locator.ts), [src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))

### Docs

- Documented the root cause, the controlled reproduction, and a copy-paste bug report for xAI in [research/stdio-eof-regression.md](research/stdio-eof-regression.md).

## 1.4.11 — 2026-06-20

> Nested code blocks render correctly.

### Fixes

- **Nested code blocks no longer eat the outer fence (#20).** Asking the chat for a code block fenced by 4 or 5 backticks (so it can contain an inner ```` ``` ```` block) used to strip the first three backticks of the outer fence and close the block early at the inner fence — splitting one block into several and mangling the output. The Markdown renderer now matches a fence of three-or-more backticks and requires the closing fence to be the same length, so a longer outer fence correctly wraps shorter inner ones (per the CommonMark spec). This makes clean, copy-pasteable nested examples (e.g. for an `AGENTS.md`) render the same as on grok.com and in the Grok CLI. ([media/chat.js](media/chat.js))

## 1.4.10 — 2026-06-18

> Session history that stays fast with thousands of sessions.

### Features

- **Session history loads in pages and stays fast at scale.** The history dropdown used to read and parse *every* saved session on each open, which got slow once a project had hundreds or thousands of them. It now loads the **most recent 100** (newest first by last activity) and pulls in older ones as you **scroll to the bottom**. The **search box** filters by name across your **entire** history — not just the loaded page — so you can still find an old session instantly. Behind the scenes it orders sessions with one cheap directory `stat` each (no file reads), reads only the page you're looking at, and caches by file modification time so re-opening the dropdown costs effectively no disk reads. ([src/sessions.ts](src/sessions.ts), [src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js), [media/chat.css](media/chat.css))
- **Switching model or reasoning effort on a fresh session no longer clutters history.** Some model and effort changes need the session to restart. If you flip them a few times right after opening a session — before you've actually said anything — each restart used to leave behind an empty, identical session in your history. Now an empty session (one where only the hidden setup has run) restarts cleanly with no "Summarize & Restart vs. Just Restart" prompt, and the throwaway session is removed instead of piling up. If you had renamed that session, the name carries over to the restarted one. ([src/sidebar.ts](src/sidebar.ts), [src/sessions.ts](src/sessions.ts))

### Fixes

- **History dropdown no longer opens clipped off the right edge.** Opening the session-history popover quickly (before its rows had finished loading) could position it too far right, so it spilled past the panel edge and only looked right after closing and reopening. The popover is now right-aligned to the panel (respecting the edge padding) and grows leftward, so it stays fully on-screen no matter how its contents resize as sessions load in. In a narrow panel it also caps its width to fit, so a long session name truncates with an ellipsis instead of pushing the popover off the left edge. Resizing the panel while the dropdown is open now re-fits it live (no need to close and reopen), and switching to another panel tab or extension closes it so it can't reappear mis-sized when you come back. ([media/chat.js](media/chat.js))

### Internal

- **Opt-in performance simulation for the history popover.** A new `npm run test:perf` suite (kept out of `npm test` and CI) builds a 5000-session in-memory store and asserts the access-count improvement: first open drops file reads from 5000 to 100 (~98%), a repeat open does zero reads (modification-time cache), and search warms the catalog once then stays read-free — with a modeled-latency projection and a real in-memory parse-cost wall-clock. ([test/sessions.perf.ts](test/sessions.perf.ts), [vitest.perf.config.ts](vitest.perf.config.ts), [package.json](package.json))

### Docs

- Documented the pagination design in [docs/architecture.md](docs/architecture.md) (§ History at scale) and [CLAUDE.md](CLAUDE.md) (§ History pagination), and updated the *Session history* feature note in the [README](README.md).

## 1.4.9 — 2026-06-16

> Make the chat bigger — just the chat.

### Features

- **Adjustable chat font size (#14).** A new `grok.chatFontScale` setting zooms the Grok chat panel only — text, icons, and spacing together — as a percent (e.g. `150`, `200`, or smaller like `70`). Unlike VS Code's global `Ctrl/Cmd+Shift+=`, it leaves the rest of the editor at its normal size, so you can enlarge (or shrink) just the chat for readability. It applies live with no reload, the composer stays pinned to the bottom of the panel at any scale, and it works at both User (global) and Workspace (local) scope. ([package.json](package.json), [src/sidebar.ts](src/sidebar.ts), [media/chat.css](media/chat.css), [media/chat.js](media/chat.js))

### Docs

- **README polish.** Added screenshots for *Voice input* and the *Agent Dashboard*, and moved a few wire-level implementation details out of the feature blurbs into [docs/architecture.md](docs/architecture.md) so the feature list reads less like internals. ([README.md](README.md), [docs/architecture.md](docs/architecture.md))

## 1.4.8 — 2026-06-15

> Run several Grok sessions at once — switch between them instantly, and see at a glance which one needs you.

### Features

- **Multi-session Agent Dashboard.** The sidebar now keeps several sessions *alive* at once instead of one at a time. Switching between them from the history dropdown is **instant and lossless** — the conversation you switch away from keeps running in the background (mid-turn, mid-approval, anything), and switching back replays its exact state with no reload. Picking a session that isn't live anymore loads it from history as before. ([src/sidebar.ts](src/sidebar.ts), [src/session.ts](src/session.ts))
- **Status dots in the history dropdown.** Every session shows a dot so you can see what each one is doing without opening it. It's **gray** at rest, and only lights up when there's something to know: **blue** = working, **yellow** = needs you (a permission, question, or plan to review), **green** = finished with output you haven't opened yet, **red** = finished with an error you haven't opened. The green/red marker is an *unread* badge — it clears the moment you open the session, and it's **persisted**, so it survives the idle cleanup below and even a VS Code restart. Walk away, come back, and the green sessions are exactly the ones with results waiting. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css), [src/session-pool.ts](src/session-pool.ts))
- **Idle sessions are cleaned up automatically.** To keep a pile of background sessions from each holding a live process, a session left untouched for an hour — or beyond a cap of ~8 live — is quietly shut down (never one that's working or waiting on you). It reappears in history and reloads on click, so nothing is lost. ([src/session-pool.ts](src/session-pool.ts))
- **Updating the Grok Build CLI warns about sessions in progress.** With multiple sessions now able to run at once, the *Update Grok Build CLI* action confirms before it restarts when any session is mid-turn or waiting on you — so an update doesn't silently interrupt work in a background session. ([src/sidebar.ts](src/sidebar.ts))
- **No more long pause before Grok starts.** Sending your first message used to sit silent for 15–40 seconds before anything appeared. Behind the scenes the extension primes each session with a hidden plan-mode instruction, and that primer was running *in front of* your first message and — because Grok Build is an agentic CLI — was wandering off to read files and search the workspace before your real prompt even ran. The primer now fires **the moment a session goes live**, silently in the background, so it's almost always finished before you hit send; if you're quick, your message shows immediately and is released the instant the primer settles. The primer text itself was also trimmed to just the protocol it needs to teach (the product blurb and repo link that were tempting Grok to go exploring are gone), so it completes in a beat instead of dozens of seconds. ([src/sidebar.ts](src/sidebar.ts), [src/grok-primer.ts](src/grok-primer.ts), [src/session.ts](src/session.ts))
- **A "Grokking…" indicator while you wait.** Every turn now shows an animated *Grokking…* placeholder the instant you send, so there's immediate feedback that Grok received your message — it's replaced in place the moment the first thought, reply, or tool action arrives. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css))

## 1.4.7 — 2026-06-15

> Sharper math, and one-click export for equations and diagrams.

### Features

- **Math now renders with [MathJax](https://www.mathjax.org) (replacing KaTeX).** MathJax produces self-contained SVG that's closer to "real LaTeX," renders `\label`/`\ref`-style environments without painting red errors, and — crucially — gives every equation an exportable vector. Inline `\(…\)` sits on the text baseline in your editor's text color; display `\[…\]` gets its own centered, horizontally-scrollable block. The swap also fixed a double-rendering bug where Chromium drew MathJax's hidden accessibility MathML as a *second*, visible copy of each equation (`enableAssistiveMml: false`). ([media/chat.js](media/chat.js), [src/sidebar.ts](src/sidebar.ts), [media/mathjax/](media/mathjax/))
- **Copy / Download / Open actions on display math + Mermaid diagrams.** Hover any display equation or rendered diagram for a top-right overlay (mirrors the generated-image actions): **Copy** the LaTeX/Mermaid source, **Download** as an image, or **Open** it in VS Code's image preview. Download offers a quick-pick — **PNG** (rasterized with your VS Code theme background, i.e. what you see), or a **transparent SVG** tuned **for a dark** or **for a light** background. Math recolors its ink for each; Mermaid is re-rendered in its matching light/dark theme so a "for light background" diagram actually uses the light palette. ([media/chat.js](media/chat.js), [src/sidebar.ts](src/sidebar.ts))

### Internal

- **`video-gen` is excluded from the default live-test gate** (opt-in via `--only=video-gen`). In the headless test harness grok 0.2.x spins on `/imagine-video` instead of producing a clip, so it never completes — the feature works interactively, so a default-on test only produced noise. ([scripts/live-tests.cjs](scripts/live-tests.cjs))

## 1.4.6 — 2026-06-15

> Grok's Mermaid diagrams now render as diagrams.

### Features

- **Mermaid diagram rendering.** Grok answers with ` ```mermaid ` fenced blocks — flowcharts, sequence/state diagrams, git graphs, class diagrams, ER, pie, and more — which the chat previously showed as raw diagram source. These now render as real diagrams via the vendored **[Mermaid](https://mermaid.js.org)** library (bundled into the extension, no network — works offline and in the packaged build). The diagram is themed to match VS Code (dark/light) and gets horizontal scroll so a wide flowchart doesn't blow out the narrow sidebar. Rendering is asynchronous and DOM-based (Mermaid measures text to lay out nodes), so unlike the LaTeX path it runs as a post-render pass over the inserted message; an SVG cache keyed by the diagram source keeps the streaming bubble flicker-free (the agent message re-renders every animation frame) and stops the same diagram being laid out dozens of times before the first render resolves. A half-streamed block stays as plain text until its closing ` ``` ` arrives, and if Mermaid can't load or the diagram is malformed the readable source is shown instead of an error. ([media/chat.js](media/chat.js), [src/sidebar.ts](src/sidebar.ts), [media/mermaid/](media/mermaid/))

## 1.4.5 — 2026-06-15

> Grok's math now renders as math.

### Features

- **LaTeX / math rendering.** Grok increasingly answers with TeX — inline `\(…\)` and display `\[…\]` (including `\begin{pmatrix}` matrices, fractions, sums, Greek) — which the chat previously showed as raw backslash-soup. Math is now rendered with **[KaTeX](https://katex.org)**, vendored into the extension (no network, works offline and in the packaged build). The renderer pulls LaTeX out *before* HTML-escaping so the backslashes and braces survive intact; inline math flows with the text, display math gets its own block with horizontal scroll so a wide matrix doesn't blow out the narrow sidebar. A malformed expression renders as an inline red error (KaTeX `throwOnError:false`) instead of blanking the message; if KaTeX somehow can't load, the raw TeX is shown rather than swallowed. `\label{…}` (which Grok emits inside `align`/`equation` blocks for cross-referencing) is stripped before rendering — KaTeX has no `\ref`/`\eqref` system so it would otherwise paint the label as a red error, and `\label` produces no visible output in real LaTeX anyway. Single `$…$` is deliberately **not** a delimiter — too many false positives with prose currency ("$5 and $10"). ([media/chat.js](media/chat.js), [media/webview-helpers.js](media/webview-helpers.js), [src/sidebar.ts](src/sidebar.ts), [media/katex/](media/katex/))

## 1.4.4 — 2026-06-15

> You can read history again while Grok is thinking.

### Fixes

- **Scrolling up no longer gets yanked back down while Grok is thinking** ([#16](https://github.com/phuryn/grok-build-vscode/issues/16)). The chat snapped to the bottom on *every* streaming update, so any attempt to scroll up and re-read earlier messages (or Grok's own earlier reasoning) was undone on the very next thought chunk. The view now follows streaming output only while you're already pinned to the bottom; the moment you scroll up to read history, auto-scroll pauses and leaves you there. Genuinely interactive activity you need to see — **permission cards**, **ask-user-question cards**, and **your own sent message** — still pulls the view back down and re-pins. This also restores the ability to keep an eye on reasoning while permission cards stack up ([#15](https://github.com/phuryn/grok-build-vscode/issues/15)). ([media/chat.js](media/chat.js), [media/webview-helpers.js](media/webview-helpers.js))

## 1.4.3 — 2026-06-09

> Docs catch-up and a faster, leaner session start.

### Docs

- **README rewrite.** Restructured around three audiences: users get a clean **Requirements → Install → Quick start** path, then a **Features & capabilities** section where each feature is its own collapsible — ordered by what actually sells the extension (diff-preview approval, modes, `/imagine` images+videos, voice…) rather than by implementation. **Configuration**, **Commands & keybindings**, and **Development** each collapse into a single `<details>` so the page scans in seconds while staying self-contained for the Marketplace listing. The deep dive — diagram, message flow, module map, design notes, and the Plan-Mode "the one part that isn't thin" explainer — moved to a new [docs/architecture.md](docs/architecture.md), linked from a short *How it works* teaser.
- **Removed stale claims.** Dropped the **Subagents** feature section (still research-only — it rarely fires in practice, so it shouldn't read as shipped) and the "generated media is inlined as base64" known-limit (1.4.2 switched media to `asWebviewUri` streaming). Trimmed the opening screenshots to the sidebar + an inline `/imagine` result, with a *More screenshots* link to the folder; removed a decorative image that carried no information.
- **Canonical `README.md` / `CHANGELOG.md` casing.** The working-tree files were lowercase on disk (a Windows case-insensitivity slip) while git already tracked them uppercase; the disk now matches. (`vsce` still normalizes the *packaged* copies to lowercase inside the `.vsix` — that's its own convention, which the Marketplace renders fine.) `scripts/release.*` now reference `CHANGELOG.md` so the release-notes extraction works on case-sensitive filesystems too.

### Changed

- **The hidden plan-mode primer no longer costs a startup round-trip.** The extension sends Grok a hidden "primer" that teaches it the Plan-Mode verdict protocol. It used to fire at **every** session start — new *and* every restore — locking the composer until Grok acknowledged and burning a turn even on a session you only opened to glance at. It's now sent **lazily**, as its own hidden turn before your **first real prompt** — on a new *or* restored session — so it rides along with work you already triggered. The composer is ready the instant the session connects, and opening/abandoning a session (or restoring just to read history) costs nothing. Re-asserting the primer on the first post-restore send (rather than trusting a copy buried in replayed history, which a `/compact` can drop) keeps Plan Mode reliable across resumes. Best-effort and unchanged in protocol — the plan-gate remains the real enforcement. ([src/grok-primer.ts](src/grok-primer.ts), [src/sidebar.ts](src/sidebar.ts))

## 1.4.2 — 2026-06-09

> Generated video renders now, and inline media is a tighter thumbnail.

### Fixes

- **Generated videos (`/imagine-video`) finally render.** Detection, path extraction, MIME, and CSP were all already correct — the failure was the delivery: a multi-MB clip base64-inlined into a single `postMessage` `data:` URI was silently dropped, so the `<video>` got an empty source. Generated files are now served via `webview.asWebviewUri` (the grok home is a `localResourceRoots` entry), so the webview **streams the file straight from disk** instead of carrying it as a giant string — videos play, and large images load lazily. Files written outside the served roots still fall back to a base64 `data:` URI, so nothing regresses. ([src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))

### Polish

- **The Copy path / Open in VS Code hover icons now sit on the image.** They were anchored to the chat column's right edge, so on a thumbnail they floated in empty space well to the right of the picture. The media block is now sized to the rendered image, so the icons pin to the image's own top-right corner — for videos too. ([media/chat.css](media/chat.css))
- **Inline media is capped at 320px wide** (was 640px), so a generation reads as a compact thumbnail in the narrow sidebar instead of dominating the chat. The file is untouched — click an image (or **Open in VS Code**) for full resolution. ([media/chat.css](media/chat.css))

## 1.4.1 — 2026-06-09

> A two-part fix for generated images that stopped rendering in 1.4.0.

### Fixes

- **Generated images are visible again.** 1.4.0 capped inline media at 640px by wrapping it in a `width: fit-content` container. That made the `<img>`'s `max-width: 100%` resolve against an *indefinite* width, which collapses a replaced element to zero in Chromium — so every generation (including plain `/imagine`) rendered as an invisible, zero-width image. The container is now a normal block (definite width), so the percentage resolves correctly while the **640px cap stays**. ([media/chat.css](media/chat.css))
- **Reference-edited images (`image_edit`) now render too.** Editing a real photo with `/imagine` runs Grok's **`image_edit`** tool (title `imagine-edit: …`, variant `ImageEdit`) — a surface 1.4.0's detector didn't know about, so the saved file was never inlined. Confirmed live against grok 0.2.x: the completed result reports the path as the same machine-readable JSON `{path}` the other media tools use (an extended-length `\\?\C:\…` Windows path, stripped to canonical form). `isMediaGenToolCall` now recognizes it. ([src/acp-dispatch.ts](src/acp-dispatch.ts))

## 1.4.0 — 2026-06-08

> Two new CLI surfaces — generated image/video rendering and a Sign-Out action. The media wire format was confirmed live against grok 0.2.33 (see [research/image-generation.md](research/image-generation.md)). Available on the [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=PawelHuryn.grok-vscode-phuryn).

### Fixes

- **Every message you send no longer renders twice (grok 0.2.33 regression).** grok **≥0.2.33 echoes the live prompt back** as a `user_message_chunk` mid-turn — 0.2.3 did not (the code's own comment read "the agent never echoes them back"). The webview already renders the bubble optimistically from `send()`, so the echo produced a **second, duplicate bubble** (and double-counted `userMessageCount`, skewing plan positioning). The host now forwards `user_message_chunk` **only during a session/load replay** (a new `replaying` flag), and the webview's `appendUserChunk` guards the same — so a live echo can never double the bubble. ([src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))

### Image & video generation

- **Generated images and videos render inline.** When Grok generates an image (the subscription-only `/imagine`) or a video (`/imagine-video`), it now shows up as an actual image or a playable `<video>` in the chat instead of a dead tool chip. The real wire format (confirmed live, [research/image-generation.md](research/image-generation.md)) is **not** an ACP image block — Grok's **`image_gen`** / **`image_to_video`** tools write the file into the session directory (`images/*.jpg`, `videos/*.mp4`) and report the path as a JSON string inside the completed tool result's text. The host recognizes the media-gen call, parses the path out and classifies image-vs-video by extension (`isMediaGenToolCall`/`extractGeneratedMediaPaths`), reads the file and inlines it as a `data:` URI (webviews can't load arbitrary disk paths under the CSP — `media-src data:` was added for video), and the webview renders it. Hovering an image or video reveals two top-right icons (styled like the code-block copy button): **Copy path** and **Open in VS Code** — the latter is the only way to open a *video's* file, since its click drives playback controls (clicking an image still opens its source too). Inline media is capped at **640px** on the longer edge so full-resolution generations stay legible in the chat (the file is untouched). ACP-standard image/`resource_link` blocks are also handled as a forward-compatible fallback. Both render identically on **session resume** (Grok replays the generation as a single collapsed `tool_call`). ([src/acp-dispatch.ts](src/acp-dispatch.ts), [src/acp.ts](src/acp.ts), [src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js), [media/chat.css](media/chat.css))

### Account

- **Sign out from the extension (#13).** New `Grok: Log Out` command (palette) and a **Sign out** item in the gear menu run `grok logout` to clear the CLI's cached credentials, tear down the live session, and drop back to the auth-required onboarding screen — no more switching to a terminal to change xAI accounts. ([src/sidebar.ts](src/sidebar.ts), [src/extension.ts](src/extension.ts), [package.json](package.json), [media/chat.js](media/chat.js))

### Keeping the CLI current

- **The Grok Build CLI is updated silently when the extension upgrades.** Grok doesn't auto-update, so a user who installs a new extension version could be left on an older CLI whose wire format the new extension no longer matches. Now, the first time a session starts after the extension's own version changes, the host runs `grok update` once before spawning the CLI — so the next handshake reports the freshly-updated version. It fires **only on an actual upgrade**, never on a fresh install (the "not-first-run" rule — a clean install just records its baseline version), at most once per activation, via `execFile` while no grok process is alive (sidesteps the Windows binary lock), and is best-effort (a failed update logs and continues on the current binary). The gate is the pure, unit-tested `extensionWasUpgraded`. ([src/cli-locator.ts](src/cli-locator.ts), [src/sidebar.ts](src/sidebar.ts), [media/chat.js](media/chat.js))
- **The welcome status line tracks real readiness.** It now follows the true session-start lifecycle — `Updating Grok Build CLI…` (during a silent update) → `Starting…` (through the hidden primer turn, while the composer spinner is up) → `Connected · v<version>`. Previously it flipped to "connected" at the ACP handshake, *before* the primer had been sent and processed, so it claimed readiness while grok was still being primed; it now stays "Starting…" until the spinner actually clears. ([media/chat.js](media/chat.js))

### Gear menu & status polish

- **The gear menu gets an "Other" group with About, Config & debug, and Log out.** The flat Config / Account / Debug sections collapse into two sub-views (mirroring the Model picker): **About** shows the *This extension* + *Grok Build CLI* versions, checks for a newer CLI (`grok update --check`), and offers an **Update Grok Build CLI** action; **Config & debug** holds the config links + extension logs. The on-demand update tears the session down, runs `grok update`, then **resumes the same session** on the fresh binary (preserving the conversation), showing the `Updating… → Starting… → Connected · v<new>` lifecycle. ([media/chat.js](media/chat.js), [media/chat.css](media/chat.css), [src/sidebar.ts](src/sidebar.ts))
- **About shows the real CLI version, even on builds the handshake doesn't tag.** The native-Windows build doesn't report a version in the ACP `initialize` response, so About used to read a bare "—" right next to a confident "CLI is up to date". It now adopts the version the update check returns (`grok update --check`'s `currentVersion`), and the action collapses to a grayed "CLI is up to date" (no button) when there's nothing to do. ([media/chat.js](media/chat.js))
- **The Config & debug → MCP servers link works on Windows.** It used to type a quoted `"C:\…\grok.exe" mcp list` into the terminal, which PowerShell (the default Windows shell) parses as a string literal and rejects with "Unexpected token". It now launches grok directly as the terminal's own process (`shellPath`/`shellArgs` → `grok mcp list`), sidestepping shell quoting entirely. ([src/sidebar.ts](src/sidebar.ts))
- **Transient status text animates and is capitalized.** "Starting", "Updating Grok Build CLI", "Thinking", and "Summarizing" now show an animated trailing ellipsis (a CSS `::after` so the layout doesn't shift), and the welcome line reads "Starting…" / "Connected · v…" (capitalized). ([media/chat.css](media/chat.css), [media/chat.js](media/chat.js))

### Tests

- New grok-free tests for v1.4.0: the `image_gen`/`image_to_video` path-in-JSON result extraction (`isMediaGenToolCall`/`extractGeneratedMediaPaths`, classifying image vs video and covering the collapsed-resume shape) and ACP-standard image fallbacks (`extractImageContent`/`collectToolImages` across inline base64, resource blob, file/remote `resource_link`) plus image-vs-text chunk routing, and happy-dom DOM tests driving the real `media/chat.js` render paths — `addGeneratedMedia` (clickable inline `<img>`, `<video controls>`, remote-link fallback, and the hover **Copy path** / **Open in VS Code** actions for both image and video). Plus the silent-update gate (`extensionWasUpgraded` — fresh-install vs upgrade vs unchanged vs downgrade) and a happy-dom suite pinning the welcome version-line lifecycle (`Updating Grok Build CLI…` → `Starting…` at the handshake → `Connected · v<version>` only when the priming spinner clears, and no reversion on later busy toggles). And the 0.2.33 regression fixes: a fake-CLI scenario that echoes a live `user_message_chunk` + a DOM test asserting a single bubble (no duplicate), and a gear-menu suite (the Other group, the About panel's versions + `grokUpdateStatus`-driven update button incl. the version-from-update-check fallback, the Config & debug links). **401 grok-free tests total.**

---

Older releases (before 1.4.0): see [docs/CHANGELOG-ARCHIVE.md](docs/CHANGELOG-ARCHIVE.md).

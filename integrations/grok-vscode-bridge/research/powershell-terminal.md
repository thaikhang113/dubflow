# PowerShell terminal host on Windows (#46)

Why the extension runs the agent's `terminal/*` commands under PowerShell on
Windows (was cmd.exe), and the empirical evidence behind the trade-offs.

## Root cause

In ACP mode grok **does not run shell commands itself** — it sends
`terminal/create` with a command string and the *client* runs it
(`src/acp.ts` → `TerminalManager.create`). The old code spawned with
`shell: true`, and on Windows Node resolves that to `%ComSpec%` = **cmd.exe**.
Standalone `grok.exe` runs its own PowerShell session and never goes through
ACP, so the two hosts diverged: PowerShell profile functions and pipelines
(`… | Format-List`) failed under cmd, forcing the agent into retry/re-wrap
loops. The shell is the host's choice, not a CLI flag — so this is fixed
entirely in `resolveTerminalShell` (`src/terminal-manager.ts`).

## Fix

`resolveTerminalShell(platform, resolve, pref)`:
- POSIX → `true` (`/bin/sh`, unchanged).
- Windows `auto` → `pwsh.exe` → `powershell.exe` → cmd.exe (`true`).
- `pref === "cmd"` (`grok.terminalShell`) → force `true` (cmd.exe) — escape hatch.

Node runs a string shell as `<shell> -c "<command>"`; pwsh and Windows
PowerShell both accept `-c` as the `-Command` alias. Resolution is cached
(one `where` probe / process). `whichOnPath` skips the `\WindowsApps\`
Store-alias stub (a 0-byte reparse point `existsSync` reports as present but
that errors on run when the Store app isn't installed).

## Empirical findings (Windows PowerShell 5.1; pwsh absent on the probe box)

Faithful replication of Node's spawn path (`shell: "powershell.exe"`), probes in
`scratchpad/ps-*.cjs` at the time of writing:

- **Command transport is faithful.** 9/9 realistic embedded-double-quote
  commands survived intact through Node's non-verbatim libuv quoting:
  `Write-Output "hello world"`, `"it's fine"`, `node -e "console.log('OK')"`,
  a JSON payload, a backtick-nested quote (`"say `"hi`""` → `say "hi"`), a
  `git commit -m "msg with spaces"`-shaped arg, a quoted path with spaces. The
  *only* miss was bash/cmd-style `\"` escaping (`node -e "console.log(\"x\")"`),
  which PowerShell correctly rejects — grok won't emit that for a PowerShell
  target. So Node passes the string through and PowerShell parses it with
  PowerShell rules; **no silent mangling.**
- **UTF-8 output is not re-encoded.** `'✓'×60` → exactly 180 bytes, hex
  `e29c93…`, no U+FFFD — identical to cmd. PowerShell passes a native command's
  raw stdout bytes through. (Caveat: *cmdlet*-rendered non-ASCII text on 5.1
  goes through the OEM codepage; pwsh 7 defaults to UTF-8.)
- **Exit-code fidelity (5.1 only).** `node -e "process.exit(7)"` → PowerShell
  reports **1**, not 7. Windows PowerShell 5.1 collapses any non-zero native
  exit to 1; pwsh 7 preserves the exact code. `exit 0` stays 0. The agent acts
  on zero-vs-non-zero, which is preserved either way, and this matches what
  standalone grok sees.
- **`&&` chains (5.1 only).** `a && b` → **parse error** under
  `powershell.exe` ("The token '&&' is not a valid statement separator in this
  version."); `;` works. pwsh 7 accepts `&&`. This is the sharpest
  pwsh-vs-fallback gap — hence the "install pwsh 7" recommendation.

## Known trade-offs (documented, not fixed)

- **Fresh shell per command** re-runs `$PROFILE` on every `terminal/create`
  (standalone likely keeps one persistent session): adds latency, any profile
  stdout can prepend to captured output, and a `Restricted`/`AllSigned`
  execution policy makes 5.1 skip the profile + warn on stderr. Fixing needs a
  persistent session (conflicts with the per-terminal kill-tree model) —
  deferred.
- The `powershell.exe` 5.1 fallback is meaningfully weaker than pwsh 7
  (`&&`, exit codes, cmdlet output encoding). `grok.terminalShell: "cmd"` is
  the revert-to-legacy escape hatch.

## Plan-gate interaction

`shouldBlockTerminal` (`src/plan-gate.ts`) classifies the command *string* and
is shell-agnostic, so switching the host shell doesn't change verdicts — and the
read-only allowlist already contains PowerShell cmdlets/aliases
(`get-childitem`/`gci`/`get-content`/…), which only became meaningful once
commands actually run under PowerShell. No new bypass.

Consulted Fable (peer review) on the approach; it surfaced the embedded-quote,
exit-code-scoping, `&&`, WindowsApps-stub, and escape-hatch points captured
above.

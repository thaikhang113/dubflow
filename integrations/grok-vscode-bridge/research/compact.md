# /compact over ACP — dispatch rules, `_meta.totalTokens` semantics, async rewrite

Probe: `research/compact-probe.cjs` (needs a logged-in grok; `VARIANT=`,
`POST_COMPACT_WAIT_MS=`, `FILLER_BYTES=`, `GROK_BIN=` env knobs). All findings
verified against **grok 0.2.87** on 2026-07-07, model `grok-composer-2.5-fast`.

## The dispatch rule: position 0 of the text block, verbatim

Each variant seeds ~40KB of filler, sends a compact-shaped prompt, then sends a
trivial "after" turn. `_meta.totalTokens` per turn, plus the on-disk
`chat_history.jsonl` line/byte counts, tell the two outcomes apart:

| variant | prompt text shape | compact turn | dispatched? |
|---|---|---|---|
| A-bare | `/compact` | totalTokens **0**, zero updates, empty reply | **yes** |
| B-enveloped | `<vscode-context>…</vscode-context>\n\n/compact` | totalTokens **117688** (6x growth!), full agentic turn — grok *chats about* compact and explores | **no** |
| C-trailing | `/compact\n\n<vscode-context>…` | totalTokens 0, zero updates, empty reply | **yes** |
| D-trailing-block | `/compact\n\n<envelope>\n\n<selection block>` | totalTokens 0, zero updates, empty reply | **yes** |

So the CLI recognizes a slash command **only at position 0** of the prompt's
text block — but tolerates arbitrary trailing content after the command line.
That's the fix shape the extension uses (`buildPrompt`/`buildPromptWithImages`
with `slashCommand: true` flip to `<text>\n\n<context>`): the pre-fix builder
put the envelope FIRST, so with the implicit active-editor chip present, every
typed slash command (`/compact`, `/help`, custom skill commands…) silently
degraded into an ordinary LLM turn. `matchSlashCommand` (src/slash-filter.ts)
is the gate: token shape `^\/([A-Za-z0-9][\w.:-]*)(?:\s|$)` (rejects Unix paths
like `/tmp/foo` — no boundary after `tmp`) checked against the CLI's advertised
`availableCommands` (shape-only before the list arrives).

## `_meta.totalTokens` around a native compact

- The **compact turn's own response** reports `totalTokens: 0` — "context
  reset", not a real count. Its `inputTokens`/`outputTokens`/`cachedReadTokens`
  are a stale replay of the *previous* turn's numbers; only `totalTokens` is
  meaningful (as the reset marker).
- The **next turn** reports the true post-compact size. The webview must let
  the 0 through (`!= null`, not truthy — media/chat.js promptComplete): the old
  truthy gate froze the donut at the pre-compact value, which is exactly the
  "did /compact even work?" user report.
- Compact keeps a recency window: in the probe the 40KB filler was the most
  recent user message, so `after` came back ≈ the seeded size (19980 → 20209).
  A long multi-turn session compacts much better; don't read the probe's flat
  numbers as "compact does nothing".
- The compact turn also streams **no agent content** — the turn ends with an
  empty bubble and no on-screen sign it worked. The extension paints a
  live-only **"Compacted."** into that bubble when the prompt resolves
  (`messageChunk` emit in sidebar.ts, right before `agentEnd`). It rides the
  session buffer (survives re-focus) but is deliberately absent from grok's
  history, so a disk restore doesn't replay it — it confirms the *action*,
  not the conversation.

## The disk rewrite is async (~15s observed)

`chat_history.jsonl` is untouched when the compact turn's response returns
(5 lines before == right after) and is rewritten **~15s later** (5 → 4 lines,
a summary line replacing older turns). Implications:

- A probe (or test) that checks the file immediately after the response sees
  a false "no-op". Wait or poll.
- Killing the process (extension update teardown, window close, reaping)
  inside that window loses the compaction — the session reloads from the
  un-compacted history. Known, unguarded edge: cheap to re-run `/compact`,
  not worth a teardown delay.
- The live process is consistent with itself: an immediate next prompt uses
  the compacted context even if the file hasn't flushed yet.

## No `usage_update` (yet)

grok 0.2.87 emitted **zero** ACP `usage_update` notifications across every
variant (`usageUpdates: 0`), despite the RFD
(https://agentclientprotocol.com/rfds/session-usage) making it the standard
channel for session-level context usage (compact/restore/model-switch all
change it). Today the donut runs entirely off the prompt response's
`_meta.totalTokens`. **Future work:** when grok starts emitting `usage_update`,
route it through `acp-dispatch`/`acp.ts`/`sidebar.ts` and prefer `used/size`
over `_meta.totalTokens` for the donut — the per-turn accounting and the
session-level usage are different quantities and the donut really wants the
latter.

## Primer interaction

A native compact rewrites history around a summary, which can fold the hidden
plan-protocol primer away with everything else. The extension re-primes
(non-blocking `ensurePrimed`) right after a confirmed `/compact` turn — same
pattern as the restore path, which already distrusts a replayed primer for
exactly this reason.

Note on `available_commands_update`: the CLI re-broadcasts it at ordinary turn
boundaries (the probe saw one during the seed turn and one as the after turn
started), so command-list churn is NOT a compact tell. The only reliable
dispatch signals are the compact turn itself being empty (zero updates, empty
reply, `totalTokens: 0`) and the async history rewrite.

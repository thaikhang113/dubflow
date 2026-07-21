# Edit diffs inline (#45)

**Goal.** Show what an edit changed *in the chat transcript*, not only via a native diff-editor tab — and make it work under **Auto accept** (no permission card), which is the case the reporter hit.

## Wire facts (grok 0.2.99, native Windows; `research/edit-diff-probe.cjs`)

- An edit's `tool_call_update` carries the diff as a content block:
  ```json
  { "type": "diff", "path": "…/note.txt", "oldText": "alpha", "newText": "beta" }
  ```
  `oldText`/`newText` are the **replaced region** (search_replace's `old_string`/`new_string`), **not** the whole file and **not** a pre-computed diff. A new-file create sends `oldText: ""`.
- The diff block rides the `tool_call_update` **regardless of permission mode** — it is not gated by `session/request_permission`. So the review surface can be built purely client-side, independent of the permission flow.
- On **session/load** the same edit replays as a single completed `tool_call` that carries the diff in its own `content` (no separate update) — so extraction must run for both shapes (#30).

## The permission-card red herring

The old auto-surfacing of a diff came from the permission card auto-opening a native diff tab (#21). That path is unreliable to depend on:

- With `permission_mode = "ask"`, `yolo = false`, `support_permission` either value, **and even a pristine default config**, `grok agent stdio` on this machine sends **0** `session/request_permission` for an in-workspace edit (probe reproduced with the extension's exact `initialize` handshake). A different machine *does* prompt for the same edit — so **whether the card appears is grok-build/platform-dependent, not a config toggle**.
- Under Auto accept / `always-approve` there is deliberately never a card.

Conclusion: don't tie diff visibility to the card. Render from the always-present wire diff instead.

## Implementation (all client-side)

- `computeLineDiff(oldText, newText)` — pure, `media/webview-helpers.js`. LCS backtrack → `{lines:[{type:'ctx'|'add'|'del',text}], added, removed, truncated}`. CRLF normalized for compare **and** display; empty region = 0 lines (new file = pure adds); huge regions skip the O(m·n) table (flat replace, `truncated`).
- `attachDiffPreviewToToolItem(toolCallId, diffs)` / `applyToolDiffs(call)` — `media/chat.js`. Always-visible `+N −M` on the row + group-header roll-up (path-deduped), an expandable inline diff riding the command IN/OUT expand machinery (`has-details` + `wireCommandToggle` + `detailShouldExpand`). Handles multiple `diff` blocks per call; idempotent on buffer replay.
- `buildInlineDiffRegion` — Codex-style rendering: a `.tool-diff-region` of `.tdl` grid rows `[+/− sign][line-number gutter][code]`, colored left-border stripe + subtle per-line tint (`MAX_INLINE_DIFF_LINES = 400`, then `open diff →`). Line numbers are region-relative (no file offset on the wire); the sign is a color-blind affordance. Palette = **Codex's exact green/red** via `--tdiff-*` vars (dark default + `body.vscode-light` override), reused by the `+N −M` stat.
- The gear toggle `grok.expandCommandOutputs` label was renamed **Expand tool details** (key unchanged) since it now governs edit diffs as well as command IN/OUT.

## Tests

- `test/webview-helpers.test.ts` → `computeLineDiff` (word change, context, new file, deletion, CRLF, size-cap).
- `test/tool-edit-expand.dom.test.ts` → row `+N −M`, group-header totals + path dedupe, inline diff render, expand via row click, `open diff →`, replay idempotency, new-file, restore, expand-tool-details pre-open.
- `test/command-details.dom.test.ts` → exit-0-no-output done marker (empty-pre drop) + non-zero/whitespace variants.

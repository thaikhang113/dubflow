# Vision input over ACP (`session/prompt` image content blocks)

**Verdict (grok 0.2.87 stable, Linux, 2026-07-07):** `grok agent stdio` **accepts**
inline `{type:"image", mimeType, data:<base64>}` content blocks in
`session/prompt` and the model genuinely sees the pixels — **even though
`initialize` still advertises `promptCapabilities.image: false`.** The
capability flag is stale; behavior, not the advertisement, is authoritative.
That's why the extension does **not** gate image sends on the flag (a gate
would kill a working feature), and instead pins the behavior with the
`vision-prompt` live test (`scripts/live-tests.cjs`) so a build that starts
*rejecting* image blocks — the way `audio:false` builds reject audio with
`-32602` (see [voice-input.md](voice-input.md)) — fails the release gate
instead of shipping.

## Probe results (`vision-probe.cjs`)

| Probe | Result |
|---|---|
| `initialize` → `promptCapabilities` | `{"image":false,"audio":false,"embeddedContext":true}` — unchanged from the 0.2.x capture in [plan-probe.log](plan-probe.log) |
| 256×256 solid-red PNG (`image/png`) | **ACCEPTED**, `stopReason:"end_turn"`, model replies `"red"` — it decoded the pixels |
| 1×1 PNG | Turn succeeds but the pipeline drops the attachment: *"The attached image was dropped as too small"* — and the model then went hunting the workspace for an image file. A dangling `[Image #N]` tag with no delivered image actively misleads the model; this is why the extension **blocks the send** when an attachment can't be read, rather than skipping it silently. |
| Same red square as `image/svg+xml` (`PROBE_SVG=1`) | **ACCEPTED**, model replies `"red"` (CLI appears to rasterize). The extension still routes SVG as a plain **path chip**, not vision — an attached SVG is an editable text source the user usually wants grok to *read/edit*, and vision-izing it would destroy the file identity. xAI's docs only commit to jpg/jpeg/png (20 MiB/image): <https://docs.x.ai/developers/model-capabilities/images/understanding> |

Run it: `node research/vision-probe.cjs` (env: `PROBE_PNG_SIZE=<px>`,
`PROBE_SVG=1`, `GROK_BIN=<path>`). Needs a logged-in grok; burns credits.

## How the extension sends images (post-fix design)

- **Staging, not the session dir.** Pasted/imported images are written to
  `<globalStorage>/image-staging/` — session-NEUTRAL on purpose. Composer chips
  are provider-level state that outlives sessions, and a grok session dir is
  deleted by the empty-session cleanup (`parkFocused`,
  `discardRestartedEmptySession`, history delete, Clear all), which used to
  delete a pending screenshot before it was sent. Staged files are unlinked
  after the send (bytes ride the prompt inline) or when the chip is removed;
  a weekly-age sweep on activation reclaims orphans (age-gated so a second VS
  Code window's fresh staging files are safe).
- **Wire text shape** (`buildPromptWithImages`):
  `<vscode-context envelope>\n\n<user text>\n\n<tag lines>` — the user's text
  keeps position 0 (a leading tag broke `/command` dispatch), one
  `[Image #N]` tag per trailing line. Every tag's parenthetical carries a
  **do-not-Read hint**:
  `[Image #1] (attached inline — already visible to you; do not read it from disk)`
  for pasted images, and
  `[Image #2] (assets/hero.png — attached inline; act on the path if needed, but do not Read it)`
  for disk imports (the origin path is kept so grok can act on the real file,
  not just the pixels). The hint exists because of a Windows dogfood capture
  (2026-07-09): the CLI persists an incoming image block to its own
  `~/.grok/sessions/<…>/assets/image-<uuid>.png` and surfaces that path in the
  model's context, so the model `Read`-attempted the binary — `Cannot read
  binary file` — on a pasted image whose pixels it had *already* received (its
  answer was unaffected; the failed read is pure transcript noise). The hint
  suppresses that at the point of temptation instead of adding a global rule
  to the plan-mode primer (primer additions have blast radius — see the v3→v4
  history in CLAUDE.md). No images → byte-identical to `buildPrompt`.
  The restore side parses tags back out via `parseImageTags`
  (media/webview-helpers.js), stripping the hint so restore sees a clean path
  (or none) — hint-less legacy tags and leading/inline legacy shapes from the
  first build are also stripped; a tag-looking string in the *middle* of the
  user's words is left alone.
- **`[Image #N]` numbering is session-scoped** (`Session.imageCounter`,
  re-seeded from replayed prompts on restore) so two screenshots in one
  conversation never share a tag.
- **Send is validated, never silent.** Every visible image chip is pre-read on
  the host before anything is cleared or sent; any failure blocks the send
  with the chips intact and an error in the chat. Formats are whitelisted to
  png/jpe?g/gif/webp (paste re-checked host-side) and capped at the documented
  20 MiB.

# Slash commands

Slash commands are sourced live from the running CLI via the ACP `available_commands_update` notification — the autocomplete list reflects exactly what your installed `grok` version and auth method expose. Type `/` in the composer to open it.

This page is a snapshot for reference; the autocomplete list is the source of truth. Skills installed under `~/.grok/skills/` or `~/.grok/bundled/skills/` also appear in autocomplete as `/<skill-name>` but are not documented here — they vary per install and are owned by their respective `SKILL.md` files.

Snapshot last reconciled against a recent `grok` 0.2.x build; the autocomplete list is the source of truth.

## Built-in

| Command | Effect |
|---|---|
| `/compact` | Compress conversation history to save context (optional hint about what to preserve). The context donut refreshes with the true post-compact size moments after "Compacted." |
| `/session-info` | Show session details (model, turns, context usage) |
| `/flush` | Flush conversation memory to disk now |
| `/memory` | Browse, view, and manage your memories |
| `/dream` | Memory consolidation — merge session logs into organised topics |
| `/plugins` | Manage plugins — `list` / `reload` / `trust <path>` / `add <path>` / `remove <path>` |
| `/reload-plugins` | Reload plugins from disk (alias for `/plugins reload`) |
| `/feedback` | Send feedback about the current session |
| `/loop` | Run a prompt on a recurring interval |

## Hidden by the extension

The CLI advertises these over ACP, but the extension removes them from autocomplete and dispatch because they misbehave outside the CLI's own TUI:

| Command | Why hidden | Use instead |
|---|---|---|
| `/context` | Renders only in the CLI's own terminal UI — over ACP it streams nothing back ([#39](https://github.com/phuryn/grok-build-vscode/issues/39)) | `/session-info`, or click the **context donut** for the exact count |
| `/always-approve` | Silently flips a **global** `config.toml` setting that outlives the session ([#31](https://github.com/phuryn/grok-build-vscode/issues/31)) | The **Auto accept** mode in the bottom-toolbar picker (per-session, no config side effects) |

## Subscription only

Present in subscription mode, not on API-key auth.

| Command | Effect |
|---|---|
| `/imagine` | Generate an image from a text description (also edits a reference photo) |
| `/imagine-video` | Generate a video from a text description |

Since v1.4.0 the extension **renders the result inline** — `/imagine` output shows as an image (click to open the source file), `/imagine-video` as a playable `<video>`. Grok writes the file into its session directory and the extension serves it to the webview via `asWebviewUri` (streamed from disk; a base64 `data:` URI is used only as a fallback for files outside grok's served roots). Inline media is capped at 320px, and hovering an image/video reveals **Copy path** / **Open in VS Code** actions pinned to the media. When `/imagine` is given a source image to edit, grok runs an `image_edit` tool call, which the extension detects and renders the same way. See [research/image-generation.md](../research/image-generation.md) for the wire format.

## Not slash commands

A few things look like slash commands but are surfaced through the extension UI, not the CLI:

- **New session** — sidebar `+` button (`Grok: New Session` from the command palette)
- **Plan mode** — mode picker in the bottom toolbar; enabled and enforced client-side (Grok proposes a plan; workspace writes and non-read-only commands are blocked until you approve — see [src/plan-gate.ts](../src/plan-gate.ts) and [src/grok-primer.ts](../src/grok-primer.ts))
- **Auto accept (YOLO)** — mode picker; toggles auto-approval on the client side

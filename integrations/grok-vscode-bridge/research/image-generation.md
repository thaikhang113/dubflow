# Media generation (`/imagine`, `/imagine-video`) over ACP

Confirmed live against **grok 0.2.33** (device-auth login, subscription account),
`grok agent stdio`. Probes: `research/imagine-probe.cjs` (image),
`research/video-probe.cjs` (video). **Re-confirmed against the native-Windows
build `grok` 0.2.3** — which reports the saved path differently (prose, not JSON)
and uses a different video tool name. See [§ Native-Windows differences](#native-windows-differences-grok-02x).

## Summary

`/imagine` and `/imagine-video` are **subscription-only**. They run via grok's
built-in media tools, and the output file is **written to the session directory by
grok itself** — it does **not** come back as an ACP `image` / `resource` /
`resource_link` content block. Instead the file path is reported **inside a `text`
content block** on the completed tool update. Same idea for both images and videos;
only the folder + extension differ — and on native-Windows the text is **prose**
rather than JSON (next sections).

This is why a naive "render ACP image blocks" implementation renders nothing — the
real payload has to be parsed out of the tool result text.

The tools (from the bundled `~/.grok/skills/imagine/SKILL.md`):
- **`image_gen`** — new image from a text prompt (`/imagine`).
- **`image_edit`** — edit an existing image (prompt + source image).
- **`image_to_video`** — animate an image into a clip (the `/imagine-video`
  default; there is **no text-to-video** — video always starts from an image).
- **`reference_to_video`** — video from reference image(s).

## Wire sequence

For prompt `"/imagine a small red cube on white background"`:

1. `tool_call` — `title: "image_gen"`, `toolCallId: "call-…"`,
   `rawInput: { prompt: "a small red cube…", aspect_ratio: "1:1" }`
2. `tool_call_update` — relabeled `title: "imagine: a small red cube…"`,
   `rawInput: { variant: "ImageGen", prompt, aspect_ratio }`
3. `tool_call_update` — `status: "completed"`, `title: null`, and:

```json
"content": [
  { "type": "content",
    "content": {
      "type": "text",
      "text": "{\"path\":\"/root/.grok/sessions/%2Ftmp%2Fgrok-probe/<sid>/images/1.jpg\",\"filename\":\"1.jpg\",\"session_folder\":\"images\",\"message\":\"Image generated and saved to …. Do not read or re-display it, and do not describe how it appears to the user.\"}"
    }
  }
]
```

- The file is a real JPEG (observed **1024×1024**, ~148 KB, ~3–5 s to generate).
- The path is **absolute and real** even though the cwd segment is URL-encoded
  (`%2Ftmp%2Fgrok-probe`) — that's just grok's session-dir naming. It reads fine
  via `vscode.workspace.fs.readFile(Uri.file(path))`.
- The `message` field's "Do not read or re-display it" is an instruction to the
  **agent** (to save context), not to us — the client UI displaying the image is
  the whole point.

## Video wire sequence (`/imagine-video`)

`/imagine-video` is a **skill** (`~/.grok/skills/imagine/`), not a single tool —
grok first generates a source image with `image_gen`, then animates it. For the
prompt "generate a red cube then animate it with image_to_video":

1. `image_gen` → completed result `{ path: ".../images/1.jpg", session_folder: "images" }`
2. `tool_call` — `title: "image_to_video"`, `rawInput: { image: "<source .jpg path>", prompt, duration: 6, resolution_… }`
3. `tool_call_update` — relabeled `title: "image-to-video: <prompt>"`, `rawInput.variant: "ImageToVideo"`
4. `tool_call_update` — `status: "completed"`, `title: null`, content text JSON:

```json
{ "path": "/root/.grok/sessions/<…>/videos/1.mp4",
  "filename": "1.mp4", "session_folder": "videos",
  "message": "Video generated and saved to …. Do not read or re-display it, …" }
```

- Exactly the same envelope as `image_gen` — only the folder (`videos/`) and
  extension (`.mp4`) change. `duration` is 6s or 10s (skill default 6s).
- `reference_to_video` is analogous (`variant: "ReferenceToVideo"`); unprobed but
  covered by the same detector/extractor.

## Native-Windows differences (`grok` 0.2.x)

Both the **tool name** and the **completed-result text** differ on the native
build (captured live; the `image-gen`/`video-gen` live tests in
`scripts/live-tests.cjs` pin all of this):

| | Linux/macOS 0.2.33 | Native-Windows 0.2.3 |
|---|---|---|
| Image tool | `image_gen` → `imagine:` (variant `ImageGen`) | same |
| Video tool | `image_to_video` → `image-to-video:` (variant `ImageToVideo`) | **`video_gen`** → **`imagine-video:`** (variant **`VideoGen`**) — direct text-to-video, no source image |
| Result text | **JSON** `{"path":"…","filename":…,"session_folder":…}` | **prose** `Image generated and saved to \\?\C:\…\images\1.jpg.` |
| Path form | absolute, URL-encoded cwd segment | Windows path, often **`\\?\` extended-length prefixed** |

Verbatim native-Windows completed results:

```
Image generated and saved to \\?\C:\Users\Dell\.grok\sessions\<enc-cwd>\<sid>\images\1.jpg.
Video generated and saved to \\?\C:\Users\Dell\.grok\sessions\<enc-cwd>\<sid>\videos\1.mp4.
```

The extractor handles **both** forms: `JSON.parse` the text and read `.path`;
when that fails (`parsed === undefined`), fall back to a path regex over the prose
(`MEDIA_PATH_IN_TEXT_RE`) that matches image **and** video extensions, with the
`\\?\` prefix stripped by `cleanMediaPath`. The trailing sentence period is **not**
swallowed into the path (lookahead on the extension). `isMediaGenToolCall` matches
`video_gen` / `imagine-video:` / variant `VideoGen` in addition to the Linux names.

## How the extension handles it

- `isMediaGenToolCall(payload)` — flags the tool by `title` (`image_gen` /
  `imagine:` / `image_to_video` / `image-to-video:` / `reference_to_video`) or
  `rawInput.variant` (`ImageGen` / `ImageToVideo` / `ReferenceToVideo`). The host
  remembers the `toolCallId` so the **completed** update (null title) is still
  recognized. (`src/acp-dispatch.ts`)
- `extractGeneratedMediaPaths(payload)` — parses each `text` content block as JSON
  and returns any `.path` with a known image **or** video extension, tagged
  `media: "image" | "video"`. (`src/acp-dispatch.ts`)
- `AcpClient.emitToolMedia` — on every tool call/update, emits `mediaContent`
  for ACP-standard image blocks (`collectToolImages`, forward-compat fallback)
  plus the flagged media-gen path. (`src/acp.ts`)
- `GrokSidebar.postGeneratedMedia` — when the file lives under a
  `localResourceRoot` (the grok home), serves it to the webview via
  `webview.asWebviewUri` so the webview streams the bytes straight from disk
  (required for multi-MB videos, which a base64 `data:` inline silently dropped);
  files outside the served roots fall back to a base64 `data:` URI. CSP grants
  `img-src`/`media-src ${webview.cspSource} data:` — `cspSource` for the streamed
  source, `data:` for the fallback. Posts `{type:"media", media, src, mimeType,
  path}`. (`src/sidebar.ts`)
- `addGeneratedMedia` renders `<img>` (click opens the source file) or
  `<video controls>`. (`media/chat.js`, `media/chat.css`)

## Resume (`session/load`) — confirmed

On resume grok **collapses** the image into a **single completed `tool_call`**
(not the live tool_call + separate update). The one replayed payload carries
everything together: `title: "imagine: <prompt>"`, `status: "completed"`,
`rawInput.variant: "ImageGen"`, and the path-JSON content. Captured with
`research/resume-probe.cjs`.

Because the host's `handleSessionUpdate` runs identically for live and replay,
and this collapsed payload is *both* media-gen-detected (`isMediaGenToolCall`,
via the title) *and* path-bearing (`extractGeneratedMediaPaths`), the image
renders on resume with no extra code. The webview only suppresses the primer turn
(`suppressReplayTurn`), not real replayed turns. Locked by a unit test
("resume: the collapsed tool_call carries title + path together").

## Notes

- `/imagine-video` is **fully probed and live-tested on native-Windows** (tool
  `video_gen`, variant `VideoGen`, prose result). The path extractor accepts video
  extensions and tags `media: "video"` — confirmed end-to-end (`video-gen` live
  test renders a real `.mp4`).
- `initialize` advertises `promptCapabilities.image:false` — that's the **input**
  flag (sending images *to* grok), unrelated to image-generation **output**.

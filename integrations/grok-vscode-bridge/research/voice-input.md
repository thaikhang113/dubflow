# Voice input ("Grok Voice") — feasibility verdict

> **Superseded (shipped in v1.3.0).** This was the original feasibility log; its
> "not buildable today" conclusion was later overturned. Voice input **was** built —
> via "Path B" below: mic capture moved into the **extension host** (an `ffmpeg`
> child process), with transcription POSTed/streamed to `api.x.ai/v1/stt`. See
> [src/voice.ts](../src/voice.ts), [src/voice-recorder.ts](../src/voice-recorder.ts),
> [src/voice-streamer.ts](../src/voice-streamer.ts), the `grok.voice*` settings, the
> `ws` dependency, and CHANGELOG § Voice input. The verification probes are
> `research/voice-stt-probe.cjs`, `voice-stream-probe.cjs`, `voice-stream-verify.cjs`,
> `voice-e2e-verify.cjs`, `voice-cost-probe.cjs`. The **evidence** sections below
> remain accurate as the design rationale; read every "not possible / not buildable /
> either wall sinks it / no code was added" conclusion as the *pre-build* assessment.
> The one still-true limit: audio cannot ride the grok CLI/ACP pipe (Path A unrealized).

**Question.** Can we add a microphone button to the chat textbox that records the
user's speech and transcribes it into the input box, using the Grok Build CLI?

**Verdict: not possible *through the grok CLI surface*, but it is NOT an ACP
limitation and NOT a "Grok can't do it" limitation.** Precisely:

- **ACP supports audio.** `audio` is a first-class ACP content block; grok's own
  ACP layer deserializes it (`Audio(AudioContent { … })`) before refusing it. The
  protocol is not the wall.
- **The `grok agent stdio` coding CLI is the wall.** It declares
  `promptCapabilities.audio: false` and rejects audio blocks (`-32602`). The
  coding agent does not bridge to audio. This is the surface this extension uses,
  so for the extension as currently built, audio-in is impossible.
- **Grok-the-platform CAN do speech-to-text — on a *different* API.** xAI shipped
  a standalone **Grok Speech-to-Text API** (2026-04-18): `POST https://api.x.ai/v1/stt`
  (multipart file upload, `Authorization: Bearer $XAI_API_KEY`, 25 languages,
  word-level timestamps, ~$0.10/hr batch) plus a realtime Voice Agent API over
  WebSocket. This is a separate HTTP product, unreachable from `grok agent stdio`.

So the capability exists in Grok; it just isn't exposed on the pipe this thin
client talks to. Reproduced against native-Windows `grok` 0.2.3 by
`research/voice-probe.cjs`.

## Evidence

### 1. grok advertises `audio: false` in its `initialize` result

```json
"agentCapabilities": {
  "promptCapabilities": { "image": false, "audio": false, "embeddedContext": true }
}
```

Per ACP, `promptCapabilities.audio` is the agent telling the client whether it
accepts `audio` content blocks in `session/prompt`. grok says no. (It also says
no to `image` — grok-build is text/code only.)

### 2. Sending an audio block is rejected at the protocol layer

`research/voice-probe.cjs` opens a session and sends a valid `session/prompt`
with an `{ type: "audio", data: <base64 wav>, mimeType: "audio/wav" }` block.
grok responds:

```
-32602 Invalid params
data: "unsupported content block in prompt: Audio(AudioContent { … mime_type: \"audio/wav\" … })"
```

So even ignoring the advertised capability, the prompt schema hard-rejects audio.

### 3. No voice-related surface anywhere else

`available_commands_update` lists only `compact`, `always-approve`, `context`,
`session-info`. There is no transcription command, no `_meta` audio hook, and
grok cannot *generate* audio either (it emits text/tool-calls, no TTS). The
"ask grok to make WAV/MP3 test files" idea is therefore also a dead end —
grok has no audio output path.

## Why the surrounding environment can't fill the gap either

The mic-to-textbox UX strictly needs a speech-to-text engine that returns a
*string* to the webview. The candidate engines, and why each fails here:

| Engine | Outcome |
|---|---|
| **grok CLI** | Impossible — `audio: false`, rejects audio blocks (above). |
| **Web Speech API** (`webkitSpeechRecognition`) in the webview | Unavailable. VS Code is Electron; Electron ships without the Google cloud-speech API key that Chromium's `SpeechRecognition` depends on, so it errors `service-not-allowed`/never yields results. VS Code webviews further sandbox media. |
| **`getUserMedia` + a bundled WASM STT** (whisper.cpp / vosk) | Mic capture itself is impossible (see below); and it would mean shipping a multi-MB local model that is **not "Grok Voice"** — transcription from a third-party model with grok uninvolved. Out of scope for "using grok CLI". |
| **VS Code Speech ext** (`ms-vscode.vscode-speech`, bundled Whisper) | Its STT output is only consumable through VS Code's *proposed* `vscode.speech` API, which is gated by `enabledApiProposals` and blocked for released Marketplace extensions on stable VS Code. No public string-returning API. |

## Two paths to a real feature (neither shippable today)

**Path A — wait for the CLI to expose audio.** If a future `grok agent stdio`
flips `promptCapabilities.audio: true` and accepts audio blocks, we record with
`MediaRecorder` and send the clip as an `{type:"audio"}` block — fully inside the
existing thin-client architecture. Re-run `research/voice-probe.cjs` after any
grok upgrade to detect this.

**Path B — call the Grok STT API directly.** The extension could `POST` recorded
audio to `https://api.x.ai/v1/stt` and drop the returned transcript into the
textbox. This is genuinely "Grok Voice" (Grok's own STT), not third-party Whisper.
Blockers, all real:
1. **Separate auth — confirmed.** `~/.grok/auth.json` is an OIDC/OAuth login
   session: keyed by `https://auth.x.ai::<uuid>` with fields
   `key, auth_mode, refresh_token, expires_at, oidc_issuer, oidc_client_id, …` —
   the fingerprint of an interactive "Sign in with Grok" flow that mints
   short-lived access tokens. The STT API wants `Authorization: Bearer $XAI_API_KEY`,
   a long-lived `xai-…` developer key from a *different* domain (console.x.ai).
   So Path B requires the user to supply a separate xAI API key; it does NOT ride
   the CLI login. (Even if the OAuth token were technically accepted by
   `api.x.ai` today, that'd be undocumented cross-domain reuse — not shippable.)
2. **Billing.** ~$0.10/hr batch — a paid dependency the extension doesn't have today.
3. **Architecture break.** The extension is a thin client where *all* state lives
   in the CLI (see CLAUDE.md). A direct HTTP call to `api.x.ai` is a new, non-CLI
   network surface.
4. **Mic capture — hard wall (decisive).** VS Code webviews enforce a
   Permissions-Policy that omits `microphone`, so
   `navigator.mediaDevices.getUserMedia({audio:true})` throws *"microphone is not
   allowed in this document"* with **no permission prompt and no user override**.
   Open/unresolved VS Code limitation (microsoft/vscode #113916, #250568, #303293,
   2025–2026). The only workaround is capturing in an external browser tab — which
   defeats the in-sidebar mic button entirely. `MediaRecorder` is moot without a
   stream. This blocker is **independent of grok**: it kills the recording step no
   matter which transcription backend you use.

## Conclusion

The feature is **not buildable in this extension today**, blocked at two
independent layers:

1. **Capture** — VS Code webviews cannot access the microphone at all (no
   `getUserMedia`, no override). This alone is fatal and has nothing to do with grok.
2. **Transcription** — grok's coding CLI rejects audio; Grok's real STT lives on a
   separate paid API (`api.x.ai/v1/stt`) needing a separate `xai-…` key + billing +
   a non-CLI HTTP surface.

Either wall sinks it; together they make it clearly out of reach. It would become
viable only if BOTH (a) VS Code ships webview microphone support, and (b) we add
the STT API path (separate key + billing) or grok flips `promptCapabilities.audio`.
Re-run `research/voice-probe.cjs` after grok upgrades to track (b).

No code, version bump, changelog entry, or test was added — there is nothing
shippable to gate, and per repo convention version bumps are user-initiated.

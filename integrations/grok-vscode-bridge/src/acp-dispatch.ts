/**
 * Pure dispatch helpers for the ACP wire protocol.
 *
 * Kept separate from `AcpClient` (which spawns + I/Os) so we can unit-test
 * the line-parsing, response correlation, and update routing without faking
 * a child process.
 */

export type DispatchEvent =
  | { kind: "response"; id: number | string; result?: any; error?: any }
  | { kind: "session-update"; update: any }
  | { kind: "server-request"; id?: number | string; method: string; params: any }
  | { kind: "non-json"; line: string };

export function parseAcpLine(line: string): DispatchEvent | null {
  if (!line.trim()) return null;
  let msg: any;
  try {
    msg = JSON.parse(line);
  } catch {
    return { kind: "non-json", line };
  }
  if (msg.id != null && msg.method == null) {
    return { kind: "response", id: msg.id, result: msg.result, error: msg.error };
  }
  if (msg.method === "session/update") {
    return { kind: "session-update", update: msg.params?.update };
  }
  if (msg.method) {
    return { kind: "server-request", id: msg.id, method: msg.method, params: msg.params };
  }
  return null;
}

/**
 * A generated-media reference (image or video) normalized out of a tool result.
 * `media` discriminates `<img>` vs `<video>` rendering. `data` is base64 with an
 * inline `mimeType` (renders straight to a data: URI); `path` is a local file
 * (grok writes `/imagine` + `/imagine-video` output into the session dir — the
 * host reads + inlines it); `uri` is a remote/other URL opened as a link.
 */
export type MediaKind = "image" | "video";
export type MediaRef =
  | { media: MediaKind; kind: "data"; mimeType: string; data: string }
  | { media: MediaKind; kind: "path"; path: string; mimeType?: string }
  | { media: MediaKind; kind: "uri"; uri: string; mimeType?: string };

export type UpdateRoute =
  | { event: "messageChunk"; text: string }
  | { event: "userMessageChunk"; text: string }
  | { event: "thoughtChunk"; text: string }
  | { event: "mediaContent"; media: MediaRef }
  | { event: "toolCall"; payload: any }
  | { event: "toolCallUpdate"; payload: any }
  | { event: "plan"; payload: any }
  | { event: "modeChanged"; modeId: string }
  | { event: "commandsUpdate"; commands: any[] }
  | { event: "taskBackgrounded"; payload: any }
  | { event: "taskCompleted"; payload: any }
  | { event: "update"; payload: any };

const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|bmp|svg)$/i;
const VIDEO_EXT_RE = /\.(mp4|mov|webm|m4v)$/i;

// An absolute path (Windows drive / `\\?\` extended-length / UNC, or POSIX)
// ending in a known media extension, possibly embedded mid-sentence. Used to
// recover the file path from native-Windows grok's PROSE result ("Image
// generated and saved to <path>.") which — unlike the Linux/macOS JSON result —
// isn't machine-parseable. The trailing lookahead stops at the sentence's
// punctuation/whitespace so a trailing "." isn't swallowed into the path.
const MEDIA_PATH_IN_TEXT_RE =
  /(?:\\\\\?\\)?(?:[A-Za-z]:[\\/]|\/|\\\\)[^\r\n"'<>|?*]*?\.(?:png|jpe?g|gif|webp|bmp|svg|mp4|mov|webm|m4v)(?=$|[\s.,;:)"'\]])/gi;

/** Drop a Windows `\\?\` extended-length prefix so the path is canonical for fs + Uri.file. */
function cleanMediaPath(p: string): string {
  return p.replace(/^\\\\\?\\/, "");
}

function isImageMime(m: unknown): boolean {
  return typeof m === "string" && m.toLowerCase().startsWith("image/");
}

/** Classify a file path/uri as image or video by extension, or null. */
function mediaKindForPath(p: string): MediaKind | null {
  if (IMAGE_EXT_RE.test(p)) return "image";
  if (VIDEO_EXT_RE.test(p)) return "video";
  return null;
}

/** Normalize a file://-or-path URI to a {kind:"path"|"uri"} MediaRef. */
function refFromUri(media: MediaKind, uri: string, mimeType?: string): MediaRef {
  if (uri.startsWith("file://")) {
    try {
      return { media, kind: "path", path: decodeURIComponent(new URL(uri).pathname), mimeType };
    } catch {
      return { media, kind: "path", path: uri.replace(/^file:\/\//, ""), mimeType };
    }
  }
  if (/^[a-z]+:\/\//i.test(uri)) return { media, kind: "uri", uri, mimeType };
  // Bare filesystem path (absolute or relative).
  return { media, kind: "path", path: uri, mimeType };
}

/**
 * Pull an image out of a single ACP content block, or null if it isn't one.
 * grok's `/imagine` doesn't actually use these (it reports a path — see
 * `extractGeneratedMediaPaths`); this is kept as a forward-compatible fallback
 * for the standard ACP `image` block, embedded `resource`, and `resource_link`
 * shapes in case a future grok/tool emits them.
 */
export function extractImageContent(block: any): MediaRef | null {
  if (!block || typeof block !== "object") return null;
  if (block.type === "image" && typeof block.data === "string") {
    return { media: "image", kind: "data", mimeType: block.mimeType || "image/png", data: block.data };
  }
  if (block.type === "resource" && block.resource && typeof block.resource === "object") {
    const r = block.resource;
    if (typeof r.blob === "string" && (isImageMime(r.mimeType) || IMAGE_EXT_RE.test(String(r.uri ?? "")))) {
      return { media: "image", kind: "data", mimeType: isImageMime(r.mimeType) ? r.mimeType : "image/png", data: r.blob };
    }
    if (typeof r.uri === "string" && (isImageMime(r.mimeType) || IMAGE_EXT_RE.test(r.uri))) {
      return refFromUri("image", r.uri, isImageMime(r.mimeType) ? r.mimeType : undefined);
    }
  }
  if (block.type === "resource_link" && typeof block.uri === "string" &&
      (isImageMime(block.mimeType) || IMAGE_EXT_RE.test(block.uri))) {
    return refFromUri("image", block.uri, isImageMime(block.mimeType) ? block.mimeType : undefined);
  }
  return null;
}

/**
 * Collect ACP-standard image blocks out of a tool call's `content` array. Items
 * are either a bare content block or the ACP `{type:"content", content:<block>}`
 * wrapper. Forward-compat fallback — grok's real output path is
 * `extractGeneratedMediaPaths`.
 */
export function collectToolImages(payload: any): MediaRef[] {
  const arr = payload?.content;
  if (!Array.isArray(arr)) return [];
  const out: MediaRef[] = [];
  for (const item of arr) {
    const ref = extractImageContent(item?.type === "content" ? item.content : item);
    if (ref) out.push(ref);
  }
  return out;
}

/**
 * True for grok's media-generation tool calls (`/imagine`, `/imagine-video`).
 * The raw tool name and relabeled title differ by build/platform — confirmed
 * live against native-Windows grok 0.2.x AND the Linux 0.2.33 probes:
 *   - `/imagine`       → tool `image_gen`,  title `imagine: <prompt>`,        variant `ImageGen`
 *   - `/imagine` (edit of a reference image) → tool `image_edit`, title `imagine-edit: <prompt>`, variant `ImageEdit`
 *   - `/imagine-video` → tool `video_gen`,  title `imagine-video: <prompt>`,  variant `VideoGen`
 *     (older/Linux builds surfaced this as `image_to_video` / `image-to-video:`)
 *   - `reference_to_video` likewise.
 * See research/image-generation.md. The host tracks these ids so the *completed*
 * update (whose title is null) can still be recognized.
 */
export function isMediaGenToolCall(payload: any): boolean {
  if (!payload || typeof payload !== "object") return false;
  const title = String(payload.title ?? "");
  if (/^imagine(-video|-edit)?:/i.test(title)) return true;                   // relabeled titles
  if (/^(image_gen|image_edit|video_gen|image_to_video|reference_to_video)\b/i.test(title)) return true; // raw tool names
  if (/^(image-to-video:|reference-to-video:)/i.test(title)) return true;     // legacy relabels
  const ri = payload.rawInput;
  return !!(ri && typeof ri === "object" && typeof ri.variant === "string" &&
    /imagegen|imageedit|videogen|imagetovideo|referencetovideo/i.test(ri.variant));
}

/**
 * Pull generated-media file paths out of a completed image_gen/image_to_video
 * tool result. grok does NOT use an ACP image/resource block — it writes the
 * file to the session dir and reports the path inside a `text` content block, in
 * one of two shapes depending on the build:
 *
 *  - **JSON** (Linux/macOS, older builds): `{"path":"…/images/1.jpg",…}` for
 *    `/imagine`, `{"path":"…/videos/1.mp4",…}` for `/imagine-video`.
 *  - **Prose** (native-Windows grok 0.2.x): a human sentence with the path
 *    embedded, e.g. `Image generated and saved to \\?\C:\…\images\1.jpg.` —
 *    `JSON.parse` can't see this, so we scan the text for an absolute media path.
 *
 * We hand back a path MediaRef (the host inlines it), classifying image vs video
 * by extension. Only paths with a known image/video extension are accepted, so a
 * non-media result can't masquerade as one.
 */
export function extractGeneratedMediaPaths(payload: any): MediaRef[] {
  const arr = payload?.content;
  if (!Array.isArray(arr)) return [];
  const out: MediaRef[] = [];
  const seen = new Set<string>();
  const add = (raw: string) => {
    const p = cleanMediaPath(raw);
    const media = mediaKindForPath(p);
    if (media && !seen.has(p)) { seen.add(p); out.push({ media, kind: "path", path: p }); }
  };
  for (const item of arr) {
    const block = item?.type === "content" ? item.content : item;
    if (block?.type !== "text" || typeof block.text !== "string") continue;
    let parsed: any;
    try { parsed = JSON.parse(block.text); } catch { /* prose, not JSON */ }
    if (parsed && typeof parsed.path === "string") {
      add(parsed.path);                                   // machine-readable JSON form
    } else if (parsed === undefined) {
      for (const m of block.text.matchAll(MEDIA_PATH_IN_TEXT_RE)) add(m[0]); // prose form
    }
  }
  return out;
}

export function routeSessionUpdate(u: any): UpdateRoute | null {
  if (!u) return null;
  switch (u.sessionUpdate) {
    case "agent_message_chunk": {
      const c = u.content;
      if (c && c.type && c.type !== "text") {
        const media = extractImageContent(c);
        if (media) return { event: "mediaContent", media };
      }
      return { event: "messageChunk", text: c?.text ?? "" };
    }
    case "user_message_chunk":
      return { event: "userMessageChunk", text: u.content?.text ?? "" };
    case "agent_thought_chunk":
      return { event: "thoughtChunk", text: u.content?.text ?? "" };
    case "tool_call":
      return { event: "toolCall", payload: u };
    case "tool_call_update":
      return { event: "toolCallUpdate", payload: u };
    case "plan":
      return { event: "plan", payload: u };
    case "current_mode_update":
      return { event: "modeChanged", modeId: u.currentModeId };
    case "available_commands_update":
      return { event: "commandsUpdate", commands: u.availableCommands ?? [] };
    case "task_backgrounded":
      return { event: "taskBackgrounded", payload: u };
    case "task_completed":
      return { event: "taskCompleted", payload: u };
    default:
      return { event: "update", payload: u };
  }
}

export interface PromptResultMeta {
  totalTokens?: number;
  inputTokens?: number;
  outputTokens?: number;
  cachedReadTokens?: number;
  reasoningTokens?: number;
  modelId?: string;
}

export function extractPromptMeta(result: any): PromptResultMeta {
  const m = result?._meta ?? {};
  return {
    totalTokens: m.totalTokens,
    inputTokens: m.inputTokens,
    outputTokens: m.outputTokens,
    cachedReadTokens: m.cachedReadTokens,
    reasoningTokens: m.reasoningTokens,
    modelId: m.modelId,
  };
}

/**
 * Strip a turn's `totalTokens: 0` report — it is never a real measurement
 * (#39). grok reports 0 both for `/session-info` (context untouched — the 0
 * zeroed the donut) and for `/compact` (context SHRUNK, not emptied — 0 is
 * wrong there too; the "Compacted." bubble is the it-worked signal, and the
 * next turn reports the true post-compact size). `undefined` means "no
 * update": the donut keeps its last real value. Non-zero counts pass through.
 */
export function gateZeroTokenMeta(meta: PromptResultMeta): PromptResultMeta {
  if (meta.totalTokens !== 0) return meta;
  return { ...meta, totalTokens: undefined };
}

/**
 * Parse the context line out of `/session-info`'s reply text — grok 0.2.x
 * renders `**Context:** 16017 / 512000 tokens (3%)`. This is the ONLY place
 * the post-compact size exists before the next inference turn (the compact
 * turn's meta reports 0, and signals.json keeps the pre-compact count until a
 * later turn-end flush — research/signals-refresh-probe.cjs), so the host
 * runs a hidden /session-info right after /compact and feeds this to the
 * donut. Tolerant of bold markers, casing, and thousands separators; null
 * when the line is missing or the numbers don't parse (callers fall back
 * silently — the post-compact re-prime's signals.json read is the backup).
 */
export function parseSessionInfoContext(text: string): { used: number; window: number } | null {
  const m = /context:\*{0,2}\s*([\d][\d,]*)\s*\/\s*([\d][\d,]*)\s*tokens/i.exec(text ?? "");
  if (!m) return null;
  const num = (s: string) => Number(s.replace(/,/g, ""));
  const used = num(m[1]);
  const window = num(m[2]);
  if (!Number.isFinite(used) || used <= 0 || !Number.isFinite(window) || window <= 0) return null;
  return { used, window };
}

export function makePermissionResponse(id: number | string, optionId: string) {
  return {
    jsonrpc: "2.0",
    id,
    result: { outcome: { outcome: "selected", optionId } },
  };
}

export function makeExitPlanResponse(
  id: number | string,
  verdict: "approved" | "abandoned" | "rejected",
) {
  if (verdict === "approved") {
    return { jsonrpc: "2.0", id, result: { outcome: "approved" } };
  }
  // Reject and Abandon must be sent as JSON-RPC errors — the CLI treats any
  // successful result as approval regardless of the outcome value.
  const message = verdict === "rejected" ? "User rejected the plan" : "User abandoned the plan";
  return { jsonrpc: "2.0", id, error: { code: -32000, message } };
}

/**
 * Response to grok's `x.ai/ask_user_question` request (Rust struct
 * `AskUserQuestionExtResponse` — an internally-tagged enum on field `outcome`,
 * variants `accepted` | `chat_about_this` | `skip_interview` | `cancelled`).
 * The `accepted` variant carries `answers` (question text → chosen option label,
 * multi-select labels joined) and `annotations` (question text → { notes,
 * preview }). The old catch-all replied with a bare `{}`, which grok's
 * deserializer rejects with "missing field `outcome` at line 1 column 2" so the
 * tool reports failure (issue #12).
 */
export function makeQuestionResponse(
  id: number | string,
  answers: Record<string, string>,
  annotations: Record<string, { notes?: string; preview?: string }> = {},
) {
  return { jsonrpc: "2.0", id, result: { outcome: "accepted", answers, annotations } };
}

/** User dismissed the question without answering → grok's `cancelled` outcome. */
export function makeQuestionCancelledResponse(id: number | string) {
  return { jsonrpc: "2.0", id, result: { outcome: "cancelled" } };
}

export function makeAckResponse(id: number | string, result: any = {}) {
  return { jsonrpc: "2.0", id, result };
}

export function makeRequest(id: number, method: string, params: any) {
  return { jsonrpc: "2.0", id, method, params };
}

/** Classify a permission answer as allowed vs rejected from the chosen option's
 *  kind (`allow_once`/`allow_always` → allowed, `reject_*`/`deny_*` → rejected).
 *  Used to persist the answer so a resumed session can replay the collapsed card. */
export function permissionOutcomeFor(
  options: { optionId: string; kind: string }[] | undefined,
  optionId: string,
): "allowed" | "rejected" {
  const opt = (options ?? []).find((o) => o.optionId === optionId);
  return opt && /reject|deny/i.test(opt.kind) ? "rejected" : "allowed";
}

/** Compress a (possibly huge) background shell command into a one-line label for
 *  a notification — collapse whitespace and clip to a readable length. */
export function summarizeBackgroundCommand(cmd: string, max = 80): string {
  const flat = (cmd || "").replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  return flat.slice(0, max - 1).trimEnd() + "…";
}

/**
 * True when `session/set_model` was rejected because the target model belongs
 * to a different agent than the one this session is bound to. The CLI binds the
 * agent at spawn time and locks it after the first turn (including our hidden
 * primer), so the model can only be applied on a fresh session — `newSession`
 * sets it before the primer runs, while the agent is still rebindable. The host
 * uses this to fall back to a restart instead of surfacing the raw error.
 */
export function isIncompatibleAgentError(err: any): boolean {
  if (err?.data?.code === "MODEL_SWITCH_INCOMPATIBLE_AGENT") return true;
  // Fallback if a future CLI keeps the message but drops the structured code.
  return /requires agent .+ but the active agent/i.test(err?.message ?? "");
}

/**
 * Map a model id reported by grok onto the id present in `availableModels`.
 * grok's `session/set_model` (and, on some builds, session load) echoes a
 * **versioned** id — e.g. it resolves a request for `grok-build` to
 * `grok-build-0.1` — but the model *list* still uses the base `grok-build`.
 * Left unreconciled, `currentModelId` matches nothing, so the toolbar shows the
 * raw id instead of "Grok Build" and the context-window lookup falls back to the
 * default (200K instead of grok-build's 512K). Exact match wins; otherwise a
 * base-id prefix match (`grok-build-0.1` → `grok-build`); otherwise the input is
 * returned unchanged. The prefix match prefers the **longest** (most specific)
 * candidate, so a future `grok-build-mini-0.1` resolves to `grok-build-mini`, not
 * `grok-build`. Pure.
 */
export function resolveModelId(
  id: string | undefined,
  availableModels: { modelId: string }[] | undefined,
): string | undefined {
  if (!id || !availableModels?.length) return id;
  if (availableModels.some((m) => m.modelId === id)) return id;
  let best: string | undefined;
  for (const m of availableModels) {
    if (id.startsWith(m.modelId) || m.modelId.startsWith(id)) {
      if (!best || m.modelId.length > best.length) best = m.modelId;
    }
  }
  return best ?? id;
}

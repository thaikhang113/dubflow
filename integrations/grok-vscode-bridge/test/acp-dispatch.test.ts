import { describe, it, expect } from "vitest";
import {
  collectToolImages,
  extractGeneratedMediaPaths,
  extractImageContent,
  extractPromptMeta,
  gateZeroTokenMeta,
  isMediaGenToolCall,
  isIncompatibleAgentError,
  makeAckResponse,
  makeExitPlanResponse,
  makePermissionResponse,
  makeQuestionCancelledResponse,
  makeQuestionResponse,
  makeRequest,
  parseAcpLine,
  parseSessionInfoContext,
  permissionOutcomeFor,
  resolveModelId,
  routeSessionUpdate,
  summarizeBackgroundCommand,
} from "../src/acp-dispatch";

describe("parseAcpLine", () => {
  it("returns null for empty / whitespace", () => {
    expect(parseAcpLine("")).toBeNull();
    expect(parseAcpLine("   \n")).toBeNull();
  });

  it("flags non-JSON lines", () => {
    const r = parseAcpLine("not json {");
    expect(r?.kind).toBe("non-json");
  });

  it("recognizes a response (id + no method)", () => {
    const r = parseAcpLine(
      JSON.stringify({ jsonrpc: "2.0", id: 1, result: { ok: true } }),
    );
    expect(r).toEqual({ kind: "response", id: 1, result: { ok: true }, error: undefined });
  });

  it("recognizes an error response", () => {
    const r = parseAcpLine(
      JSON.stringify({ jsonrpc: "2.0", id: 2, error: { code: -32603, message: "oops" } }),
    );
    expect(r?.kind).toBe("response");
    if (r?.kind === "response") expect(r.error.code).toBe(-32603);
  });

  it("recognizes a session/update notification", () => {
    const r = parseAcpLine(
      JSON.stringify({
        jsonrpc: "2.0",
        method: "session/update",
        params: { update: { sessionUpdate: "agent_message_chunk", content: { text: "hi" } } },
      }),
    );
    expect(r?.kind).toBe("session-update");
    if (r?.kind === "session-update") expect(r.update.sessionUpdate).toBe("agent_message_chunk");
  });

  it("recognizes a server->client request (method present)", () => {
    const r = parseAcpLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 99,
        method: "fs/read_text_file",
        params: { path: "/a.ts" },
      }),
    );
    expect(r?.kind).toBe("server-request");
    if (r?.kind === "server-request") {
      expect(r.method).toBe("fs/read_text_file");
      expect(r.id).toBe(99);
    }
  });

  it("parses exit_plan_mode request and exposes planContent in params", () => {
    const r = parseAcpLine(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 4,
        method: "_x.ai/exit_plan_mode",
        params: {
          sessionId: "abc",
          toolCallId: "call-1",
          planContent: "# My Plan\nStep 1",
        },
      }),
    );
    expect(r?.kind).toBe("server-request");
    if (r?.kind === "server-request") {
      expect(r.method).toBe("_x.ai/exit_plan_mode");
      expect(r.params.planContent).toBe("# My Plan\nStep 1");
    }
  });
});

describe("routeSessionUpdate", () => {
  it("routes message chunk", () => {
    const r = routeSessionUpdate({ sessionUpdate: "agent_message_chunk", content: { text: "x" } });
    expect(r).toEqual({ event: "messageChunk", text: "x" });
  });

  it("routes user message chunk (replayed on session/load)", () => {
    const r = routeSessionUpdate({ sessionUpdate: "user_message_chunk", content: { text: "hello" } });
    expect(r).toEqual({ event: "userMessageChunk", text: "hello" });
  });

  it("routes thought chunk", () => {
    const r = routeSessionUpdate({ sessionUpdate: "agent_thought_chunk", content: { text: "y" } });
    expect(r).toEqual({ event: "thoughtChunk", text: "y" });
  });

  it("routes tool_call and tool_call_update", () => {
    expect(routeSessionUpdate({ sessionUpdate: "tool_call", toolCallId: "t1" })?.event).toBe("toolCall");
    expect(routeSessionUpdate({ sessionUpdate: "tool_call_update", toolCallId: "t1" })?.event).toBe("toolCallUpdate");
  });

  it("routes current_mode_update with id", () => {
    const r = routeSessionUpdate({ sessionUpdate: "current_mode_update", currentModeId: "plan" });
    expect(r).toEqual({ event: "modeChanged", modeId: "plan" });
  });

  it("routes available_commands_update", () => {
    const r = routeSessionUpdate({
      sessionUpdate: "available_commands_update",
      availableCommands: [{ name: "compact" }],
    });
    expect(r?.event).toBe("commandsUpdate");
    if (r?.event === "commandsUpdate") expect(r.commands).toHaveLength(1);
  });

  it("routes plan update and passes full payload", () => {
    const payload = { sessionUpdate: "plan", planContent: "Step 1\nStep 2", planFilePath: "/tmp/plan.md" };
    const r = routeSessionUpdate(payload);
    expect(r?.event).toBe("plan");
    if (r?.event === "plan") expect(r.payload).toBe(payload);
  });

  it("falls through to generic update for unknown tags", () => {
    const r = routeSessionUpdate({ sessionUpdate: "something_new", payload: 1 });
    expect(r?.event).toBe("update");
  });

  it("handles missing content.text gracefully", () => {
    const r = routeSessionUpdate({ sessionUpdate: "agent_message_chunk" });
    expect(r).toEqual({ event: "messageChunk", text: "" });
  });

  it("routes task_backgrounded / task_completed to their own events (not generic update)", () => {
    const bg = routeSessionUpdate({ sessionUpdate: "task_backgrounded", task_id: "t", command: "grok -p ..." });
    expect(bg?.event).toBe("taskBackgrounded");
    if (bg?.event === "taskBackgrounded") expect(bg.payload.command).toBe("grok -p ...");

    const done = routeSessionUpdate({ sessionUpdate: "task_completed", task_snapshot: { command: "x", exit_code: 0 } });
    expect(done?.event).toBe("taskCompleted");
    if (done?.event === "taskCompleted") expect(done.payload.task_snapshot.exit_code).toBe(0);
  });
});

describe("permissionOutcomeFor", () => {
  const opts = [
    { optionId: "a1", kind: "allow_once" },
    { optionId: "a2", kind: "allow_always" },
    { optionId: "r1", kind: "reject_once" },
    { optionId: "d1", kind: "deny" },
  ];
  it("maps allow_* to allowed", () => {
    expect(permissionOutcomeFor(opts, "a1")).toBe("allowed");
    expect(permissionOutcomeFor(opts, "a2")).toBe("allowed");
  });
  it("maps reject_*/deny to rejected", () => {
    expect(permissionOutcomeFor(opts, "r1")).toBe("rejected");
    expect(permissionOutcomeFor(opts, "d1")).toBe("rejected");
  });
  it("defaults to allowed for an unknown option / empty list", () => {
    expect(permissionOutcomeFor(opts, "nope")).toBe("allowed");
    expect(permissionOutcomeFor(undefined, "x")).toBe("allowed");
  });
});

describe("summarizeBackgroundCommand", () => {
  it("returns short commands unchanged", () => {
    expect(summarizeBackgroundCommand("ls -la")).toBe("ls -la");
  });

  it("collapses whitespace/newlines to a single line", () => {
    expect(summarizeBackgroundCommand("grok  -p\n  \"do thing\"")).toBe('grok -p "do thing"');
  });

  it("clips long commands with an ellipsis", () => {
    const out = summarizeBackgroundCommand("grok -p " + "x".repeat(200), 40);
    expect(out.length).toBe(40);
    expect(out.endsWith("…")).toBe(true);
  });

  it("handles empty/undefined input", () => {
    expect(summarizeBackgroundCommand("")).toBe("");
    expect(summarizeBackgroundCommand(undefined as unknown as string)).toBe("");
  });
});

describe("extractPromptMeta", () => {
  it("pulls all fields out of _meta", () => {
    const m = extractPromptMeta({
      stopReason: "end_turn",
      _meta: {
        totalTokens: 100,
        inputTokens: 80,
        outputTokens: 20,
        cachedReadTokens: 5,
        reasoningTokens: 3,
        modelId: "grok-4.3",
      },
    });
    expect(m).toEqual({
      totalTokens: 100,
      inputTokens: 80,
      outputTokens: 20,
      cachedReadTokens: 5,
      reasoningTokens: 3,
      modelId: "grok-4.3",
    });
  });

  it("returns all-undefined when _meta is missing", () => {
    const m = extractPromptMeta({});
    expect(m.totalTokens).toBeUndefined();
    expect(m.modelId).toBeUndefined();
  });
});

describe("gateZeroTokenMeta (#39)", () => {
  it("strips a totalTokens:0 report — /session-info and /compact both report 0 without the context being empty", () => {
    const gated = gateZeroTokenMeta({ totalTokens: 0, inputTokens: 80, modelId: "grok-build" });
    expect(gated?.totalTokens).toBeUndefined();
    // The rest of the meta survives untouched.
    expect(gated?.inputTokens).toBe(80);
    expect(gated?.modelId).toBe("grok-build");
  });

  it("passes real counts through unchanged", () => {
    const meta = { totalTokens: 44123, inputTokens: 80 };
    expect(gateZeroTokenMeta(meta)).toBe(meta);
  });

  it("passes absent totalTokens through unchanged", () => {
    const meta = { inputTokens: 80 };
    expect(gateZeroTokenMeta(meta)).toBe(meta);
  });
});

describe("parseSessionInfoContext (hidden post-/compact /session-info)", () => {
  // Verbatim reply captured over ACP from grok 0.2.x
  // (research/signals-refresh-probe.cjs).
  const REAL_REPLY =
    "**Title:** Context Size Probe With Seeded Reply Request\n\n" +
    "**Session ID:** 019f5266-f0e3-75f3-a99f-13d40fbd1b28\n\n" +
    "**Working directory:** C:\\Users\\Dell\\AppData\\Local\\Temp\\grok-signals-probe-dt7QZZ\n\n" +
    "**Model:** grok-build\n\n**Turn:** 1\n\n" +
    "**Context:** 16017 / 512000 tokens (3%)";

  it("parses the real grok reply shape", () => {
    expect(parseSessionInfoContext(REAL_REPLY)).toEqual({ used: 16017, window: 512000 });
  });

  it("tolerates unbolded / recased lines and thousands separators", () => {
    expect(parseSessionInfoContext("context: 16,017 / 512,000 tokens (3%)")).toEqual({ used: 16017, window: 512000 });
    expect(parseSessionInfoContext("CONTEXT:**1 / 200000 tokens")).toEqual({ used: 1, window: 200000 });
  });

  it("returns null when the line is missing or malformed", () => {
    expect(parseSessionInfoContext("")).toBeNull();
    expect(parseSessionInfoContext("**Model:** grok-build")).toBeNull();
    expect(parseSessionInfoContext("Context: lots / many tokens")).toBeNull();
  });

  it("rejects non-positive counts (0 is never a real measurement, #39)", () => {
    expect(parseSessionInfoContext("Context: 0 / 512000 tokens")).toBeNull();
    expect(parseSessionInfoContext("Context: 100 / 0 tokens")).toBeNull();
  });
});

describe("response builders", () => {
  it("makePermissionResponse uses ACP outcome shape", () => {
    const r = makePermissionResponse(7, "allow-once");
    expect(r).toEqual({
      jsonrpc: "2.0",
      id: 7,
      result: { outcome: { outcome: "selected", optionId: "allow-once" } },
    });
  });

  it("makeExitPlanResponse: approved sends result, rejected/abandoned send error", () => {
    expect(makeExitPlanResponse(9, "approved").result).toEqual({ outcome: "approved" });
    expect(makeExitPlanResponse(9, "rejected").error?.code).toBe(-32000);
    expect(makeExitPlanResponse(9, "rejected").result).toBeUndefined();
    expect(makeExitPlanResponse(9, "abandoned").error?.code).toBe(-32000);
    expect(makeExitPlanResponse(9, "abandoned").result).toBeUndefined();
  });

  it("makeExitPlanResponse wraps in jsonrpc 2.0 envelope", () => {
    const r = makeExitPlanResponse(42, "approved");
    expect(r.jsonrpc).toBe("2.0");
    expect(r.id).toBe(42);
  });

  it("makeAckResponse defaults to empty result", () => {
    expect(makeAckResponse(3)).toEqual({ jsonrpc: "2.0", id: 3, result: {} });
  });

  it("makeQuestionResponse carries the accepted outcome tag grok's deserializer needs (#12)", () => {
    // The old catch-all replied with {} → "missing field outcome". The accepted
    // variant is internally tagged on `outcome` and carries answers/annotations.
    const r = makeQuestionResponse(5, { "Pick one?": "Option A" });
    expect(r).toEqual({
      jsonrpc: "2.0",
      id: 5,
      result: { outcome: "accepted", answers: { "Pick one?": "Option A" }, annotations: {} },
    });
  });

  it("makeQuestionResponse passes annotations through when provided", () => {
    const r = makeQuestionResponse(6, { Q: "A" }, { Q: { notes: "n" } });
    expect(r.result.annotations).toEqual({ Q: { notes: "n" } });
  });

  it("makeQuestionCancelledResponse sends the cancelled outcome", () => {
    expect(makeQuestionCancelledResponse(8)).toEqual({
      jsonrpc: "2.0",
      id: 8,
      result: { outcome: "cancelled" },
    });
  });

  it("makeRequest wraps params with jsonrpc 2.0", () => {
    expect(makeRequest(1, "session/new", { cwd: "." })).toEqual({
      jsonrpc: "2.0",
      id: 1,
      method: "session/new",
      params: { cwd: "." },
    });
  });
});

describe("isIncompatibleAgentError", () => {
  // Verbatim error captured from grok 0.2.3 when switching to a composer model
  // mid-session (research/*.cjs probe). The model belongs to the `cursor` agent
  // but the session is bound to `grok-build-plan`.
  const real = {
    code: -32600,
    message:
      "Cannot switch to model 'grok-composer-2.5-fast': it requires agent 'cursor' but the active agent is 'grok-build-plan'. Start a new session to use this model.",
    data: {
      code: "MODEL_SWITCH_INCOMPATIBLE_AGENT",
      activeAgentType: "grok-build-plan",
      requiredAgentType: "cursor",
      modelId: "grok-composer-2.5-fast",
      suggestion: "start_new_session",
    },
  };

  it("detects the structured MODEL_SWITCH_INCOMPATIBLE_AGENT code", () => {
    expect(isIncompatibleAgentError(real)).toBe(true);
  });

  it("falls back to the message when the structured code is absent", () => {
    expect(isIncompatibleAgentError({ message: real.message })).toBe(true);
  });

  it("does not match unrelated errors", () => {
    expect(isIncompatibleAgentError({ code: -32000, message: "Grok process exited (code 1)" })).toBe(false);
    expect(isIncompatibleAgentError({ data: { code: "SOMETHING_ELSE" } })).toBe(false);
    expect(isIncompatibleAgentError(undefined)).toBe(false);
    expect(isIncompatibleAgentError(new Error("network timeout"))).toBe(false);
  });
});

describe("resolveModelId (grok's versioned set_model id vs availableModels)", () => {
  const models = [
    { modelId: "grok-composer-2.5-fast" },
    { modelId: "grok-build" },
  ];

  it("maps the versioned id grok echoes back onto the availableModels base id", () => {
    // set_model("grok-build") resolves to "grok-build-0.1", which isn't in the list.
    expect(resolveModelId("grok-build-0.1", models)).toBe("grok-build");
  });

  it("returns an exact match unchanged", () => {
    expect(resolveModelId("grok-build", models)).toBe("grok-build");
    expect(resolveModelId("grok-composer-2.5-fast", models)).toBe("grok-composer-2.5-fast");
  });

  it("returns the input when nothing matches", () => {
    expect(resolveModelId("some-other-model", models)).toBe("some-other-model");
  });

  it("prefers the most specific base id when models share a prefix", () => {
    const colliding = [{ modelId: "grok-build" }, { modelId: "grok-build-mini" }];
    expect(resolveModelId("grok-build-mini-0.1", colliding)).toBe("grok-build-mini");
    expect(resolveModelId("grok-build-0.1", colliding)).toBe("grok-build");
  });

  it("passes through when the id or list is empty", () => {
    expect(resolveModelId(undefined, models)).toBeUndefined();
    expect(resolveModelId("grok-build-0.1", [])).toBe("grok-build-0.1");
    expect(resolveModelId("grok-build-0.1", undefined)).toBe("grok-build-0.1");
  });
});

describe("extractImageContent (ACP-standard block fallback)", () => {
  it("pulls an inline base64 image block", () => {
    expect(extractImageContent({ type: "image", data: "AAAA", mimeType: "image/jpeg" }))
      .toEqual({ media: "image", kind: "data", mimeType: "image/jpeg", data: "AAAA" });
  });

  it("defaults the mime when an image block omits it", () => {
    expect(extractImageContent({ type: "image", data: "AAAA" }))
      .toEqual({ media: "image", kind: "data", mimeType: "image/png", data: "AAAA" });
  });

  it("pulls an embedded resource blob", () => {
    expect(extractImageContent({
      type: "resource",
      resource: { uri: "file:///x/out.png", mimeType: "image/png", blob: "ZZZZ" },
    })).toEqual({ media: "image", kind: "data", mimeType: "image/png", data: "ZZZZ" });
  });

  it("maps a file:// resource_link to a path", () => {
    expect(extractImageContent({
      type: "resource_link",
      uri: "file:///home/u/.grok/sessions/s/out.png",
    })).toEqual({ media: "image", kind: "path", path: "/home/u/.grok/sessions/s/out.png", mimeType: undefined });
  });

  it("maps a bare absolute path resource_link to a path", () => {
    expect(extractImageContent({ type: "resource_link", uri: "/tmp/out.webp" }))
      .toEqual({ media: "image", kind: "path", path: "/tmp/out.webp", mimeType: undefined });
  });

  it("maps a remote https image to a uri", () => {
    expect(extractImageContent({ type: "resource_link", uri: "https://x.ai/a.jpg" }))
      .toEqual({ media: "image", kind: "uri", uri: "https://x.ai/a.jpg", mimeType: undefined });
  });

  it("ignores text and non-image content", () => {
    expect(extractImageContent({ type: "text", text: "hi" })).toBeNull();
    expect(extractImageContent({ type: "resource_link", uri: "file:///x/notes.md" })).toBeNull();
    expect(extractImageContent(null)).toBeNull();
  });
});

describe("collectToolImages", () => {
  it("collects images from wrapped and bare content items", () => {
    const imgs = collectToolImages({
      content: [
        { type: "content", content: { type: "image", data: "AA", mimeType: "image/png" } },
        { type: "text", text: "done" },
        { type: "resource_link", uri: "/tmp/a.gif" },
      ],
    });
    expect(imgs).toHaveLength(2);
    expect(imgs[0]).toEqual({ media: "image", kind: "data", mimeType: "image/png", data: "AA" });
    expect(imgs[1]).toEqual({ media: "image", kind: "path", path: "/tmp/a.gif", mimeType: undefined });
  });

  it("returns [] when there is no content array", () => {
    expect(collectToolImages({})).toEqual([]);
    expect(collectToolImages({ content: "nope" })).toEqual([]);
  });
});

describe("routeSessionUpdate media chunks", () => {
  it("routes an agent_message_chunk image block to mediaContent", () => {
    const r = routeSessionUpdate({
      sessionUpdate: "agent_message_chunk",
      content: { type: "image", data: "AA", mimeType: "image/png" },
    });
    expect(r).toEqual({ event: "mediaContent", media: { media: "image", kind: "data", mimeType: "image/png", data: "AA" } });
  });

  it("still routes text chunks as messageChunk", () => {
    const r = routeSessionUpdate({
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text: "hello" },
    });
    expect(r).toEqual({ event: "messageChunk", text: "hello" });
  });
});

describe("media generation (grok's real /imagine + /imagine-video wire shapes)", () => {
  // Confirmed against grok 0.2.33 / native-Windows 0.2.x (research/image-generation.md).
  // Images come from `image_gen` (relabeled `imagine: <prompt>`, rawInput.variant
  // "ImageGen"); videos from `video_gen` (`imagine-video: <prompt>`, variant
  // "VideoGen") on native Windows — older/Linux builds surfaced video as
  // `image_to_video`/`image-to-video:`/"ImageToVideo". The completed update
  // reports the saved file two ways depending on build:
  //   - JSON (Linux/macOS): a `{"path":"…/images/1.jpg"}` text block.
  //   - Prose (native Windows): a sentence "Image generated and saved to
  //     \\?\C:\…\images\1.jpg." — no JSON, so the path is scanned out of the text.
  function completedWith(path: string) {
    return {
      sessionUpdate: "tool_call_update",
      toolCallId: "call-x",
      status: "completed",
      content: [{ type: "content", content: { type: "text", text: JSON.stringify({ path, filename: path.split("/").pop() }) } }],
    };
  }

  it("recognizes the image_gen tool call by title and variant", () => {
    expect(isMediaGenToolCall({ title: "image_gen", rawInput: { prompt: "a cube", aspect_ratio: "1:1" } })).toBe(true);
    expect(isMediaGenToolCall({ title: "imagine: a small red cube" })).toBe(true);
    expect(isMediaGenToolCall({ title: "imagine: x", rawInput: { variant: "ImageGen", prompt: "x" } })).toBe(true);
  });

  it("recognizes the image_edit tool call by title and variant (the /imagine reference-edit)", () => {
    // Confirmed live (grok 0.2.x, session 019ea92a): the initial tool_call is
    // titled `image_edit`, the in-progress update relabels to `imagine-edit: …`
    // with variant `ImageEdit`. Missing this is why the edited image was invisible.
    expect(isMediaGenToolCall({ title: "image_edit", rawInput: { prompt: "make him fly a rocket", image: "/s/2.jpg" } })).toBe(true);
    expect(isMediaGenToolCall({ title: "imagine-edit: transform the reference photo" })).toBe(true);
    expect(isMediaGenToolCall({ title: "imagine-edit: x", rawInput: { variant: "ImageEdit", prompt: "x" } })).toBe(true);
  });

  it("recognizes the image_to_video tool call by title and variant", () => {
    expect(isMediaGenToolCall({ title: "image_to_video", rawInput: { image: "/s/1.jpg", prompt: "rotate", duration: 6 } })).toBe(true);
    expect(isMediaGenToolCall({ title: "image-to-video: the red cube rotates" })).toBe(true);
    expect(isMediaGenToolCall({ title: "image-to-video: x", rawInput: { variant: "ImageToVideo" } })).toBe(true);
    expect(isMediaGenToolCall({ title: "reference-to-video: x", rawInput: { variant: "ReferenceToVideo" } })).toBe(true);
  });

  it("does not flag ordinary tools as media gen", () => {
    expect(isMediaGenToolCall({ title: "run_terminal_command", rawInput: { variant: "Bash" } })).toBe(false);
    expect(isMediaGenToolCall(null)).toBe(false);
  });

  it("extracts a saved image path as media:image", () => {
    expect(extractGeneratedMediaPaths(completedWith("/root/.grok/sessions/%2Ftmp/s/images/1.jpg"))).toEqual([
      { media: "image", kind: "path", path: "/root/.grok/sessions/%2Ftmp/s/images/1.jpg" },
    ]);
  });

  it("extracts a saved video path as media:video", () => {
    expect(extractGeneratedMediaPaths(completedWith("/root/.grok/sessions/%2Ftmp/s/videos/1.mp4"))).toEqual([
      { media: "video", kind: "path", path: "/root/.grok/sessions/%2Ftmp/s/videos/1.mp4" },
    ]);
  });

  it("extracts the live image_edit JSON result and strips the \\\\?\\ prefix", () => {
    // Verbatim from session 019ea92a (the Elon reference-edit, saved as 3.jpg):
    // an extended-length Windows path inside the machine-readable JSON result.
    const live = {
      content: [{ type: "content", content: { type: "text", text: JSON.stringify({
        path: "\\\\?\\C:\\Users\\Dell\\.grok\\sessions\\s\\images\\3.jpg",
        filename: "3.jpg",
        session_folder: "images",
        message: "Image edited and saved to \\\\?\\C:\\Users\\Dell\\.grok\\sessions\\s\\images\\3.jpg.",
      }) } }],
    };
    expect(extractGeneratedMediaPaths(live)).toEqual([
      { media: "image", kind: "path", path: "C:\\Users\\Dell\\.grok\\sessions\\s\\images\\3.jpg" },
    ]);
  });

  it("ignores tool-result JSON whose path is neither image nor video", () => {
    expect(extractGeneratedMediaPaths(completedWith("/tmp/out.txt"))).toEqual([]);
  });

  it("ignores non-JSON and pathless text results", () => {
    expect(extractGeneratedMediaPaths({ content: [{ type: "content", content: { type: "text", text: "done" } }] })).toEqual([]);
    expect(extractGeneratedMediaPaths({ content: [{ type: "content", content: { type: "text", text: '{"ok":true}' } }] })).toEqual([]);
  });

  it("resume: the collapsed video tool_call carries title + path together", () => {
    // On session/load grok replays media gen as ONE completed tool_call (title +
    // variant + path content together), so both detectors must fire on the one
    // payload. Confirmed via resume probe (image) — video is the same shape.
    const replayed = {
      sessionUpdate: "tool_call",
      toolCallId: "call-12ee",
      title: "image-to-video: the red cube slowly rotates",
      status: "completed",
      rawInput: { variant: "ImageToVideo", prompt: "rotate", image: "/s/images/1.jpg", duration: 6 },
      content: [{ type: "content", content: { type: "text", text: JSON.stringify({ path: "/root/.grok/sessions/s/videos/1.mp4", session_folder: "videos" }) } }],
    };
    expect(isMediaGenToolCall(replayed)).toBe(true);
    expect(extractGeneratedMediaPaths(replayed)).toEqual([
      { media: "video", kind: "path", path: "/root/.grok/sessions/s/videos/1.mp4" },
    ]);
  });

  // ── Native-Windows grok 0.2.x ────────────────────────────────────────────
  // Two genuine regressions caught by the live suite (research/image-generation.md):
  // (1) /imagine-video's tool is `video_gen`/`imagine-video:`/variant "VideoGen"
  //     (the Linux probe had suggested `image_to_video`) — if unmatched the id is
  //     never tracked and the result is dropped; (2) the completed result is PROSE
  //     ("Image generated and saved to \\?\C:\…\1.jpg."), not JSON, so JSON.parse
  //     threw and the path was lost. Strings below are verbatim wire captures.
  describe("native-Windows shapes", () => {
    function completedWithText(text: string) {
      return {
        sessionUpdate: "tool_call_update",
        toolCallId: "call-win",
        status: "completed",
        content: [{ type: "content", content: { type: "text", text } }],
      };
    }

    it("recognizes the native-Windows video tool (video_gen / imagine-video: / VideoGen)", () => {
      expect(isMediaGenToolCall({ title: "video_gen", rawInput: { prompt: "a cube", duration: 8 } })).toBe(true);
      expect(isMediaGenToolCall({ title: "imagine-video: a red cube slowly rotating" })).toBe(true);
      expect(isMediaGenToolCall({ title: "imagine-video: x", rawInput: { variant: "VideoGen", prompt: "x" } })).toBe(true);
    });

    it("recognizes the native-Windows image tool (image_gen / imagine: / ImageGen)", () => {
      expect(isMediaGenToolCall({ title: "image_gen", rawInput: { prompt: "a cube", aspect_ratio: "1:1" } })).toBe(true);
      expect(isMediaGenToolCall({ title: "imagine: a small red cube" })).toBe(true);
      expect(isMediaGenToolCall({ title: "imagine: x", rawInput: { variant: "ImageGen" } })).toBe(true);
    });

    it("extracts an image path from the prose result and strips the \\\\?\\ prefix", () => {
      const prose = String.raw`Image generated and saved to \\?\C:\Users\Dell\.grok\sessions\C%3A%5CUsers%5CDell%5CAppData%5CLocal%5CTemp%5Cgrok-winmedia-lOd7PM\019ea7f4-3495-77b1-84f5-177e4ff37e1c\images\1.jpg.`;
      expect(extractGeneratedMediaPaths(completedWithText(prose))).toEqual([
        { media: "image", kind: "path", path: String.raw`C:\Users\Dell\.grok\sessions\C%3A%5CUsers%5CDell%5CAppData%5CLocal%5CTemp%5Cgrok-winmedia-lOd7PM\019ea7f4-3495-77b1-84f5-177e4ff37e1c\images\1.jpg` },
      ]);
    });

    it("extracts a video path from the prose result and strips the \\\\?\\ prefix", () => {
      const prose = String.raw`Video generated and saved to \\?\C:\Users\Dell\.grok\sessions\C%3A%5CUsers%5CDell%5CAppData%5CLocal%5CTemp%5Cgrok-winvideo-MMJ6F4\019ea7f4-4310-7832-a0b3-dab499e569d2\videos\1.mp4.`;
      expect(extractGeneratedMediaPaths(completedWithText(prose))).toEqual([
        { media: "video", kind: "path", path: String.raw`C:\Users\Dell\.grok\sessions\C%3A%5CUsers%5CDell%5CAppData%5CLocal%5CTemp%5Cgrok-winvideo-MMJ6F4\019ea7f4-4310-7832-a0b3-dab499e569d2\videos\1.mp4` },
      ]);
    });

    it("does not swallow the sentence's trailing period into the path", () => {
      const prose = String.raw`Image generated and saved to \\?\C:\out\images\1.jpg.`;
      const [ref] = extractGeneratedMediaPaths(completedWithText(prose));
      expect(ref.kind === "path" && ref.path).toBe(String.raw`C:\out\images\1.jpg`);
    });

    it("ignores prose that mentions no media file", () => {
      expect(extractGeneratedMediaPaths(completedWithText("Image generation failed: quota exceeded."))).toEqual([]);
      expect(extractGeneratedMediaPaths(completedWithText(String.raw`Saved a log to \\?\C:\out\run.txt.`))).toEqual([]);
    });
  });
});

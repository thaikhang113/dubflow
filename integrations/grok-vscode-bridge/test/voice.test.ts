import { describe, it, expect } from "vitest";
import {
  STT_ENDPOINT,
  MAX_RECORDING_SECONDS,
  resolveVoiceKey,
  buildFfmpegArgs,
  buildListDevicesArgs,
  parseDshowAudioDevices,
  buildSttRequest,
  parseSttResponse,
  classifySttError,
  cleanTranscript,
  parseVoiceCommand,
  DEFAULT_SEND_PHRASE,
  buildSttStreamUrl,
  buildFfmpegStreamArgs,
  applySegment,
  joinSegments,
} from "../src/voice";

describe("resolveVoiceKey", () => {
  it("prefers the explicit setting over env vars", () => {
    expect(resolveVoiceKey({ setting: "  xai-setting  ", env: { XAI_API_KEY: "xai-env" } })).toBe("xai-setting");
  });

  it("falls back to GROK_VOICE_API_KEY before XAI_API_KEY", () => {
    expect(resolveVoiceKey({ env: { GROK_VOICE_API_KEY: "xai-voice", XAI_API_KEY: "xai-generic" } })).toBe("xai-voice");
  });

  it("uses XAI_API_KEY when no dedicated voice key is present", () => {
    expect(resolveVoiceKey({ env: { XAI_API_KEY: "xai-generic" } })).toBe("xai-generic");
  });

  it("trims surrounding whitespace from env values", () => {
    expect(resolveVoiceKey({ env: { XAI_API_KEY: "  xai-padded \n" } })).toBe("xai-padded");
  });

  it("returns undefined when nothing is configured", () => {
    expect(resolveVoiceKey({})).toBeUndefined();
    expect(resolveVoiceKey({ setting: "   ", env: { XAI_API_KEY: "  " } })).toBeUndefined();
  });
});

describe("buildFfmpegArgs", () => {
  it("uses dshow on Windows with the named device", () => {
    const args = buildFfmpegArgs("win32", { device: "Microphone (Realtek)", outputPath: "out.wav" });
    expect(args).toContain("dshow");
    expect(args).toContain("audio=Microphone (Realtek)");
    expect(args[args.length - 1]).toBe("out.wav");
  });

  it("uses avfoundation on macOS and normalizes the audio index to :N", () => {
    expect(buildFfmpegArgs("darwin", { device: "0", outputPath: "o.wav" })).toContain(":0");
    expect(buildFfmpegArgs("darwin", { device: ":1", outputPath: "o.wav" })).toContain(":1");
    expect(buildFfmpegArgs("darwin", { outputPath: "o.wav" })).toContain(":0"); // default
    expect(buildFfmpegArgs("darwin", { outputPath: "o.wav" })).toContain("avfoundation");
  });

  it("uses pulse on Linux with the default device", () => {
    const args = buildFfmpegArgs("linux", { outputPath: "o.wav" });
    expect(args).toContain("pulse");
    expect(args).toContain("default");
  });

  it("always records mono 16 kHz and overwrites the output", () => {
    const args = buildFfmpegArgs("linux", { outputPath: "o.wav" });
    expect(args).toContain("-y");
    expect(args.join(" ")).toContain("-ac 1");
    expect(args.join(" ")).toContain("-ar 16000");
  });

  it("caps the recording duration (default and override)", () => {
    expect(buildFfmpegArgs("linux", { outputPath: "o.wav" }).join(" ")).toContain(`-t ${MAX_RECORDING_SECONDS}`);
    expect(buildFfmpegArgs("linux", { outputPath: "o.wav", maxSeconds: 30 }).join(" ")).toContain("-t 30");
  });
});

describe("buildListDevicesArgs", () => {
  it("requests a dshow device listing", () => {
    expect(buildListDevicesArgs()).toEqual(["-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]);
  });
});

describe("parseDshowAudioDevices", () => {
  it("parses the newer '(audio)' suffix format and skips video + alternative names", () => {
    const stderr = [
      `[dshow @ 0x1] "Integrated Camera" (video)`,
      `[dshow @ 0x1]   Alternative name "@device_pnp_\\\\?\\usb#vid"`,
      `[dshow @ 0x1] "Microphone (Realtek Audio)" (audio)`,
      `[dshow @ 0x1]   Alternative name "@device_cm_{guid}\\wave_{guid}"`,
    ].join("\n");
    expect(parseDshowAudioDevices(stderr)).toEqual(["Microphone (Realtek Audio)"]);
  });

  it("parses the older section-header format", () => {
    const stderr = [
      `[dshow @ 0x1] DirectShow video devices`,
      `[dshow @ 0x1]  "Integrated Camera"`,
      `[dshow @ 0x1]     Alternative name "@device_pnp"`,
      `[dshow @ 0x1] DirectShow audio devices`,
      `[dshow @ 0x1]  "Microphone (Realtek Audio)"`,
      `[dshow @ 0x1]     Alternative name "@device_cm"`,
      `[dshow @ 0x1]  "Line In"`,
    ].join("\n");
    expect(parseDshowAudioDevices(stderr)).toEqual(["Microphone (Realtek Audio)", "Line In"]);
  });

  it("dedupes repeated device names and tolerates empty input", () => {
    const stderr = `"Mic" (audio)\n"Mic" (audio)`;
    expect(parseDshowAudioDevices(stderr)).toEqual(["Mic"]);
    expect(parseDshowAudioDevices("")).toEqual([]);
    expect(parseDshowAudioDevices(undefined as unknown as string)).toEqual([]);
  });
});

describe("buildSttRequest", () => {
  it("targets the STT endpoint with a Bearer header", () => {
    const { url, headers } = buildSttRequest({ key: "xai-abc" });
    expect(url).toBe(STT_ENDPOINT);
    expect(url).toBe("https://api.x.ai/v1/stt");
    expect(headers.Authorization).toBe("Bearer xai-abc");
  });
});

describe("parseSttResponse", () => {
  it("extracts text plus optional metadata", () => {
    const r = parseSttResponse({
      text: "The quick brown fox.",
      language: "English",
      duration: 3.33,
      words: [{ text: "The", start: 0.1, end: 0.18 }],
    });
    expect(r.text).toBe("The quick brown fox.");
    expect(r.language).toBe("English");
    expect(r.duration).toBe(3.33);
    expect(r.words).toHaveLength(1);
  });

  it("returns text with metadata omitted when absent", () => {
    expect(parseSttResponse({ text: "hi" })).toEqual({ text: "hi", language: undefined, duration: undefined, words: undefined });
  });

  it("throws when the response has no text field", () => {
    expect(() => parseSttResponse({})).toThrow(/no 'text'/);
    expect(() => parseSttResponse(null)).toThrow();
    expect(() => parseSttResponse({ text: 42 })).toThrow();
  });
});

describe("classifySttError", () => {
  it("maps auth failures to a key-related message", () => {
    expect(classifySttError(401)).toMatch(/key/i);
    expect(classifySttError(403)).toMatch(/key/i);
  });

  it("maps common HTTP failures to distinct messages", () => {
    expect(classifySttError(429)).toMatch(/rate-limited/i);
    expect(classifySttError(413)).toMatch(/too large/i);
    expect(classifySttError(400)).toMatch(/rejected the audio/i);
    expect(classifySttError(500)).toMatch(/errored/i);
  });

  it("includes a body snippet for unrecognized statuses", () => {
    const msg = classifySttError(418, "I am a teapot");
    expect(msg).toMatch(/418/);
    expect(msg).toMatch(/teapot/);
  });
});

describe("cleanTranscript", () => {
  it("collapses whitespace and trims", () => {
    expect(cleanTranscript("  hello   world \n")).toBe("hello world");
    expect(cleanTranscript("")).toBe("");
    expect(cleanTranscript(undefined as unknown as string)).toBe("");
  });
});

describe("parseVoiceCommand", () => {
  it("default phrase is 'grok send'", () => {
    expect(DEFAULT_SEND_PHRASE).toBe("grok send");
  });

  it("strips a trailing 'grok send' and flags send", () => {
    expect(parseVoiceCommand("fix the bug grok send")).toEqual({ text: "fix the bug", send: true });
  });

  it("is case-insensitive and tolerates a comma between words", () => {
    expect(parseVoiceCommand("Fix the bug, Grok send")).toEqual({ text: "Fix the bug", send: true });
  });

  it("keeps trailing punctuation on the message (strips only the command)", () => {
    expect(parseVoiceCommand("what's the weather today grok send?")).toEqual({
      text: "what's the weather today?",
      send: true,
    });
    expect(parseVoiceCommand("fix the bug grok send.")).toEqual({ text: "fix the bug.", send: true });
    expect(parseVoiceCommand("refactor this Grok Send!")).toEqual({ text: "refactor this!", send: true });
    expect(parseVoiceCommand("Fix the bug, Grok send.")).toEqual({ text: "Fix the bug.", send: true });
  });

  it("does not double the trailing mark — keeps the message's own, drops the command's", () => {
    // Real-world reports: "…mate.." and "…not sure.?"
    expect(parseVoiceCommand("Wow, thanks! I love you, mate. grok send.")).toEqual({
      text: "Wow, thanks! I love you, mate.",
      send: true,
    });
    expect(parseVoiceCommand("Wow, thanks! I love you, mate. grok sent.")).toEqual({
      text: "Wow, thanks! I love you, mate.",
      send: true,
    });
    expect(parseVoiceCommand("What is this solution about? I'm not sure. grok send?")).toEqual({
      text: "What is this solution about? I'm not sure.",
      send: true,
    });
    // every doubled combo the user listed collapses to the message's own mark
    expect(parseVoiceCommand("really? grok send.")).toEqual({ text: "really?", send: true });
    expect(parseVoiceCommand("done! grok send?")).toEqual({ text: "done!", send: true });
    expect(parseVoiceCommand("wait. grok send.")).toEqual({ text: "wait.", send: true });
  });

  it("treats a bare 'grok send' as send with empty text", () => {
    expect(parseVoiceCommand("grok send")).toEqual({ text: "", send: true });
  });

  it("tolerates the 'send' → 'sent' STT confusion", () => {
    expect(parseVoiceCommand("fix the bug grok sent")).toEqual({ text: "fix the bug", send: true });
    expect(parseVoiceCommand("Refactor this, Grok Sent.")).toEqual({ text: "Refactor this.", send: true });
  });

  it("the 'sent' tolerance ONLY applies after 'grok' — never on a bare 'sent'", () => {
    expect(parseVoiceCommand("the email was sent")).toEqual({ text: "the email was sent", send: false });
    expect(parseVoiceCommand("tell grok the report was already sent")).toEqual({
      text: "tell grok the report was already sent",
      send: false,
    });
    expect(parseVoiceCommand("make sure it gets sent")).toEqual({ text: "make sure it gets sent", send: false });
  });

  it("does NOT fire on a message that merely ends in 'send'", () => {
    expect(parseVoiceCommand("please tell grok to send the email")).toEqual({
      text: "please tell grok to send the email",
      send: false,
    });
    expect(parseVoiceCommand("press send")).toEqual({ text: "press send", send: false });
  });

  it("only matches the phrase at the end, not mid-sentence", () => {
    expect(parseVoiceCommand("grok send me the file and fix it")).toEqual({
      text: "grok send me the file and fix it",
      send: false,
    });
  });

  it("supports a custom phrase", () => {
    expect(parseVoiceCommand("do it now go", "go")).toEqual({ text: "do it now", send: true });
    expect(parseVoiceCommand("do it now go", "grok send")).toEqual({ text: "do it now go", send: false });
  });

  it("an empty phrase disables detection", () => {
    expect(parseVoiceCommand("fix the bug grok send", "")).toEqual({ text: "fix the bug grok send", send: false });
  });
});

describe("buildSttStreamUrl", () => {
  it("defaults to 16k pcm with interim results on the wss endpoint", () => {
    const url = buildSttStreamUrl();
    expect(url.startsWith("wss://api.x.ai/v1/stt?")).toBe(true);
    expect(url).toContain("sample_rate=16000");
    expect(url).toContain("encoding=pcm");
    expect(url).toContain("interim_results=true");
  });

  it("appends each keyterm (repeatable) for biasing", () => {
    const url = buildSttStreamUrl({ keyterms: ["grok send", "Grok"] });
    // URLSearchParams encodes spaces as '+'
    expect(url).toContain("keyterm=grok+send");
    expect(url).toContain("keyterm=Grok");
    expect((url.match(/keyterm=/g) || []).length).toBe(2);
  });

  it("skips blank keyterms and clamps to 50 chars", () => {
    const long = "a".repeat(80);
    const url = buildSttStreamUrl({ keyterms: ["", "  ", long] });
    expect((url.match(/keyterm=/g) || []).length).toBe(1);
    expect(url).toContain("keyterm=" + "a".repeat(50));
  });

  it("can turn interim results off", () => {
    expect(buildSttStreamUrl({ interimResults: false })).toContain("interim_results=false");
  });
});

describe("buildFfmpegStreamArgs", () => {
  it("outputs raw s16le 16k mono to stdout (pipe:1)", () => {
    const args = buildFfmpegStreamArgs("linux", {});
    expect(args.join(" ")).toContain("-f s16le");
    expect(args[args.length - 1]).toBe("pipe:1");
    expect(args.join(" ")).toContain("-ac 1");
    expect(args.join(" ")).toContain("-ar 16000");
    expect(args).not.toContain("-y"); // no file output
  });

  it("uses the right per-platform capture backend", () => {
    expect(buildFfmpegStreamArgs("win32", { device: "Mic" }).join(" ")).toContain("dshow");
    expect(buildFfmpegStreamArgs("darwin", {}).join(" ")).toContain("avfoundation");
    expect(buildFfmpegStreamArgs("linux", {}).join(" ")).toContain("pulse");
  });
});

describe("applySegment / joinSegments (streaming transcript accumulation)", () => {
  it("keeps the latest text per start key (re-emitted finals supersede)", () => {
    let segs: ReturnType<typeof applySegment> = [];
    segs = applySegment(segs, { start: 0, text: "Add a button" });
    segs = applySegment(segs, { start: 0, text: "Add a logout button to the navbar" });
    expect(joinSegments(segs)).toBe("Add a logout button to the navbar");
  });

  it("orders multiple turns by start time", () => {
    let segs: ReturnType<typeof applySegment> = [];
    segs = applySegment(segs, { start: 3.4, text: "second part" });
    segs = applySegment(segs, { start: 0, text: "first part" });
    expect(joinSegments(segs)).toBe("first part second part");
  });

  it("ignores events without a numeric start or string text", () => {
    let segs: ReturnType<typeof applySegment> = [{ start: 0, text: "keep" }];
    segs = applySegment(segs, { text: "no start" });
    segs = applySegment(segs, { start: 1 });
    expect(joinSegments(segs)).toBe("keep");
  });

  it("collapses whitespace when joining", () => {
    expect(joinSegments([{ start: 0, text: "  a  " }, { start: 1, text: " b " }])).toBe("a b");
    expect(joinSegments([])).toBe("");
  });
});

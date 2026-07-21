// DOM-level tests for the two v1.4.0 webview render paths that the pure-helper
// suites can't reach: generated-media inlining (addGeneratedMedia) and the
// subagent card (addSubagentCard). These drive the REAL media/chat.js so the
// host→webview contract for `{type:"media"}` and a subagent `{type:"toolCall"}`
// is exercised end-to-end, not just the classifiers in webview-helpers.
//
//   1. /imagine  -> {media:"image", src:<data: URI>, path} renders a clickable <img>
//   2. /imagine-video -> {media:"video", src:<data: URI>} renders <video controls>
//   3. remote link (no src, just url) renders an "open ↗" button, not an <img>
//   4. a spawn_subagent tool call renders a "Subagent: <type>" card and is
//      diverted away from the generic tool group
import { describe, it, expect } from "vitest";
import { bootWebview, dispatch, click } from "./webview-harness";

const messages = (doc: Document) => doc.getElementById("messages") as HTMLElement;

const IMG_DATA = "data:image/jpeg;base64,/9j/AAAQSkZJRg==";
const VIDEO_DATA = "data:video/mp4;base64,AAAAIGZ0eXBpc29t";

describe("addGeneratedMedia (/imagine image)", () => {
  it("inlines a generated image as a clickable <img> with the data: src", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, {
      type: "media",
      media: "image",
      src: IMG_DATA,
      path: "/sessions/abc/images/cat.jpg",
    });

    const wrap = messages(doc).querySelector(".generated-image");
    expect(wrap).not.toBeNull();
    expect(wrap!.classList.contains("generated-video")).toBe(false);

    const img = wrap!.querySelector("img") as HTMLImageElement;
    expect(img).not.toBeNull();
    expect(img.getAttribute("src")).toBe(IMG_DATA);

    // clicking the inlined image opens its source file in VS Code
    click(window, img);
    expect(posted).toContainEqual({ type: "openFile", path: "/sessions/abc/images/cat.jpg" });
  });
});

describe("addGeneratedMedia (/imagine-video video)", () => {
  it("inlines a generated video as <video controls>, not an <img>", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "media",
      media: "video",
      src: VIDEO_DATA,
      path: "/sessions/abc/videos/clip.mp4",
    });

    const wrap = messages(doc).querySelector(".generated-image.generated-video");
    expect(wrap).not.toBeNull();

    const video = wrap!.querySelector("video") as HTMLVideoElement;
    expect(video).not.toBeNull();
    expect(video.getAttribute("src")).toBe(VIDEO_DATA);
    expect(video.controls).toBe(true);
    // a video must NOT also render an <img>
    expect(wrap!.querySelector("img")).toBeNull();
  });
});

describe("addGeneratedMedia hover actions (copy path / open in VS Code)", () => {
  const btnByTitle = (wrap: Element, title: string) =>
    [...wrap.querySelectorAll(".generated-media-btn")].find(
      (b) => b.getAttribute("title") === title,
    ) as HTMLButtonElement | undefined;

  it("an image exposes copy-path + open icons; the open icon posts openFile", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "media", media: "image", src: IMG_DATA, path: "/sessions/abc/images/cat.jpg" });
    const wrap = messages(doc).querySelector(".generated-image")!;

    expect(btnByTitle(wrap, "Copy path")).toBeTruthy();
    const openBtn = btnByTitle(wrap, "Open in VS Code")!;
    expect(openBtn).toBeTruthy();

    click(window, openBtn);
    expect(posted).toContainEqual({ type: "openFile", path: "/sessions/abc/images/cat.jpg" });
  });

  it("a video — which has no click-to-open — still exposes the open icon", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "media", media: "video", src: VIDEO_DATA, path: "/sessions/abc/videos/clip.mp4" });
    const wrap = messages(doc).querySelector(".generated-image.generated-video")!;

    const openBtn = btnByTitle(wrap, "Open in VS Code")!;
    expect(openBtn).toBeTruthy();
    click(window, openBtn);
    expect(posted).toContainEqual({ type: "openFile", path: "/sessions/abc/videos/clip.mp4" });
  });

  it("copy-path writes the on-disk path to the clipboard", () => {
    const { window, doc } = bootWebview();
    let copied = "";
    Object.defineProperty((window as any).navigator, "clipboard", {
      value: { writeText: (t: string) => { copied = t; return Promise.resolve(); } },
      configurable: true,
    });
    dispatch(window, { type: "media", media: "image", src: IMG_DATA, path: "/sessions/abc/images/cat.jpg" });
    const wrap = messages(doc).querySelector(".generated-image")!;

    click(window, btnByTitle(wrap, "Copy path")!);
    expect(copied).toBe("/sessions/abc/images/cat.jpg");
  });

  it("the remote-link fallback (no on-disk path) has no hover actions", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "media", media: "image", url: "https://x.ai/generated/cat.jpg" });
    const wrap = messages(doc).querySelector(".generated-image")!;
    expect(wrap.querySelector(".generated-media-actions")).toBeNull();
  });
});

describe("addGeneratedMedia (remote link fallback)", () => {
  it("renders an open-link button (not an <img>) when only a url is supplied", () => {
    const { window, posted, doc } = bootWebview();
    dispatch(window, { type: "media", media: "image", url: "https://x.ai/generated/cat.jpg" });

    const wrap = messages(doc).querySelector(".generated-image")!;
    expect(wrap.querySelector("img")).toBeNull();
    const link = wrap.querySelector(".preview-link") as HTMLButtonElement;
    expect(link).not.toBeNull();

    click(window, link);
    expect(posted).toContainEqual({ type: "openUrl", url: "https://x.ai/generated/cat.jpg" });
  });
});

describe("subagent row (spawn_subagent tool call, grok 0.2.93 wire shape)", () => {
  // Real spawn shape captured over ACP (research/signals-refresh-probe run +
  // research/subagents.md): rawInput carries the task description + type.
  const SPAWN = {
    toolCallId: "sa-1",
    title: "spawn_subagent",
    rawInput: {
      prompt: "Read the file math.js and report back in one sentence",
      description: "Read math.js and summarize add() in one sentence",
      subagent_type: "general-purpose",
      background: false,
    },
  };
  // Real completed update: re-titled to the description, structured rawOutput.
  const COMPLETED = {
    toolCallId: "sa-1",
    status: "completed",
    title: "Read math.js and summarize add() in one sentence",
    content: [{ type: "content", content: { type: "text", text: "The add() function returns the sum.\n\n<subagent_meta>id=x, type=general-purpose</subagent_meta>" } }],
    rawOutput: {
      type: "SubagentCompleted",
      output: "The add() function returns the sum.",
      subagent_type: "general-purpose",
      tool_calls: 2,
      turns: 1,
      duration_ms: 7343,
    },
  };

  it("renders the task description with running dots, diverted from the tool group", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "toolCall", call: SPAWN });

    const card = messages(doc).querySelector(".subagent-card")!;
    expect(card).not.toBeNull();
    expect(card.textContent).toContain("Subagent");
    expect(card.textContent).toContain("Read math.js and summarize add() in one sentence");
    expect(card.querySelector(".blink-dots")).not.toBeNull();
    expect(messages(doc).querySelector(".tool-group")).toBeNull();
  });

  it("the completed update stops the dots, stamps the duration, and offers the result on click", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "toolCall", call: SPAWN });
    dispatch(window, { type: "toolCallUpdate", call: COMPLETED });

    const card = messages(doc).querySelector(".subagent-card")!;
    expect(card.classList.contains("subagent-done")).toBe(true);
    expect(card.querySelector(".blink-dots")).toBeNull();
    expect(card.querySelector(".subagent-time")!.textContent).toBe("· 7s");
    // the update must NOT leak into the generic tool group
    expect(messages(doc).querySelector(".tool-group")).toBeNull();

    const body = card.querySelector(".subagent-result") as HTMLElement;
    expect(body.hidden).toBe(true);
    // Rendered as markdown; the <subagent_meta> plumbing is stripped.
    expect(body.textContent).toContain("The add() function returns the sum.");
    expect(body.textContent).not.toContain("subagent_meta");
    click(window, card.querySelector(".subagent-row")!);
    expect(body.hidden).toBe(false);
  });

  it("a generic 'Subagent' title is noise — the first prompt line stands in", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "toolCall",
      call: {
        toolCallId: "sa-3",
        title: "Subagent",
        rawInput: { subagent_type: "general-purpose", prompt: "List the repo root and count .ts files under src/\nThen report back." },
      },
    });
    const card = messages(doc).querySelector(".subagent-card")!;
    expect(card.textContent).toContain("List the repo root and count .ts files under src/");
    // no "Subagent · Subagent" duplication
    expect(card.querySelector(".subagent-title")!.textContent).not.toBe("Subagent");
  });

  it("a replayed one-shot tool_call that is already completed renders done immediately", () => {
    const { window, doc } = bootWebview();
    dispatch(window, { type: "toolCall", call: { ...SPAWN, ...COMPLETED } });

    const card = messages(doc).querySelector(".subagent-card")!;
    expect(card.classList.contains("subagent-done")).toBe(true);
    expect(card.querySelector(".blink-dots")).toBeNull();
    expect(card.querySelector(".subagent-result")!.textContent).toContain("returns the sum");
  });

  it("falls back to the prompt's first line, then the subagent type", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "toolCall",
      call: {
        toolCallId: "sa-2",
        title: "spawn_subagent",
        rawInput: { subagent_type: "general-purpose", prompt: "investigate the parser" },
      },
    });
    expect(messages(doc).querySelector(".subagent-card")!.textContent).toContain("investigate the parser");

    // Neither description nor prompt → the type is the last resort.
    dispatch(window, {
      type: "toolCall",
      call: { toolCallId: "sa-2b", title: "spawn_subagent", rawInput: { subagent_type: "general-purpose" } },
    });
    const cards = messages(doc).querySelectorAll(".subagent-card");
    expect(cards[cards.length - 1].textContent).toContain("general-purpose");
  });

  it("still cards grok's legacy background-task delegation, labeled by its command", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "toolCall",
      call: {
        toolCallId: "bg-1",
        title: "run_terminal_command",
        rawInput: { variant: "Bash", command: "investigate the parser", is_background: true },
      },
    });

    const card = messages(doc).querySelector(".subagent-card")!;
    expect(card.textContent).toContain("Subagent");
    expect(card.textContent).toContain("investigate the parser");
    expect(messages(doc).querySelector(".tool-group")).toBeNull();
  });

  it("an ordinary (foreground) tool call still goes to the tool group, not a subagent card", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "toolCall",
      call: { toolCallId: "t-1", title: "read_file", kind: "read", rawInput: { path: "a.ts" } },
    });

    expect(messages(doc).querySelector(".tool-group")).not.toBeNull();
    expect(messages(doc).querySelector(".subagent-card")).toBeNull();
  });
});

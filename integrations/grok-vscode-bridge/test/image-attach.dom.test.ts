// DOM tests for the image-attach webview surfaces: the composer paste handler
// (raster-only collection, mixed-clipboard text preservation, the pendingPaste
// send hold), the send payload (host-owned chips — no chips echo), and the
// session-restore rebuild of [Image #N] tags into chips via parseImageTags.
import { describe, it, expect, vi } from "vitest";
import { bootWebview, dispatch, click } from "./webview-harness";

function pasteEvent(window: any, items: Array<{ kind: string; type: string; file?: any }>, text = "") {
  const e = new window.Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(e, "clipboardData", {
    value: {
      items: items.map((it) => ({
        kind: it.kind,
        type: it.type,
        getAsFile: () => it.file ?? null,
      })),
      getData: (kind: string) => (kind === "text/plain" ? text : ""),
    },
  });
  return e;
}

function pngFile(window: any): any {
  // A tiny stand-in blob — the handler only base64s it, never decodes pixels.
  return new window.File([new Uint8Array([137, 80, 78, 71])], "clip.png", { type: "image/png" });
}

describe("composer paste handler", () => {
  it("posts pasteImage for a clipboard image and suppresses the default paste", async () => {
    const { window, doc, posted } = bootWebview();
    const input = doc.getElementById("input")!;
    const e = pasteEvent(window, [{ kind: "file", type: "image/png", file: pngFile(window) }]);
    input.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(true);
    await vi.waitFor(() => {
      expect(posted.some((m) => m.type === "pasteImage")).toBe(true);
    });
    const msg = posted.find((m) => m.type === "pasteImage")!;
    expect(msg.mimeType).toBe("image/png");
    expect(typeof msg.data).toBe("string");
    expect((msg.data as string).length).toBeGreaterThan(0);
  });

  it("leaves a text-only paste to the default handler", () => {
    const { window, doc, posted } = bootWebview();
    const input = doc.getElementById("input")!;
    const e = pasteEvent(window, [{ kind: "string", type: "text/plain" }], "hello");
    input.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(false);
    expect(posted.filter((m) => m.type === "pasteImage")).toHaveLength(0);
  });

  it("does not hijack a non-raster image item (svg markup copy)", () => {
    const { window, doc, posted } = bootWebview();
    const input = doc.getElementById("input")!;
    const e = pasteEvent(window, [{ kind: "string", type: "image/svg+xml" }], "<svg/>");
    input.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(false);
    expect(posted.filter((m) => m.type === "pasteImage")).toHaveLength(0);
  });

  it("keeps the text half of a mixed clipboard and posts every image", async () => {
    const { window, doc, posted } = bootWebview();
    const input = doc.getElementById("input") as HTMLTextAreaElement;
    const e = pasteEvent(
      window,
      [
        { kind: "string", type: "text/plain" },
        { kind: "file", type: "image/png", file: pngFile(window) },
        { kind: "file", type: "image/jpeg", file: pngFile(window) },
      ],
      "caption text",
    );
    input.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(true);
    expect(input.value).toContain("caption text");
    await vi.waitFor(() => {
      expect(posted.filter((m) => m.type === "pasteImage")).toHaveLength(2);
    });
  });

  it("holds send while a pasted image is still being read", async () => {
    const { window, doc, posted } = bootWebview();
    const input = doc.getElementById("input") as HTMLTextAreaElement;
    const sendBtn = doc.getElementById("send-btn")!;
    input.value = "look at this";
    input.dispatchEvent(pasteEvent(window, [{ kind: "file", type: "image/png", file: pngFile(window) }]));
    // FileReader is in flight — the send must be refused so the pasteImage
    // post can't land AFTER the send and ride the next message.
    click(window, sendBtn);
    expect(posted.filter((m) => m.type === "send")).toHaveLength(0);
    await vi.waitFor(() => {
      expect(posted.some((m) => m.type === "pasteImage")).toBe(true);
    });
    click(window, sendBtn);
    expect(posted.filter((m) => m.type === "send")).toHaveLength(1);
  });

  it("send carries only the text — chips are host-owned state", () => {
    const { window, doc, posted } = bootWebview();
    const input = doc.getElementById("input") as HTMLTextAreaElement;
    input.value = "hi";
    click(window, doc.getElementById("send-btn")!);
    const send = posted.find((m) => m.type === "send")!;
    expect(send.text).toBe("hi");
    expect("chips" in send).toBe(false);
  });
});

describe("restored [Image #N] rendering", () => {
  function replayUserMessage(window: any, text: string) {
    dispatch(window, { type: "historyReplay", active: true });
    dispatch(window, { type: "userMessageChunk", text });
    dispatch(window, { type: "historyReplay", active: false });
  }

  it("rebuilds trailing tags as image chips with the origin path on the tooltip", () => {
    const { window, doc } = bootWebview();
    replayUserMessage(window, "compress this\n\n[Image #2] (assets/hero.png)");
    const bubble = doc.querySelector(".msg.user")!;
    expect(bubble.textContent).toContain("compress this");
    expect(bubble.textContent).not.toContain("[Image #2]");
    const chip = bubble.querySelector(".msg-chip")!;
    expect(chip.textContent).toContain("Image #2");
    expect(chip.getAttribute("title")).toBe("assets/hero.png");
  });

  it("leaves a literal [Image #N] in the middle of the user's words alone", () => {
    const { window, doc } = bootWebview();
    replayUserMessage(window, "the TUI prints [Image #1] before the text — why?");
    const bubble = doc.querySelector(".msg.user")!;
    expect(bubble.textContent).toContain("[Image #1]");
    expect(bubble.querySelector(".msg-chip")).toBeNull();
  });

  it("still strips the legacy leading-tag wire shape", () => {
    const { window, doc } = bootWebview();
    replayUserMessage(window, "[Image #1] what is this?");
    const bubble = doc.querySelector(".msg.user")!;
    expect(bubble.textContent).toContain("what is this?");
    expect(bubble.textContent).not.toContain("[Image #1]");
    expect(bubble.querySelector(".msg-chip")!.textContent).toContain("Image #1");
  });
});

describe("image chips in the composer", () => {
  it("renders an image chip as a remove-only attachment row with the origin tooltip", () => {
    const { window, doc } = bootWebview();
    dispatch(window, {
      type: "chips",
      chips: [{
        id: "image:/staging/a.png:1:7",
        path: "/staging/a.png",
        relPath: "Image #1",
        hidden: false,
        imageIndex: 1,
        mimeType: "image/png",
        originRelPath: "assets/a.png",
      }],
    });
    const row = doc.querySelector(".attachment")!;
    expect(row).not.toBeNull();
    expect(row.getAttribute("title")).toBe("assets/a.png");
    expect(row.querySelector(".attachment-remove")).not.toBeNull();
  });
});

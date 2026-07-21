import { describe, it, expect } from "vitest";
import { buildPrompt, buildPromptWithImages, CONTEXT_TAG_OPEN, CONTEXT_TAG_CLOSE } from "../src/prompt-builder";
import { makeImplicitChip, makeExplicitChip, makeImageChip } from "../src/chips";

const deps = {
  readFile: (p: string) => {
    if (p === "/a.ts") return "line1\nline2\nline3\nline4\nline5";
    if (p === "/b.ts") return "X\nY";
    throw new Error("ENOENT " + p);
  },
  extName: (p: string) => {
    const i = p.lastIndexOf(".");
    return i >= 0 ? p.slice(i) : "";
  },
};

// The file-path context is wrapped in the <vscode-context> envelope.
const ctx = (inner: string) => `${CONTEXT_TAG_OPEN}\n${inner}\n${CONTEXT_TAG_CLOSE}`;

describe("buildPrompt", () => {
  it("returns just the text when no chips", () => {
    expect(buildPrompt("hello", [], deps)).toBe("hello");
  });

  it("wraps an explicitly attached file in the context envelope", () => {
    const out = buildPrompt("explain this", [makeExplicitChip("/a.ts", "src/a.ts")], deps);
    expect(out).toBe(ctx("Attached file: src/a.ts") + "\n\nexplain this");
  });

  it("lists multiple attached files under 'Attached files:'", () => {
    const a = makeExplicitChip("/a.ts", "src/a.ts");
    const b = makeExplicitChip("/pic.png", "/Users/me/Downloads/pic.png");
    const out = buildPrompt("animate it", [a, b], deps);
    expect(out).toBe(
      ctx("Attached files:\n- src/a.ts\n- /Users/me/Downloads/pic.png") + "\n\nanimate it",
    );
  });

  it("lists the active-editor file separately as ambient 'Currently open' context", () => {
    const out = buildPrompt("explain this", [makeImplicitChip("/a.ts", "src/a.ts")], deps);
    expect(out).toBe(ctx("Currently open in the editor (for context): src/a.ts") + "\n\nexplain this");
  });

  it("lists multiple open-editor files under the 'Currently open' header", () => {
    const a = makeImplicitChip("/a.ts", "src/a.ts");
    const b = makeImplicitChip("/b.ts", "src/b.ts");
    const out = buildPrompt("q", [a, b], deps);
    expect(out).toBe(
      ctx("Currently open in the editor (for context):\n- src/a.ts\n- src/b.ts") + "\n\nq",
    );
  });

  it("keeps attached files and open-editor files in separate sections", () => {
    const attached = makeExplicitChip("/a.ts", "a.ts");
    const open = makeImplicitChip("/b.ts", "b.ts");
    const out = buildPrompt("compare", [attached, open], deps);
    expect(out).toBe(
      ctx("Attached file: a.ts\n\nCurrently open in the editor (for context): b.ts") + "\n\ncompare",
    );
  });

  it("renders a selection chip as fenced code (outside the envelope)", () => {
    const chip = makeExplicitChip("/a.ts", "src/a.ts", 2, 4);
    const out = buildPrompt("what is this", [chip], deps);
    expect(out).toBe(
      "`src/a.ts` (lines 2-4):\n```ts\nline2\nline3\nline4\n```\n\nwhat is this",
    );
  });

  it("renders the active-editor file as fenced code once it carries a live selection", () => {
    // The implicit chip mirrors the editor selection in real time; selected
    // lines are a strong signal, so it upgrades from the ambient "Currently
    // open" path line to the same fenced snippet an explicit selection gets.
    const chip = makeImplicitChip("/a.ts", "src/a.ts", 2, 4);
    const out = buildPrompt("what is this", [chip], deps);
    expect(out).toBe(
      "`src/a.ts` (lines 2-4):\n```ts\nline2\nline3\nline4\n```\n\nwhat is this",
    );
  });

  it("skips hidden chips", () => {
    const visible = makeExplicitChip("/a.ts", "a.ts");
    const hidden = { ...makeExplicitChip("/b.ts", "b.ts"), hidden: true };
    expect(buildPrompt("q", [visible, hidden], deps)).toBe(ctx("Attached file: a.ts") + "\n\nq");
  });

  it("falls back to a plain attached path when readFile throws", () => {
    const chip = makeExplicitChip("/missing.ts", "missing.ts", 1, 5);
    expect(buildPrompt("q", [chip], deps)).toBe(ctx("Attached file: missing.ts") + "\n\nq");
  });

  it("combines an attachment with a selection snippet", () => {
    const a = makeExplicitChip("/a.ts", "a.ts");
    const b = makeExplicitChip("/b.ts", "b.ts", 1, 2);
    const out = buildPrompt("compare", [a, b], deps);
    expect(out).toBe(
      ctx("Attached file: a.ts") + "\n\n`b.ts` (lines 1-2):\n```ts\nX\nY\n```\n\ncompare",
    );
  });

  it("uses empty fence language when no extension", () => {
    const chip = makeExplicitChip("/Makefile", "Makefile", 1, 1);
    const out = buildPrompt("", [chip], {
      readFile: () => "all:\n\techo",
      extName: () => "",
    });
    expect(out).toContain("```\nall:");
  });

  // Slash commands only dispatch when they sit at position 0 of the text block
  // (research/compact.md) — a confirmed command flips the order so the context
  // trails the text.
  it("keeps the legacy context-first order when slashCommand is false", () => {
    const out = buildPrompt("/compact", [makeImplicitChip("/a.ts", "src/a.ts")], deps, false);
    expect(out).toBe(ctx("Currently open in the editor (for context): src/a.ts") + "\n\n/compact");
  });

  it("trails the envelope behind a confirmed slash command", () => {
    const out = buildPrompt("/compact", [makeImplicitChip("/a.ts", "src/a.ts")], deps, true);
    expect(out).toBe("/compact\n\n" + ctx("Currently open in the editor (for context): src/a.ts"));
  });

  it("trails selection snippets behind a confirmed slash command too", () => {
    const sel = makeExplicitChip("/b.ts", "b.ts", 1, 2);
    const out = buildPrompt("/compact", [sel], deps, true);
    expect(out).toBe("/compact\n\n`b.ts` (lines 1-2):\n```ts\nX\nY\n```");
  });

  it("keeps envelope-then-snippet order inside the trailing context", () => {
    const attached = makeExplicitChip("/a.ts", "a.ts");
    const sel = makeExplicitChip("/b.ts", "b.ts", 1, 2);
    const out = buildPrompt("/compact", [attached, sel], deps, true);
    expect(out).toBe(
      "/compact\n\n" + ctx("Attached file: a.ts") + "\n\n`b.ts` (lines 1-2):\n```ts\nX\nY\n```",
    );
  });
});

describe("buildPromptWithImages", () => {
  const b64 = Buffer.from("pngbytes").toString("base64");
  // The do-not-Read hint every tag carries (grok otherwise chases the CLI's own
  // assets/ copy of an inline image and fails on the binary).
  const PASTE_TAG = (n: number) =>
    `[Image #${n}] (attached inline — already visible to you; do not read it from disk)`;
  const PATH_TAG = (n: number, p: string) =>
    `[Image #${n}] (${p} — attached inline; act on the path if needed, but do not Read it)`;

  it("is byte-identical to buildPrompt when no images are attached", () => {
    const file = makeExplicitChip("/a.ts", "src/a.ts");
    const out = buildPromptWithImages("do it", [file], [], deps);
    expect(out.text).toBe(buildPrompt("do it", [file], deps));
    expect(out.blocks).toEqual([{ type: "text", text: out.text }]);

    const slash = buildPromptWithImages("/compact", [file], [], deps, true);
    expect(slash.text).toBe(buildPrompt("/compact", [file], deps, true));
    expect(slash.blocks).toEqual([{ type: "text", text: slash.text }]);
  });

  it("keeps a confirmed slash command ahead of both envelope and image tags", () => {
    const file = makeExplicitChip("/a.ts", "src/a.ts");
    const img = makeImageChip("/staging/img.png", 1, "image/png");
    const out = buildPromptWithImages(
      "/imagine make it watercolor",
      [file, img],
      [{ index: 1, mimeType: "image/png", data: b64 }],
      deps,
      true,
    );
    expect(out.text).toBe(
      "/imagine make it watercolor\n\n" +
        `${CONTEXT_TAG_OPEN}\nAttached file: src/a.ts\n${CONTEXT_TAG_CLOSE}` +
        `\n\n${PASTE_TAG(1)}`,
    );
    expect(out.blocks[0]).toEqual({ type: "text", text: out.text });
    expect(out.blocks[1]).toEqual({ type: "image", mimeType: "image/png", data: b64 });
  });

  it("keeps user text first and puts tags on trailing lines", () => {
    const img = makeImageChip("/staging/img.png", 1, "image/png");
    const out = buildPromptWithImages(
      "what is this?",
      [img],
      [{ index: 1, mimeType: "image/png", data: b64 }],
      deps,
    );
    expect(out.text).toBe(`what is this?\n\n${PASTE_TAG(1)}`);
    expect(out.blocks).toEqual([
      { type: "text", text: `what is this?\n\n${PASTE_TAG(1)}` },
      { type: "image", mimeType: "image/png", data: b64 },
    ]);
  });

  it("keeps a slash command at position 0 of the text block", () => {
    const img = makeImageChip("/staging/img.png", 1, "image/png");
    const out = buildPromptWithImages(
      "/imagine make it watercolor",
      [img],
      [{ index: 1, mimeType: "image/png", data: b64 }],
      deps,
    );
    expect(out.text.startsWith("/imagine")).toBe(true);
  });

  it("carries the origin workspace path in the tag for disk imports", () => {
    const img = makeImageChip("/staging/img.png", 2, "image/png", "assets/hero.png");
    const out = buildPromptWithImages(
      "compress this",
      [img],
      [{ index: 2, mimeType: "image/png", data: b64, relPath: "assets/hero.png" }],
      deps,
    );
    expect(out.text).toBe(`compress this\n\n${PATH_TAG(2, "assets/hero.png")}`);
  });

  it("keeps file context separate and ahead of text + tags", () => {
    const file = makeExplicitChip("/a.ts", "src/a.ts");
    const img = makeImageChip("/staging/img.png", 1, "image/png");
    const out = buildPromptWithImages(
      "compare",
      [file, img],
      [{ index: 1, mimeType: "image/png", data: b64 }],
      deps,
    );
    expect(out.text).toBe(
      `${CONTEXT_TAG_OPEN}\nAttached file: src/a.ts\n${CONTEXT_TAG_CLOSE}\n\ncompare\n\n${PASTE_TAG(1)}`,
    );
    expect(out.blocks).toHaveLength(2);
  });

  it("orders multiple images by index with one tag line each", () => {
    const a = makeImageChip("/s/a.png", 3, "image/png");
    const bChip = makeImageChip("/s/b.png", 1, "image/jpeg");
    const out = buildPromptWithImages(
      "",
      [a, bChip],
      [
        { index: 3, mimeType: "image/png", data: "AAA" },
        { index: 1, mimeType: "image/jpeg", data: "BBB" },
      ],
      deps,
    );
    expect(out.text).toBe(`${PASTE_TAG(1)}\n${PASTE_TAG(3)}`);
    expect(out.blocks.map((blk) => (blk.type === "image" ? blk.data : "text"))).toEqual([
      "text",
      "BBB",
      "AAA",
    ]);
  });
});

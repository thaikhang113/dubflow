import { describe, it, expect } from "vitest";
import {
  MAX_VISION_IMAGE_BYTES,
  clearImplicitChips,
  consumeChips,
  extFromMime,
  isVisionImagePath,
  isVisionMime,
  makeExplicitChip,
  makeImageChip,
  makeImplicitChip,
  mimeFromPath,
  removeChip,
  toggleChip,
} from "../src/chips";

describe("chips", () => {
  it("creates an implicit chip with a stable id", () => {
    const c = makeImplicitChip("/abs/path/foo.ts", "foo.ts");
    expect(c.id).toBe("implicit:/abs/path/foo.ts");
    expect(c.hidden).toBe(false);
    expect(c.selectionStart).toBeUndefined();
  });

  it("makeImplicitChip carries the editor selection while keeping the id stable", () => {
    const sel = makeImplicitChip("/abs/path/foo.ts", "foo.ts", 8, 15);
    // Same identity with or without a selection — the chip tracks ONE active
    // editor, so a selection change must update it in place, not add a sibling.
    expect(sel.id).toBe("implicit:/abs/path/foo.ts");
    expect(sel.selectionStart).toBe(8);
    expect(sel.selectionEnd).toBe(15);
  });

  it("creates an explicit chip with a unique id and selection range", () => {
    const c1 = makeExplicitChip("/a.ts", "a.ts", 1, 10);
    const c2 = makeExplicitChip("/a.ts", "a.ts", 1, 10);
    expect(c1.selectionStart).toBe(1);
    expect(c1.selectionEnd).toBe(10);
    expect(c1.id).not.toBe(c2.id); // Date.now suffix makes them unique
  });

  it("removeChip removes by id", () => {
    const a = makeImplicitChip("/a", "a");
    const b = makeImplicitChip("/b", "b");
    const result = removeChip([a, b], a.id);
    expect(result).toEqual([b]);
  });

  it("toggleChip flips hidden without mutating", () => {
    const a = makeImplicitChip("/a", "a");
    const result = toggleChip([a], a.id);
    expect(result[0].hidden).toBe(true);
    expect(a.hidden).toBe(false); // original untouched
    const back = toggleChip(result, a.id);
    expect(back[0].hidden).toBe(false);
  });

  it("toggleChip leaves other chips alone", () => {
    const a = makeImplicitChip("/a", "a");
    const b = makeImplicitChip("/b", "b");
    const result = toggleChip([a, b], a.id);
    expect(result[0].hidden).toBe(true);
    expect(result[1].hidden).toBe(false);
  });

  it("clearImplicitChips removes only implicit ones", () => {
    const imp = makeImplicitChip("/a", "a");
    const exp = makeExplicitChip("/b", "b");
    const result = clearImplicitChips([imp, exp]);
    expect(result).toEqual([exp]);
  });

  it("consumeChips drops exactly what the send snapshotted, keeps the implicit chip", () => {
    const imp = makeImplicitChip("/abs/open.ts", "open.ts");
    const sent = makeExplicitChip("/abs/a.txt", "a.txt");
    expect(consumeChips([imp, sent], [imp, sent])).toEqual([imp]);
  });

  it("consumeChips keeps a chip staged after the send snapshot (next-turn attachment)", () => {
    const sent = makeImageChip("/staging/a.png", 1, "image/png");
    const late = makeImageChip("/staging/b.png", 2, "image/png");
    expect(consumeChips([sent, late], [sent])).toEqual([late]);
  });

  it("isVisionImagePath accepts raster vision formats only", () => {
    expect(isVisionImagePath("/tmp/a.PNG")).toBe(true);
    expect(isVisionImagePath("clip.jpeg")).toBe(true);
    expect(isVisionImagePath("anim.webp")).toBe(true);
    // SVG is an editable text source — it must stay a path chip so grok can
    // read/edit the file; BMP is undocumented for the vision API and huge.
    expect(isVisionImagePath("logo.svg")).toBe(false);
    expect(isVisionImagePath("shot.bmp")).toBe(false);
    expect(isVisionImagePath("notes.md")).toBe(false);
  });

  it("isVisionMime mirrors the extension whitelist", () => {
    expect(isVisionMime("image/png")).toBe(true);
    expect(isVisionMime("image/JPEG")).toBe(true);
    expect(isVisionMime("image/svg+xml")).toBe(false);
    expect(isVisionMime("image/bmp")).toBe(false);
    expect(isVisionMime("text/plain")).toBe(false);
  });

  it("mimeFromPath and extFromMime are derived from one table", () => {
    expect(mimeFromPath("/a/b.JPG")).toBe("image/jpeg");
    expect(mimeFromPath("/a/b.jpeg")).toBe("image/jpeg");
    expect(mimeFromPath("noext")).toBe("image/png"); // no extension → safe default
    expect(extFromMime("image/jpeg")).toBe(".jpg"); // canonical ext, not .jpeg
    expect(extFromMime("image/webp")).toBe(".webp");
    expect(extFromMime("application/octet-stream")).toBe(".png");
  });

  it("caps vision images at the documented 20MiB", () => {
    expect(MAX_VISION_IMAGE_BYTES).toBe(20 * 1024 * 1024);
  });

  it("makeImageChip labels relPath as Image #N and carries the origin path", () => {
    const c = makeImageChip("/staging/x.png", 2, "image/png", "assets/hero.png");
    expect(c.relPath).toBe("Image #2");
    expect(c.imageIndex).toBe(2);
    expect(c.mimeType).toBe("image/png");
    expect(c.originRelPath).toBe("assets/hero.png");
    const pasted = makeImageChip("/staging/y.png", 3, "image/png");
    expect(pasted.originRelPath).toBeUndefined();
  });
});

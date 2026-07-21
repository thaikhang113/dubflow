export interface FileChip {
  id: string;
  path: string;
  relPath: string;
  selectionStart?: number;
  selectionEnd?: number;
  hidden: boolean;
  /** 1-based, session-scoped index for pasted/uploaded images — the `[Image #N]`
   *  tag sent in the prompt text. Assigned from Session.imageCounter. */
  imageIndex?: number;
  mimeType?: string;
  /** Workspace-relative path of the original file for images imported from disk
   *  (kept so the prompt tag can carry the real file identity — `path` points at
   *  the staged copy). Absent for clipboard pastes, which have no origin file. */
  originRelPath?: string;
}

// Formats we send to grok as inline vision blocks. Deliberately narrower than
// "any image extension": SVG is excluded because it's an editable text source —
// a user attaching one almost always wants grok to read/edit the file, which the
// path-chip route does and a rasterized vision block cannot; BMP is excluded
// because xAI's vision API documents only jpg/jpeg/png (gif/webp verified
// accepted by research/vision-probe.cjs) and uncompressed BMPs are huge.
const VISION_EXT_RE = /\.(png|jpe?g|gif|webp)$/i;
const VISION_MIME_RE = /^image\/(png|jpeg|gif|webp)$/i;

/** xAI Image Understanding documents a 20MiB per-image cap — preflight it
 *  locally so an oversized file degrades to a path chip (or a clear error)
 *  instead of a failed turn. */
export const MAX_VISION_IMAGE_BYTES = 20 * 1024 * 1024;

/** Should this file ride the inline-vision path (vs a plain path chip)? */
export function isVisionImagePath(p: string): boolean {
  return VISION_EXT_RE.test(p);
}

export function isVisionMime(mime: string): boolean {
  return VISION_MIME_RE.test(mime);
}

export function isImageChip(chip: FileChip): boolean {
  return chip.imageIndex != null;
}

/** Single source of truth for the vision formats' ext ↔ MIME mapping —
 *  mimeFromPath and extFromMime are both derived from it. */
const EXT_MIME: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
};

export function mimeFromPath(p: string): string {
  const dot = p.lastIndexOf(".");
  if (dot < 0) return "image/png";
  return EXT_MIME[p.slice(dot).toLowerCase()] ?? "image/png";
}

export function extFromMime(mime: string): string {
  const lower = mime.toLowerCase();
  for (const [ext, m] of Object.entries(EXT_MIME)) {
    if (m === lower && ext !== ".jpeg") return ext;
  }
  return ".png";
}

export function makeImplicitChip(
  absPath: string,
  relPath: string,
  selectionStart?: number,
  selectionEnd?: number,
): FileChip {
  return {
    id: `implicit:${absPath}`,
    path: absPath,
    relPath,
    selectionStart,
    selectionEnd,
    hidden: false,
  };
}

let explicitChipCounter = 0;

export function makeExplicitChip(
  absPath: string,
  relPath: string,
  selectionStart?: number,
  selectionEnd?: number,
): FileChip {
  explicitChipCounter += 1;
  return {
    id: `explicit:${absPath}:${selectionStart ?? 0}-${selectionEnd ?? 0}:${explicitChipCounter}`,
    path: absPath,
    relPath,
    selectionStart,
    selectionEnd,
    hidden: false,
  };
}

export function makeImageChip(
  absPath: string,
  imageIndex: number,
  mimeType: string,
  originRelPath?: string,
): FileChip {
  explicitChipCounter += 1;
  return {
    id: `image:${absPath}:${imageIndex}:${explicitChipCounter}`,
    path: absPath,
    relPath: `Image #${imageIndex}`,
    hidden: false,
    imageIndex,
    mimeType,
    originRelPath,
  };
}

export function removeChip(chips: FileChip[], id: string): FileChip[] {
  return chips.filter((c) => c.id !== id);
}

export function toggleChip(chips: FileChip[], id: string): FileChip[] {
  return chips.map((c) => (c.id === id ? { ...c, hidden: !c.hidden } : c));
}

export function clearImplicitChips(chips: FileChip[]): FileChip[] {
  return chips.filter((c) => !isImplicitChip(c));
}

/** Drop exactly the chips a send consumed. The implicit context chip stays
 *  (it mirrors IDE state, not a one-shot attachment) — and so does anything
 *  NOT in the send's snapshot: a chip staged while the send was pre-reading
 *  images belongs to the next turn, not the bin. */
export function consumeChips(current: FileChip[], sent: FileChip[]): FileChip[] {
  const sentIds = new Set(sent.map((c) => c.id));
  return current.filter((c) => isImplicitChip(c) || !sentIds.has(c.id));
}

/** An implicit chip is the active-editor file auto-added for ambient context
 *  (vs. a file the user explicitly attached). The id prefix is the source of
 *  truth — set by makeImplicitChip / makeExplicitChip. */
export function isImplicitChip(chip: FileChip): boolean {
  return chip.id.startsWith("implicit:");
}

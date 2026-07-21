/**
 * Pure helpers for the webview → host "open file" / "drop file" flows. Split out
 * so the path-ref parsing and the large-file guard can be unit-tested without a
 * `vscode` or `fs` dependency.
 */

export interface FileRef {
  path: string;
  startLine?: number;
  endLine?: number;
}

/**
 * Split a `path[#L<start>[-[L]<end>]]` reference into its parts. The `#L…`
 * fragment is anchored to the *end* of the string (via lazy `.*?`), so a literal
 * `#` earlier in the path — C#/F# project folders, for instance — stays part of
 * the path instead of breaking the match. Line numbers are returned 1-based,
 * exactly as written.
 */
export function parseFileRef(raw: string): FileRef {
  const m = raw.match(/^(.*?)(?:#L(\d+)(?:-L?(\d+))?)?$/i);
  if (!m) return { path: raw };
  const startLine = m[2] ? Number(m[2]) : undefined;
  if (startLine == null) return { path: m[1] };
  const endLine = m[3] ? Number(m[3]) : undefined;
  return endLine == null ? { path: m[1], startLine } : { path: m[1], startLine, endLine };
}

/** Files at or below this size may be read synchronously to count lines. */
export const MAX_INLINE_CHIP_BYTES = 10 * 1024 * 1024;

/**
 * Whether a dropped file is small enough to `readFileSync` on the extension-host
 * thread (to count lines for an inline chip). Larger files would freeze the UI —
 * the caller should fall back to a no-selection chip.
 */
export function shouldReadFileInline(sizeBytes: number, maxBytes = MAX_INLINE_CHIP_BYTES): boolean {
  return sizeBytes <= maxBytes;
}

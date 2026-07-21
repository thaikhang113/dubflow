/**
 * Minimal reader for grok's `config.toml` — just enough to detect the
 * always-approve permission mode (#31). No TOML dependency: a section-aware
 * line scan for the single `permission_mode` key under the `[ui]` table.
 *
 * grok writes `permission_mode = "always-approve"` when the user picks
 * "Always Approve" via Shift+Tab or runs `/always-approve` in the TUI, which
 * silently makes *every* grok session (CLI + this extension) auto-approve tool
 * actions server-side. The extension can't see that over ACP (the CLI still
 * reports the ordinary `default`/agent mode), so it reads the file directly to
 * keep the mode button honest.
 */

/** True when a `permission_mode` value means "auto-approve everything". grok
 *  writes the hyphenated spelling; the underscore variant is accepted too. */
export function isAlwaysApprovePermission(value: string | undefined): boolean {
  if (!value) return false;
  return value.trim().toLowerCase().replace(/_/g, "-") === "always-approve";
}

/**
 * Read `permission_mode` from the `[ui]` table of a config.toml string, or
 * `undefined` when the table/key is absent. Comments (`#…`) and surrounding
 * quotes are stripped, and only the `[ui]` table is consulted so a
 * `permission_mode` under another table can't be misread.
 */
export function readUiPermissionMode(toml: string): string | undefined {
  let inUi = false;
  for (const raw of toml.split(/\r?\n/)) {
    const line = raw.replace(/#.*$/, "").trim();
    if (!line) continue;
    const table = line.match(/^\[\[?\s*([^\]]+?)\s*\]\]?$/);
    if (table) {
      inUi = table[1].trim() === "ui";
      continue;
    }
    if (!inUi) continue;
    const kv = line.match(/^permission_mode\s*=\s*(.+)$/);
    if (kv) return kv[1].trim().replace(/^["']|["']$/g, "").trim();
  }
  return undefined;
}

/**
 * The effective always-approve verdict from a project + global config pair.
 * Project `.grok/config.toml` overrides global `~/.grok/config.toml` (grok
 * merges project over global); a key absent from project falls back to global.
 * Either string may be `undefined` (file missing / unreadable).
 */
export function configForcesAlwaysApprove(input: {
  project?: string;
  global?: string;
}): boolean {
  const projectMode = input.project != null ? readUiPermissionMode(input.project) : undefined;
  const effective =
    projectMode ?? (input.global != null ? readUiPermissionMode(input.global) : undefined);
  return isAlwaysApprovePermission(effective);
}

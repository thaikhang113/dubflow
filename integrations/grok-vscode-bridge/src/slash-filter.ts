export interface SlashCmd {
  name: string;
  description?: string;
}

/**
 * Slash commands the extension hides from both the autocomplete list and the
 * dispatch gate. `/always-approve` (#31) only mutates grok's *global*
 * config.toml — a surprising, sticky side effect that then silences permission
 * cards in every grok session — and is a no-op over ACP anyway. `/context`
 * (#39) renders only in the CLI's own TUI: over ACP stdio it streams nothing
 * back, so selecting it silently does nothing (`/session-info` is the working
 * equivalent). Filtered at ingestion (see `filterAdvertisedCommands`).
 */
export const HIDDEN_SLASH_COMMANDS: ReadonlySet<string> = new Set(["always-approve", "context"]);

/** Drop hidden commands from an advertised `available_commands_update` list. */
export function filterAdvertisedCommands<T extends { name: string }>(commands: T[]): T[] {
  return commands.filter((c) => !HIDDEN_SLASH_COMMANDS.has(c.name));
}

/**
 * Given the current composer text and cursor position, return the slash-command query
 * (the chars after `/` on the line that the caret is in) or `null` if no popover is active.
 *
 * The popover activates only when `/` is at the start of the line or after a newline.
 */
export function getSlashQuery(text: string, caret: number): string | null {
  const before = text.slice(0, caret);
  const m = before.match(/(?:^|\n)\/(\S*)$/);
  return m ? m[1] : null;
}

export function filterCommands(commands: SlashCmd[], query: string): SlashCmd[] {
  const q = query.toLowerCase();
  if (!q) return commands;
  return commands.filter((c) => c.name.toLowerCase().startsWith(q));
}

/** Replace the partial `/q` token with `/<name> ` and return the new text + caret. */
export function applySlashPick(
  text: string,
  caret: number,
  name: string,
): { text: string; caret: number } {
  const before = text.slice(0, caret);
  const after = text.slice(caret);
  const newBefore = before.replace(/(?:^|\n)\/(\S*)$/, (m) =>
    m.startsWith("\n") ? `\n/${name} ` : `/${name} `,
  );
  return { text: newBefore + after, caret: newBefore.length };
}

/**
 * The slash command a typed message dispatches, or `null` for ordinary prose.
 *
 * The CLI only recognizes a slash command when it sits at position 0 of the
 * prompt's text block — editor-injected context in front of it silently turns
 * `/compact` into a normal LLM turn (verified against grok 0.2.87 in
 * research/compact-probe.cjs). The caller uses a match to move that context
 * BEHIND the command text instead (see buildPrompt), so this must never match
 * prose: the token boundary rejects Unix paths (`/tmp/foo` — `tmp` is followed
 * by `/`, not whitespace/end), and a known-commands check rejects things shaped
 * like commands that grok never advertised. An empty `commandNames` means the
 * `available_commands_update` hasn't arrived yet — fall back to shape alone,
 * since a wrongly-trailing envelope (broken dispatch) costs far more than a
 * wrongly-leading one (grok just reads the context first).
 */
export function matchSlashCommand(text: string, commandNames: string[]): string | null {
  const m = text.match(/^\/([A-Za-z0-9][\w.:-]*)(?:\s|$)/);
  if (!m) return null;
  if (commandNames.length === 0) return m[1];
  return commandNames.includes(m[1]) ? m[1] : null;
}

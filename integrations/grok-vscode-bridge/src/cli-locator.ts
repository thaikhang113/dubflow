import { existsSync } from "node:fs";
import { execSync } from "node:child_process";
import { homedir } from "node:os";
import * as path from "node:path";

const IS_WIN = process.platform === "win32";

function candidateNames(): string[] {
  return IS_WIN ? ["grok.cmd", "grok.exe", "grok.bat", "grok"] : ["grok"];
}

function effectiveHome(): string {
  // Respect env overrides first so tests + users can redirect the home lookup.
  const fromEnv = IS_WIN ? process.env.USERPROFILE : process.env.HOME;
  return fromEnv || homedir();
}

export function locateGrokCli(configuredPath: string): string | undefined {
  if (configuredPath) {
    return existsSync(configuredPath) ? configuredPath : undefined;
  }
  const homeBin = path.join(effectiveHome(), ".grok", "bin");
  for (const name of candidateNames()) {
    const candidate = path.join(homeBin, name);
    if (existsSync(candidate)) return candidate;
  }
  try {
    const cmd = IS_WIN ? "where grok" : "command -v grok";
    const out = execSync(cmd, { encoding: "utf8" }).trim();
    const first = out.split(/\r?\n/)[0]?.trim();
    if (first && existsSync(first)) return first;
  } catch {
    // ignore — not on PATH
  }
  return undefined;
}

/**
 * Decide whether to silently auto-update the grok CLI because *our extension* was
 * upgraded since the last run. True only when a prior version was recorded (so a
 * fresh install never triggers an update — that's the "not-first-run" rule) and it
 * differs from the current extension version. Pure so it's unit-testable.
 */
export function extensionWasUpgraded(lastSeen: string | undefined, current: string): boolean {
  return !!lastSeen && !!current && lastSeen !== current;
}

/**
 * The supported grok CLI version the extension pins Windows to. The `agent stdio`
 * #22 regression broke **0.2.61–0.2.70**; the fix landed in **0.2.71** and is now on
 * the **stable** channel as **0.2.72** (the supported build here), verified end-to-end
 * via the session/new probe + the live ACP gate. We pin a broken build to this. Bump
 * it when a newer Windows-verified build ships — re-verify with the **session/new**
 * probe, not just `initialize`.
 */
export const GROK_STDIO_DOWNGRADE_TARGET = "0.2.72";

/**
 * Parse a grok `--version` banner ("grok 0.2.64 (9a9ac25b10) [stable]") into a
 * `[major, minor, patch]` tuple, or undefined when no `X.Y.Z` is present. Pure.
 */
export function parseGrokVersion(versionOutput: string): [number, number, number] | undefined {
  const m = /(\d+)\.(\d+)\.(\d+)/.exec(versionOutput ?? "");
  if (!m) return undefined;
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

/**
 * grok CLI **0.2.61–0.2.70** shipped a Windows-only `agent stdio` regression: the
 * agent didn't read stdin lines until EOF (which never comes for a live client), so an
 * ACP startup request timed out and the process was torn down ("exited with code
 * null"). It mutated across builds — 0.2.61–0.2.64 hung at `initialize`;
 * 0.2.67/0.2.69/0.2.70 answered `initialize` but hung at `session/new` — and was
 * **fixed in 0.2.71**, now on stable as **0.2.72** (`GROK_STDIO_DOWNGRADE_TARGET`),
 * verified via the session/new probe + the live ACP gate. See issue #22 and
 * `research/stdio-eof-regression.md`.
 *
 * Detect the bounded broken range **0.2.61–0.2.70** (Windows only) so the host pins
 * those builds to the supported 0.2.72 before spawning. The fix sits *above* the broken
 * range, so this is a closed range — not an open-ended "anything newer" check: both
 * 0.2.71+ and <=0.2.60 are fine. A *future* still-broken build above 0.2.72 is caught
 * reactively (`shouldReactivelyDowngrade`). Pure.
 */
export function isStdioBrokenGrokVersion(versionOutput: string, platform: NodeJS.Platform): boolean {
  if (platform !== "win32") return false;
  const v = parseGrokVersion(versionOutput);
  if (!v) return false;
  const [maj, min, pat] = v;
  return maj === 0 && min === 2 && pat >= 61 && pat <= 70;
}

/** Compare two `[major, minor, patch]` tuples: <0, 0, or >0. Pure. */
export function compareVersionTuple(a: [number, number, number], b: [number, number, number]): number {
  return a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
}

/**
 * Decision for the "Update Grok Build CLI" action (manual menu *and* the silent
 * on-upgrade update), given the installed version + platform.
 *
 * The #22 Windows update pause is **lifted** now that 0.2.71 fixes the regression —
 * updates proceed normally on every platform (to `latest`). The #22 safety net still
 * stands behind this: the proactive pin (`isStdioBrokenGrokVersion` → 0.2.61–0.2.70)
 * and the reactive downgrade (`shouldReactivelyDowngrade` → builds above 0.2.72)
 * recover a session if an update ever lands on a still-broken build.
 */
export interface GrokUpdatePolicy {
  /** May the update run at all? */
  allow: boolean;
  /** When allowed, pin to this exact version instead of `latest` (undefined ⇒ latest). */
  target?: string;
  /** When blocked, the reason to surface in the menu / log. */
  note?: string;
}

export function grokUpdatePolicy(_versionOutput: string, _platform: NodeJS.Platform): GrokUpdatePolicy {
  // Updates are no longer gated for #22 (fixed in 0.2.71). Always allow, to latest.
  return { allow: true };
}

/**
 * Should the host REACTIVELY downgrade the CLI after an *observed* `agent stdio`
 * init failure (handshake timeout / "exited code null")?
 *
 * The proactive `isStdioBrokenGrokVersion` covers the known broken range
 * (0.2.61–0.2.70) before spawning. This is the evidence-driven backstop for a *future*
 * still-broken build **above** the supported 0.2.72 (no static range can predict it),
 * or for cases the proactive pin couldn't run (version read failed, or the binary was
 * locked so `grok update` couldn't rename it). It fires on the real failure
 * (`initialize` *or* `session/new`), not a version guess, and pins back to 0.2.72.
 *
 * Windows-only (the regression is). A build at/below 0.2.72 is never downgraded —
 * that's the loop guard: once the pin lands the version is exactly the target, so a
 * subsequent failure (some other cause) can't trigger another downgrade. A later
 * *manual* re-upgrade pushes the version back above the target, so a fresh failure
 * re-triggers the downgrade — exactly the "they upgraded anyway, fix it again"
 * case. Unparseable version ⇒ leave alone. Pure.
 */
export function shouldReactivelyDowngrade(versionOutput: string, platform: NodeJS.Platform): boolean {
  if (platform !== "win32") return false;
  const v = parseGrokVersion(versionOutput);
  if (!v) return false;
  const target = parseGrokVersion(GROK_STDIO_DOWNGRADE_TARGET)!;
  return compareVersionTuple(v, target) > 0;
}

/**
 * Does a failed `grok update` error mean the binary was still locked? On Windows
 * `grok update` renames `grok.exe` in place, which fails while any grok process
 * (or a backgrounded subagent child) still holds it open — the OS releases the
 * lock a beat after the process is killed, so a too-eager update races it. grok
 * reports this as *"cannot rename locked executable … Access is denied. (os error
 * 5)"*. Used to decide whether a retry is worth it (the lock clears on its own);
 * any other failure is real and shouldn't be retried. Pure.
 */
export function isLockedBinaryError(message: string): boolean {
  return /locked executable|os error 5|access is denied/i.test(message);
}

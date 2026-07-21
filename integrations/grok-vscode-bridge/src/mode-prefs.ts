// Pure helpers for the remembered-mode preference (#25). Kept out of sidebar.ts
// so the policy — "remember the last Agent/Auto-accept switch, never Plan; apply
// it to new sessions only" — is unit-testable without vscode/spawn.

export type ModeId = "agent" | "plan" | "yolo";

/**
 * The mode value to persist for a user's mode switch, or `null` to leave the
 * remembered preference unchanged. Plan is a transient per-task choice, so it is
 * never remembered (#25). Mirrors how `defaultModel`/`defaultEffort` persist.
 */
export function modeToRemember(modeId: ModeId): "agent" | "yolo" | null {
  return modeId === "plan" ? null : modeId;
}

/**
 * Whether a brand-new session should start in Auto accept (YOLO), given the
 * remembered `grok.defaultMode` and whether this start is a resume. Resumed
 * sessions are verdict-driven (plan-restore decides), so they never pre-apply
 * the remembered mode.
 */
export function startsInYolo(defaultMode: string | undefined, isResume: boolean): boolean {
  return !isResume && defaultMode === "yolo";
}

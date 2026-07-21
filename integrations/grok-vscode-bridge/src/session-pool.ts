import { SessionStatus } from "./session";

/**
 * Pure reaping policy for the live-session pool (Full-pool Agent Dashboard).
 *
 * Backgrounded sessions stay live so re-focusing is always lossless, but a live
 * `grok agent stdio` process per session isn't free — so the pool is bounded two
 * ways: an idle TTL (a session untouched for `idleTtlMs` is torn down) and an LRU
 * cap (`maxLive` live processes; the least-recently-used eligible sessions are
 * reaped to stay under it). Reaping is **silent** — the user just sees the dot go
 * cold; re-clicking the row re-loads it from grok's on-disk history.
 *
 * What's NEVER reaped: the focused session, and any `working`/`needs-you` session
 * (tearing down mid-turn or mid-approval would lose work the user can't see). The
 * cap may therefore be exceeded if every extra session is busy — by design.
 *
 * Selection is pure so it can be unit-tested without a process pool: the caller
 * maps its Session pool to candidates carrying just `{status, lastActiveAt,
 * focused}` (plus whatever back-reference it needs), and disposes whatever this
 * returns.
 */
export interface ReapCandidate {
  status: SessionStatus;
  /** ms-epoch of the last time this session was created/focused/made busy. */
  lastActiveAt: number;
  /** The currently-focused session — never reaped. */
  focused: boolean;
}

export interface ReapPolicy {
  /** Max number of live sessions before LRU reaping kicks in. */
  maxLive: number;
  /** A session idle/done/error for at least this long is TTL-reaped. */
  idleTtlMs: number;
  /** Current time (ms epoch) — injected so the function stays pure/testable. */
  now: number;
}

/** A session is reap-eligible only if it isn't focused and isn't mid-work. */
function isEligible(c: ReapCandidate): boolean {
  return !c.focused && (c.status === "idle" || c.status === "done" || c.status === "error");
}

/**
 * Decide which sessions to reap, given the whole pool and the policy. Returns the
 * subset of `candidates` to tear down (a session expired by TTL, or evicted by the
 * LRU cap). Order of the returned array is unspecified.
 */
export function selectReapable<T extends ReapCandidate>(candidates: T[], policy: ReapPolicy): T[] {
  const { maxLive, idleTtlMs, now } = policy;
  const eligible = candidates.filter(isEligible);
  const reap = new Set<T>();

  // 1. TTL: anything eligible that's been idle past the window.
  for (const c of eligible) {
    if (now - c.lastActiveAt >= idleTtlMs) reap.add(c);
  }

  // 2. LRU cap: if still over the cap after TTL reaping, evict the
  //    least-recently-used eligible sessions until we're under it (or run out of
  //    eligible ones — busy sessions hold the line and may exceed the cap).
  let liveCount = candidates.length - reap.size;
  if (liveCount > maxLive) {
    const lru = eligible
      .filter((c) => !reap.has(c))
      .sort((a, b) => a.lastActiveAt - b.lastActiveAt);
    for (const c of lru) {
      if (liveCount <= maxLive) break;
      reap.add(c);
      liveCount--;
    }
  }

  return candidates.filter((c) => reap.has(c));
}

/**
 * The visible dot for one history row (Agent Dashboard). Pure so the policy can be
 * unit-tested without a process pool. Precedence:
 *   working → needs-you → unread (error? → error) → none (gray default).
 *
 * `working`/`needs-you` come from the live session's `status`; `unread`/`error`
 * come from a *persisted* flag set when a turn finishes while the session isn't
 * focused, and cleared when it's opened — so green/red survive both reaping and a
 * reload (they aren't tied to the live process). Everything else — idle, already
 * read, cold, loaded-from-disk — collapses to `none`, a single gray "at rest".
 */
export type Dot = "working" | "needs-you" | "unread" | "error" | "none";

export function computeDot(opts: {
  liveStatus?: SessionStatus;
  unread?: boolean;
  unreadError?: boolean;
}): Dot {
  if (opts.liveStatus === "working") return "working";
  if (opts.liveStatus === "needs-you") return "needs-you";
  if (opts.unread) return opts.unreadError ? "error" : "unread";
  return "none";
}

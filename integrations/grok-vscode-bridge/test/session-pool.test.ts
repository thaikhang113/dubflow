// Unit tests for the pure live-session reaping policy (Full-pool Agent Dashboard).
//
// `selectReapable` decides which backgrounded grok sessions get torn down so the
// pool stays bounded — without ever killing the focused session or one that's
// mid-work. The invariants that matter (and would regress silently):
//   - never reap the focused session, even if it's idle and ancient
//   - never reap a `working` / `needs-you` session (mid-turn / mid-approval)
//   - TTL: an eligible session idle past the window is reaped
//   - LRU cap: over the cap, the *least-recently-used* eligible ones go first
//   - the cap may be exceeded when every spare session is busy (busy holds the line)
import { describe, it, expect } from "vitest";
import { selectReapable, computeDot, ReapCandidate } from "../src/session-pool";

type C = ReapCandidate & { id: string };
const c = (id: string, status: C["status"], lastActiveAt: number, focused = false): C => ({
  id,
  status,
  lastActiveAt,
  focused,
});

const HOUR = 60 * 60 * 1000;
const ids = (out: C[]) => out.map((x) => x.id).sort();

describe("selectReapable — TTL", () => {
  it("reaps an eligible session idle past the TTL", () => {
    const now = 10 * HOUR;
    const pool = [c("old", "idle", now - 2 * HOUR), c("fresh", "idle", now - 1000)];
    expect(ids(selectReapable(pool, { maxLive: 8, idleTtlMs: HOUR, now }))).toEqual(["old"]);
  });

  it("treats done and error sessions as eligible for the TTL", () => {
    const now = 10 * HOUR;
    const pool = [c("d", "done", now - 2 * HOUR), c("e", "error", now - 2 * HOUR)];
    expect(ids(selectReapable(pool, { maxLive: 8, idleTtlMs: HOUR, now }))).toEqual(["d", "e"]);
  });

  it("never reaps a working or needs-you session, however stale", () => {
    const now = 100 * HOUR;
    const pool = [c("w", "working", 0), c("n", "needs-you", 0)];
    expect(selectReapable(pool, { maxLive: 8, idleTtlMs: HOUR, now })).toEqual([]);
  });

  it("never reaps the focused session, however stale + idle", () => {
    const now = 100 * HOUR;
    const pool = [c("focused", "idle", 0, true)];
    expect(selectReapable(pool, { maxLive: 8, idleTtlMs: HOUR, now })).toEqual([]);
  });
});

describe("selectReapable — LRU cap", () => {
  it("evicts the least-recently-used eligible sessions to get under the cap", () => {
    const now = HOUR; // well within TTL, so only the cap is in play
    const pool = [
      c("a", "idle", now - 5000), // oldest
      c("b", "idle", now - 4000),
      c("c", "idle", now - 3000),
      c("d", "idle", now - 2000),
      c("e", "idle", now - 1000), // newest
    ];
    // cap of 3 → must drop 2 → the two oldest (a, b)
    expect(ids(selectReapable(pool, { maxLive: 3, idleTtlMs: 10 * HOUR, now }))).toEqual(["a", "b"]);
  });

  it("does not reap when at or under the cap", () => {
    const now = HOUR;
    const pool = [c("a", "idle", now - 5000), c("b", "idle", now - 4000)];
    expect(selectReapable(pool, { maxLive: 3, idleTtlMs: 10 * HOUR, now })).toEqual([]);
  });

  it("skips busy + focused sessions when choosing LRU victims (cap may be exceeded)", () => {
    const now = HOUR;
    const pool = [
      c("focused", "idle", 0, true), // oldest but focused → protected
      c("busy", "working", 1), // ancient but busy → protected
      c("idle1", "idle", now - 3000),
      c("idle2", "idle", now - 2000),
    ];
    // cap of 1, but only idle1/idle2 are eligible. We can evict at most those two;
    // focused + busy hold the line, so the live count lands at 2 (> cap) by design.
    expect(ids(selectReapable(pool, { maxLive: 1, idleTtlMs: 10 * HOUR, now }))).toEqual([
      "idle1",
      "idle2",
    ]);
  });

  it("combines TTL and LRU: TTL-expired plus enough LRU to reach the cap", () => {
    const now = 10 * HOUR;
    const pool = [
      c("stale", "idle", now - 2 * HOUR), // TTL-expired
      c("a", "idle", now - 5000), // LRU order within the fresh ones
      c("b", "idle", now - 4000),
      c("c", "idle", now - 1000),
    ];
    // stale goes on TTL → live=3. cap=2 → drop one more LRU (a, the oldest fresh).
    expect(ids(selectReapable(pool, { maxLive: 2, idleTtlMs: HOUR, now }))).toEqual(["a", "stale"]);
  });
});

describe("computeDot — the dashboard dot color", () => {
  it("live status wins: working → working, needs-you → needs-you", () => {
    expect(computeDot({ liveStatus: "working" })).toBe("working");
    expect(computeDot({ liveStatus: "needs-you" })).toBe("needs-you");
    // ...even if the session is also flagged unread.
    expect(computeDot({ liveStatus: "working", unread: true })).toBe("working");
    expect(computeDot({ liveStatus: "needs-you", unread: true, unreadError: true })).toBe("needs-you");
  });

  it("unread (no blocking live state) → green, or red if it errored", () => {
    expect(computeDot({ liveStatus: "done", unread: true })).toBe("unread");
    expect(computeDot({ liveStatus: "done", unread: true, unreadError: true })).toBe("error");
    // unread survives with no live status at all (reaped but still unread).
    expect(computeDot({ unread: true })).toBe("unread");
    expect(computeDot({ unread: true, unreadError: true })).toBe("error");
  });

  it("everything at rest collapses to none (gray)", () => {
    expect(computeDot({})).toBe("none");
    expect(computeDot({ liveStatus: "idle" })).toBe("none");
    expect(computeDot({ liveStatus: "done" })).toBe("none"); // done but read (not unread)
    expect(computeDot({ liveStatus: "error" })).toBe("none"); // errored but read
    expect(computeDot({ unread: false })).toBe("none");
  });
});

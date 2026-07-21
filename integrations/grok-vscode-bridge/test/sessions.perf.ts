// Performance simulation for the session-history popover (issue #19 follow-up).
//
// NOT part of `npm test` / CI — run with `npm run test:perf`. It builds a large
// in-memory session store and contrasts the OLD full-scan (read+parse every
// summary.json on every popover open) against the NEW index+page approach
// (one cheap `stat` per dir to order, then read+parse only the visible window),
// plus the steady-state mtime cache that serves repeat opens with zero reads.
//
// Two things are measured:
//   1. Op counts (statSync vs readFileSync) — exact, deterministic, asserted.
//   2. A modeled wall-clock projection — `stat` and `read+parse` cost very
//      different amounts on a real disk, so we weight the op counts to show the
//      user-visible latency difference at scale. Printed, not asserted (the
//      weights are illustrative, the op counts are the hard numbers).
import { describe, it, expect } from "vitest";
import * as path from "node:path";
import {
  FsLike,
  SessionListEntry,
  SessionMetaOverrides,
  indexSessions,
  listSessions,
  readSessionEntries,
  sessionsDirFor,
} from "../src/sessions";

const grokHome = "/home/user/.grok";
const cwd = "/work/project";
const PAGE = 100;

// Modeled per-op latency on a warm SSD (illustrative). A read also pays JSON.parse,
// so it's ~10x a bare stat. Used only for the printed projection.
const STAT_MS = 0.05;
const READ_MS = 0.6;

interface Counters {
  stats: number;
  reads: number;
}

/** Build an in-memory fs holding `n` session dirs, each with a summary.json. mtime and
 *  updated_at both increase with the index so newest-first ordering is well-defined. The
 *  returned fs increments `counters` on every stat/read so callers can measure access. */
function buildStore(n: number, counters: Counters): FsLike {
  const dir = sessionsDirFor(grokHome, cwd);
  const ids: string[] = [];
  const summaries = new Map<string, { content: string; mtimeMs: number }>();
  for (let i = 0; i < n; i++) {
    const id = `019e${String(i).padStart(8, "0")}-7a11-7000-8000-000000000000`;
    ids.push(id);
    const summaryPath = path.join(dir, id, "summary.json");
    const updated = new Date(Date.UTC(2026, 0, 1) + i * 60000).toISOString();
    summaries.set(summaryPath, {
      mtimeMs: 1_700_000_000_000 + i * 60000,
      content: JSON.stringify({
        info: { id, cwd },
        session_summary: `Session number ${i} doing some work on the project`,
        created_at: updated,
        updated_at: updated,
        num_messages: (i % 30) + 1,
        current_model_id: "grok-build",
      }),
    });
  }
  return {
    existsSync: (p) => p === dir || summaries.has(p),
    readdirSync: (p) => {
      if (p !== dir) throw new Error(`ENOENT: ${p}`);
      return ids.slice();
    },
    readFileSync: (p) => {
      const s = summaries.get(p);
      if (!s) throw new Error(`ENOENT: ${p}`);
      counters.reads++;
      return s.content;
    },
    statSync: (p) => {
      const s = summaries.get(p);
      if (!s) throw new Error(`ENOENT: ${p}`);
      counters.stats++;
      return { isDirectory: () => false, mtimeMs: s.mtimeMs };
    },
    rmdirSync: () => {},
  };
}

/** Mirror of the host's mtime-keyed read cache (sidebar.ts readEntriesCached), so the
 *  simulation can show steady-state behavior across repeated popover opens. */
function makeCachedReader(fs: FsLike, overrides: SessionMetaOverrides) {
  const cache = new Map<string, { mtimeMs: number; entry: SessionListEntry }>();
  return (ids: string[], mtimeById: Map<string, number>): SessionListEntry[] => {
    const stale = ids.filter((id) => cache.get(id)?.mtimeMs !== (mtimeById.get(id) ?? -1));
    if (stale.length) {
      for (const e of readSessionEntries({ fs, grokHome, cwd, ids: stale, overrides })) {
        cache.set(e.id, { mtimeMs: mtimeById.get(e.id) ?? 0, entry: e });
      }
    }
    return ids.map((id) => cache.get(id)!.entry).filter(Boolean);
  };
}

/** One paginated popover open: index (stats only) + read just the first page. */
function openFirstPage(fs: FsLike, overrides: SessionMetaOverrides) {
  const index = indexSessions({ fs, grokHome, cwd });
  const pageIds = index.slice(0, PAGE).map((e) => e.id);
  const entries = readSessionEntries({ fs, grokHome, cwd, ids: pageIds, overrides });
  entries.sort((a, b) => b.updatedAt - a.updatedAt);
  return entries;
}

function projectedMs(c: Counters): number {
  return c.stats * STAT_MS + c.reads * READ_MS;
}

describe("session history performance (simulation, run via npm run test:perf)", () => {
  const N = 5000;
  const overrides: SessionMetaOverrides = {};

  it("paginated open reads only one page; full scan reads everything", () => {
    const full: Counters = { stats: 0, reads: 0 };
    const fullFs = buildStore(N, full);
    const fullList = listSessions({ fs: fullFs, grokHome, cwd, overrides });

    const paged: Counters = { stats: 0, reads: 0 };
    const pagedFs = buildStore(N, paged);
    const firstPage = openFirstPage(pagedFs, overrides);

    // Both surface the same newest-first ordering for the page the user actually sees.
    expect(firstPage.map((e) => e.id)).toEqual(fullList.slice(0, PAGE).map((e) => e.id));

    // The hard numbers: the old path reads + parses all N; the new path reads only a page.
    expect(full.reads).toBe(N);
    expect(paged.reads).toBe(PAGE);
    // Ordering is stat-only in both, ~one stat per dir.
    expect(paged.stats).toBe(N);

    const reduction = (1 - paged.reads / full.reads) * 100;
    // eslint-disable-next-line no-console
    console.log(
      `\n[perf] first open @ N=${N}\n` +
        `  full scan : ${full.stats} stats + ${full.reads} reads  -> ~${projectedMs(full).toFixed(0)}ms (modeled)\n` +
        `  paginated : ${paged.stats} stats + ${paged.reads} reads -> ~${projectedMs(paged).toFixed(0)}ms (modeled)\n` +
        `  reads cut by ${reduction.toFixed(1)}%`,
    );
    expect(reduction).toBeGreaterThan(95);
  });

  it("steady state: repeated opens hit the mtime cache for zero reads", () => {
    const c: Counters = { stats: 0, reads: 0 };
    const fs = buildStore(N, c);
    const readCached = makeCachedReader(fs, overrides);

    function openCached() {
      const index = indexSessions({ fs, grokHome, cwd });
      const mtimeById = new Map(index.map((e) => [e.id, e.mtimeMs]));
      const pageIds = index.slice(0, PAGE).map((e) => e.id);
      return readCached(pageIds, mtimeById);
    }

    openCached(); // warm
    const afterWarm = { ...c };
    openCached(); // repeat — same page, unchanged mtimes
    const secondOpenReads = c.reads - afterWarm.reads;

    expect(afterWarm.reads).toBe(PAGE); // first open read the page
    expect(secondOpenReads).toBe(0); // second open: all cache hits, no reads

    // eslint-disable-next-line no-console
    console.log(
      `\n[perf] steady state @ N=${N}\n` +
        `  first open  : ${PAGE} reads (cache warm)\n` +
        `  second open : ${secondOpenReads} reads (mtime cache hit) -> only ${N} cheap stats`,
    );
  });

  it("search reads the catalog once (cache-backed), then stays read-free", () => {
    const c: Counters = { stats: 0, reads: 0 };
    const fs = buildStore(N, c);
    const readCached = makeCachedReader(fs, overrides);

    function search(query: string): SessionListEntry[] {
      const index = indexSessions({ fs, grokHome, cwd });
      const mtimeById = new Map(index.map((e) => [e.id, e.mtimeMs]));
      const all = readCached(index.map((e) => e.id), mtimeById);
      return all.filter((e) => e.displayName.toLowerCase().includes(query.toLowerCase()));
    }

    const first = search("number 4242");
    const afterFirst = c.reads;
    const second = search("number 1234"); // different query, same warmed cache
    const secondReads = c.reads - afterFirst;

    expect(first.length).toBeGreaterThan(0);
    expect(second.length).toBeGreaterThan(0);
    expect(afterFirst).toBe(N); // first search warms the whole catalog once
    expect(secondReads).toBe(0); // subsequent searches reuse the cache

    // eslint-disable-next-line no-console
    console.log(
      `\n[perf] search @ N=${N}\n` +
        `  first query  : ${afterFirst} reads (warms full catalog for complete matching)\n` +
        `  later queries: ${secondReads} reads (cache reused)`,
    );
  });

  it("real wall-clock: JSON.parse cost of full scan vs one page", () => {
    const reps = 20;
    const full: Counters = { stats: 0, reads: 0 };
    const fullFs = buildStore(N, full);
    const paged: Counters = { stats: 0, reads: 0 };
    const pagedFs = buildStore(N, paged);

    const t0 = performance.now();
    for (let i = 0; i < reps; i++) listSessions({ fs: fullFs, grokHome, cwd, overrides });
    const fullMs = (performance.now() - t0) / reps;

    const t1 = performance.now();
    for (let i = 0; i < reps; i++) openFirstPage(pagedFs, overrides);
    const pagedMs = (performance.now() - t1) / reps;

    // eslint-disable-next-line no-console
    console.log(
      `\n[perf] in-memory wall-clock @ N=${N} (avg of ${reps}, no disk latency — parse cost only)\n` +
        `  full scan : ${fullMs.toFixed(2)}ms/open\n` +
        `  paginated : ${pagedMs.toFixed(2)}ms/open\n` +
        `  speedup   : ${(fullMs / pagedMs).toFixed(1)}x`,
    );
    // Even with zero disk latency, parsing 50x fewer summaries is clearly faster.
    expect(pagedMs).toBeLessThan(fullMs);
  });
});

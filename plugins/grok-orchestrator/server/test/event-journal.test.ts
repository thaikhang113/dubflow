import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { EventJournal } from "../dist/src/event-journal.js";

test("event journal replays strictly after a cursor without duplicates", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-events-"));
  const journal = new EventJournal(root, "session-a");

  const first = await journal.append({ type: "state", summary: "created", metadata: { state: "created" } });
  const second = await journal.append({ type: "message", summary: "hello", metadata: { role: "assistant" } });
  const replay = await journal.readAfter(first.event_id);

  assert.equal(first.event_id, 1);
  assert.equal(second.event_id, 2);
  assert.deepEqual(replay.events.map((event) => event.event_id), [2]);
  assert.equal(replay.cursor, 2);
});

test("event journal long-poll wakes when a new event arrives", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-events-"));
  const journal = new EventJournal(root, "session-b");
  const waiting = journal.waitAfter(0, 1_000);

  await journal.append({ type: "tool_started", summary: "test", metadata: { tool: "terminal" } });
  const result = await waiting;

  assert.equal(result.events.length, 1);
  assert.equal(result.events[0]?.type, "tool_started");
});

test("event journal fails closed on malformed persisted events", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-events-"));
  const sessionDir = path.join(root, "sessions", "session-corrupt");
  await mkdir(sessionDir, { recursive: true });
  await writeFile(path.join(sessionDir, "events.jsonl"), "not-json\n", { mode: 0o600 });

  const journal = new EventJournal(root, "session-corrupt");
  await assert.rejects(journal.readAfter(0), /JSON/);
});

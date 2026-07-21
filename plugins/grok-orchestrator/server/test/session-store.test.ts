import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { SessionStore } from "../dist/src/session-store.js";

test("session store persists state and lists sessions newest first", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-sessions-"));
  const store = new SessionStore(root);
  const first = await store.create({
    repoRoot: "/repo/a",
    baseRef: "main",
    baseSha: "a".repeat(40),
    worktreeRoot: "/work/a",
    task: "first",
    acceptanceCriteria: ["passes"],
  });
  const second = await store.create({
    repoRoot: "/repo/b",
    baseRef: "main",
    baseSha: "b".repeat(40),
    worktreeRoot: "/work/b",
    task: "second",
    acceptanceCriteria: ["passes"],
  });

  await store.transition(first.sessionId, "running");
  const reloaded = new SessionStore(root);
  const listed = await reloaded.list();

  assert.equal((await reloaded.get(first.sessionId)).state, "running");
  assert.equal(listed[0]?.sessionId, second.sessionId);
  await assert.rejects(reloaded.transition(first.sessionId, "created"));
});

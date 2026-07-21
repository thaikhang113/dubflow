import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import test from "node:test";

import { WorktreeManager } from "../dist/src/worktree-manager.js";

const exec = promisify(execFile);

test("locks a base SHA and reports only disposable-worktree changes", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-worktree-test-"));
  const repo = path.join(root, "repo");
  await exec("git", ["init", repo]);
  await exec("git", ["-C", repo, "config", "user.email", "test@example.invalid"]);
  await exec("git", ["-C", repo, "config", "user.name", "Test"]);
  await writeFile(path.join(repo, "tracked.txt"), "before\n");
  await exec("git", ["-C", repo, "add", "tracked.txt"]);
  await exec("git", ["-C", repo, "commit", "-m", "seed"]);

  const manager = new WorktreeManager(path.join(root, "state"));
  const created = await manager.createWorktree("11111111-1111-4111-8111-111111111111", repo, "HEAD");
  assert.match(created.baseSha, /^[0-9a-f]{40}$/);
  assert.equal(await readFile(path.join(created.worktreeRoot, "tracked.txt"), "utf8"), "before\n");

  await writeFile(path.join(created.worktreeRoot, "tracked.txt"), "after\n");
  await writeFile(path.join(created.worktreeRoot, "new.txt"), "new\n");
  const diff = await manager.getDiff(created.worktreeRoot);
  assert.deepEqual(diff.files.sort(), ["new.txt", "tracked.txt"]);
  assert.match(diff.diff, /tracked\.txt/);
  assert.match(diff.diff, /new\.txt/);
  assert.match(diff.diff, /\+new/);
  assert.match(diff.stat, /1 untracked file/);
  assert.equal(diff.hasChanges, true);
});

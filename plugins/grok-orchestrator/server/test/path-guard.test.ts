import assert from "node:assert/strict";
import { mkdtemp, mkdir, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { PathGuard } from "../dist/src/path-guard.js";

test("path guard accepts files in the worktree", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-paths-"));
  await mkdir(path.join(root, "src"));
  await writeFile(path.join(root, "src", "a.ts"), "export {};\n");
  const guard = await PathGuard.create(root);

  assert.equal(await guard.assertAllowed(path.join(root, "src", "a.ts"), "read"), path.join(root, "src", "a.ts"));
});

test("path guard rejects traversal, protected files, and symlink escape", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-paths-"));
  const outside = await mkdtemp(path.join(os.tmpdir(), "grok-outside-"));
  await writeFile(path.join(outside, "outside.txt"), "outside\n");
  await symlink(outside, path.join(root, "escape"));
  const guard = await PathGuard.create(root);

  await assert.rejects(guard.assertAllowed(path.join(root, "..", path.basename(outside), "outside.txt"), "read"));
  await assert.rejects(guard.assertAllowed(path.join(root, ".env"), "write"));
  await assert.rejects(guard.assertAllowed(path.join(root, "escape", "outside.txt"), "read"));
});

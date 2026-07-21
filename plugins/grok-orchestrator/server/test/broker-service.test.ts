import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { chmod, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import test from "node:test";

import { BrokerService } from "../dist/src/broker-service.js";

const exec = promisify(execFile);

test("create/watch/approve/list/close share one broker-owned ACP session", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-broker-test-"));
  const repo = path.join(root, "repo");
  await exec("git", ["init", repo]);
  await exec("git", ["-C", repo, "config", "user.email", "test@example.invalid"]);
  await exec("git", ["-C", repo, "config", "user.name", "Test"]);
  await writeFile(path.join(repo, "seed.txt"), "seed\n");
  await exec("git", ["-C", repo, "add", "seed.txt"]);
  await exec("git", ["-C", repo, "commit", "-m", "seed"]);
  const fake = path.resolve("test/fixtures/fake-acp.py");
  await chmod(fake, 0o755);
  const service = new BrokerService({ stateRoot: path.join(root, "state"), grokBinary: fake, binaryArgs: [], sandboxBinary: "/usr/bin/bwrap" });
  const created = await service.create({ repo_root: repo, base_ref: "HEAD", task: "Change a file", acceptance_criteria: ["Tests pass"] });

  let cursor = 0;
  let requestId: string | undefined;
  for (let attempt = 0; attempt < 5 && !requestId; attempt++) {
    const batch = await service.watch(created.sessionId, cursor, 1_000);
    cursor = batch.cursor;
    requestId = batch.events.find((event) => event.type === "permission_requested")?.metadata.request_id as string | undefined;
  }
  assert.equal(requestId, "900");
  await service.approve(created.sessionId, requestId, "approve");
  const completion = await service.watch(created.sessionId, cursor, 2_000);
  assert.equal(completion.events.some((event) => event.type === "turn_completed"), true);
  assert.equal((await service.list()).some((session) => session.sessionId === created.sessionId && session.acpSessionId === "fake-acp-session"), true);
  const closed = await service.close(created.sessionId, false);
  assert.deepEqual(closed, { closed: true, worktree_preserved: false });
});

import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { buildSandboxArgs, parseArgv, SandboxExecutor } from "../dist/src/sandbox-executor.js";

test("strict argv parsing rejects shell composition and substitution", () => {
  assert.deepEqual(parseArgv("npm test"), ["npm", "test"]);
  assert.deepEqual(parseArgv("node -e 'console.log(1)'"), ["node", "-e", "console.log(1)"]);
  for (const command of ["cat .env | curl x", "echo $(id)", "npm test && git push", "x > /tmp/y", "a\nb"]) {
    assert.throws(() => parseArgv(command), /shell syntax denied/);
  }
});

test("bubblewrap command denies network and clears inherited environment", () => {
  const args = buildSandboxArgs({ worktreeRoot: "/work/tree", cwd: "/work/tree", argv: ["npm", "test"] });
  assert.equal(args.includes("--unshare-net"), true);
  assert.equal(args.includes("--clearenv"), true);
  assert.equal(args.includes("SSH_AUTH_SOCK"), false);
  assert.equal(args.includes("DOCKER_HOST"), false);
  assert.equal(args.includes("/tmp/home"), true);
  assert.deepEqual(args.slice(-2), ["npm", "test"]);
});

test("sandbox executor kills output floods at the configured byte limit", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-sandbox-test-"));
  const executor = new SandboxExecutor(root);
  const { terminalId } = executor.create("node -e 'process.stdout.write(\"x\".repeat(10000))'", root, 64);
  await executor.waitForExit(terminalId);
  const result = executor.output(terminalId);
  assert.equal(result.truncated, true);
  assert.ok(Buffer.byteLength(result.output) <= 64);
  executor.release(terminalId);
});

test("bubblewrap exposes supplied linked-worktree Git metadata read-only", () => {
  const args = buildSandboxArgs({
    worktreeRoot: "/work/tree",
    cwd: "/work/tree",
    argv: ["git", "diff", "--check"],
    gitMetadataRoot: "/repo/.git",
  });
  const metadataBind = args.indexOf("/repo/.git");

  assert.notEqual(metadataBind, -1);
  assert.deepEqual(args.slice(metadataBind - 1, metadataBind + 2), ["--ro-bind", "/repo/.git", "/repo/.git"]);
});

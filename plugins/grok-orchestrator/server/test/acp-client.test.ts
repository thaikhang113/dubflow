import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { AcpClient, DEFAULT_GROK_ARGS } from "../dist/src/acp-client.js";

test("default Grok ACP arguments disable built-in web access", () => {
  assert.deepEqual(DEFAULT_GROK_ARGS, ["--no-auto-update", "--disable-web-search", "agent", "stdio"]);
});

const fixture = path.resolve("test/fixtures/fake-acp.py");

test("streams filtered ACP events and round-trips permission decisions", async () => {
  const cwd = await mkdtemp(path.join(os.tmpdir(), "grok-acp-test-"));
  const events: Array<{ type: string; summary: string }> = [];
  const client = new AcpClient({
    binary: fixture,
    binaryArgs: [],
    cwd,
    env: { PATH: process.env.PATH ?? "/usr/bin:/bin" },
    onEvent: (event) => events.push(event),
    onPermission: async () => "allow_once",
    detached: false,
  });
  await client.start();
  const created = await client.newSession();
  assert.equal(created, "fake-acp-session");
  await client.prompt("make the requested change");
  assert.deepEqual(events.map((event) => event.type), [
    "message",
    "tool_started",
    "file_changed",
    "tool_finished",
    "tool_started",
    "tool_finished",
    "test_result",
    "turn_completed",
  ]);
  assert.equal(events.find((event) => event.type === "test_result")?.summary, "Passed: Run npm test");
  assert.equal(events.some((event) => /thought|secret/i.test(event.summary)), false);
  await client.dispose();
});

test("rejects malformed ACP JSON instead of continuing ambiguously", async () => {
  const cwd = await mkdtemp(path.join(os.tmpdir(), "grok-acp-bad-test-"));
  const client = new AcpClient({
    binary: fixture,
    binaryArgs: ["--malformed"],
    cwd,
    env: { PATH: process.env.PATH ?? "/usr/bin:/bin" },
    onEvent: () => undefined,
    onPermission: async () => "reject_once",
    detached: false,
  });
  await assert.rejects(client.start(), /malformed ACP JSON/);
  await client.dispose();
});

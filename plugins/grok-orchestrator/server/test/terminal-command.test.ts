import assert from "node:assert/strict";
import test from "node:test";

import { commandApprovalPreview, normalizeTerminalCommand } from "../dist/src/broker-service.js";

test("normalizes Grok's safe shell wrapper without executing the shell", () => {
  assert.deepEqual(normalizeTerminalCommand("/usr/bin/bash -lc 'npm test'"), {
    argv: ["npm", "test"],
    command: "npm test",
  });
});

test("rejects shell operators and unsupported shell wrappers", () => {
  assert.throws(() => normalizeTerminalCommand("/usr/bin/bash -lc 'npm test && curl example.invalid'"), /shell syntax denied/);
  assert.throws(() => normalizeTerminalCommand("/usr/bin/bash --noprofile -lc 'npm test'"), /shell wrapper denied/);
  assert.throws(() => normalizeTerminalCommand("bash"), /shell wrapper denied/);
});

test("leaves an ordinary safe command unchanged", () => {
  assert.deepEqual(normalizeTerminalCommand("npm run test"), {
    argv: ["npm", "run", "test"],
    command: "npm run test",
  });
});

test("approval preview preserves the complete ordinary command", () => {
  const command = "/repo/.venv/bin/python -m pytest -q tests/test_identity.py tests/test_runtime_douyin_flags.py";
  assert.deepEqual(commandApprovalPreview(command), { command, truncated: false });
});

test("approval preview bounds unusually long commands explicitly", () => {
  const result = commandApprovalPreview(`python -m pytest ${"x".repeat(5_000)}`);
  assert.equal(result.command.length, 4_096);
  assert.equal(result.command.endsWith("…"), true);
  assert.equal(result.truncated, true);
});

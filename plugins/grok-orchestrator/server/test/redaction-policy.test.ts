import assert from "node:assert/strict";
import test from "node:test";

import { PermissionPolicy } from "../dist/src/permission-policy.js";
import { redact } from "../dist/src/redaction.js";

test("redact removes secret-shaped fields and values recursively", () => {
  const result = redact({
    message: "Authorization: Bearer abcdefghijklmnop",
    apiKey: "super-secret-value",
    nested: { cookie: "sid=private", safe: "visible" },
  });

  assert.deepEqual(result, {
    message: "Authorization: [REDACTED]",
    apiKey: "[REDACTED]",
    nested: { cookie: "[REDACTED]", safe: "visible" },
  });
});

test("permission policy allows safe worktree access and denies protected paths", () => {
  const policy = new PermissionPolicy({
    worktreeRoot: "/tmp/session/worktree",
    allowedCommands: [["npm", "test"], ["npm", "run", "lint"]],
  });

  assert.equal(policy.classify({ type: "read", path: "/tmp/session/worktree/src/a.ts" }).decision, "allow");
  assert.equal(policy.classify({ type: "read", path: "src/a.ts" }).decision, "allow");
  assert.equal(policy.classify({ type: "read", path: "/etc/passwd" }).decision, "deny");
  assert.equal(policy.classify({ type: "write", path: "/tmp/session/worktree/.git/config" }).decision, "deny");
  assert.equal(policy.classify({ type: "read", path: "/tmp/session/worktree/.env" }).decision, "deny");
  assert.equal(policy.classify({ type: "command", argv: ["npm", "test"] }).decision, "allow");
  assert.equal(policy.classify({ type: "command", argv: ["curl", "https://example.com"] }).decision, "approval");
  assert.equal(policy.classify({ type: "command", argv: ["npm", "install"] }).decision, "approval");
  assert.equal(policy.classify({ type: "command", argv: ["git", "push"] }).decision, "deny");
  assert.equal(policy.classify({ type: "command", argv: ["systemctl", "restart", "openclaw"] }).decision, "deny");
  assert.equal(policy.classify({ type: "command", argv: ["sh", "-c", "npm test"] }).decision, "deny");
});

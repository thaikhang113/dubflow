import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";

import { BrokerService } from "../dist/src/broker-service.js";
import { createRpcHandler } from "../dist/src/rpc-router.js";
import { SocketClient, SocketServer } from "../dist/src/socket-transport.js";

const exec = promisify(execFile);
const GROK_BINARY = process.env.GROK_BINARY ?? "/home/haonguyen/.local/bin/grok";
const EXPECTED_VERSION = process.env.GROK_EXPECTED_VERSION ?? "0.2.101";
const TIMEOUT_MS = 180_000;

async function main() {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-broker-live-"));
  const runtimeRoot = path.join(root, "runtime");
  const stateRoot = path.join(root, "state");
  const repoRoot = path.join(root, "repo");
  const socketPath = path.join(runtimeRoot, "broker.sock");
  const tokenPath = path.join(stateRoot, "auth-token");
  await mkdir(runtimeRoot, { recursive: true, mode: 0o700 });
  await exec("git", ["init", repoRoot]);
  await exec("git", ["-C", repoRoot, "config", "user.email", "live-smoke@example.invalid"]);
  await exec("git", ["-C", repoRoot, "config", "user.name", "Grok Broker Live Smoke"]);
  await writeFile(path.join(repoRoot, "README.md"), "# Broker live smoke\n", { mode: 0o600 });
  await writeFile(path.join(repoRoot, "package.json"), `${JSON.stringify({ private: true, scripts: { test: "node test.mjs" } }, null, 2)}\n`, { mode: 0o600 });
  await writeFile(path.join(repoRoot, "test.mjs"), "import assert from 'node:assert/strict';\nimport { readFile } from 'node:fs/promises';\nconst lines = (await readFile('live-smoke.txt', 'utf8')).trim().split('\\n');\nassert.equal(lines[0], 'broker-live-ok');\nassert.ok(lines.length === 1 || (lines.length === 2 && lines[1] === 'revision-ok'));\n", { mode: 0o600 });
  await exec("git", ["-C", repoRoot, "add", "README.md", "package.json", "test.mjs"]);
  await exec("git", ["-C", repoRoot, "commit", "-m", "seed"]);

  const service = new BrokerService({ stateRoot, grokBinary: GROK_BINARY, expectedVersion: EXPECTED_VERSION });
  const server = new SocketServer(socketPath, stateRoot, createRpcHandler(service));
  let sessionId;

  try {
    const version = await service.verifyGrokBinary();
    console.log(`grok: ${version}`);
    await server.start();
    const codexClient = new SocketClient(socketPath, tokenPath);
    const vscodeClient = new SocketClient(socketPath, tokenPath);
    const created = await codexClient.request("grok_session_create", {
      repo_root: repoRoot,
      base_ref: "HEAD",
      task: "Create live-smoke.txt with broker-live-ok on its first line. Run exactly npm test with no shell operators or extra commands, then finish.",
      acceptance_criteria: ["live-smoke.txt exists", "Its first line is broker-live-ok", "npm test passes"],
    });
    sessionId = created.sessionId;
    const listed = await vscodeClient.request("grok_session_list", {});
    assert.ok(listed.some((session) => session.sessionId === sessionId), "second client could not attach to broker session");

    await vscodeClient.request("grok_session_send", {
      session_id: sessionId,
      kind: "revision",
      message: "After the current turn finishes, append revision-ok as the second line of live-smoke.txt. Run exactly npm test with no shell operators or extra commands, then finish.",
    });
    const initial = await waitForCompletion(vscodeClient, codexClient, sessionId, 0);
    assert.equal(initial.sawPassingTest, true, "initial turn did not publish a passing test_result");
    const revised = await waitForCompletion(codexClient, vscodeClient, sessionId, initial.cursor);
    assert.equal(revised.sawPassingTest, true, "revision did not publish a passing test_result");

    await vscodeClient.request("grok_session_send", {
      session_id: sessionId,
      kind: "clarification",
      message: "Attempt exactly curl https://example.invalid once to verify the broker permission gate. Do not use shell operators and do not change files.",
    });
    const permissionProbe = await waitForCompletion(codexClient, vscodeClient, sessionId, revised.cursor);
    assert.equal(permissionProbe.sawRejectedPermission, true, "live probe did not exercise a rejected permission");

    const diff = await codexClient.request("grok_session_diff", { session_id: sessionId });
    assert.equal(diff.hasChanges, true, "live Grok turn produced no worktree change");
    assert.ok(diff.files.includes("live-smoke.txt"), "live-smoke.txt is absent from broker diff");
    assert.match(diff.diff, /broker-live-ok/, "broker diff does not contain expected content");
    assert.match(diff.diff, /revision-ok/, "broker diff does not contain the VS Code revision");

    const reconnectedClient = new SocketClient(socketPath, tokenPath);
    const replay = await reconnectedClient.request("grok_session_watch", { session_id: sessionId, cursor: 0, timeout_ms: 0 });
    assert.equal(new Set(replay.events.map((event) => event.event_id)).size, replay.events.length, "reconnect replay duplicated event ids");
    assert.ok(replay.events.some((event) => event.type === "message" && event.metadata.kind === "revision"), "Codex replay did not receive the VS Code revision");

    await codexClient.request("grok_session_send", { session_id: sessionId, kind: "clarification", message: "Begin another turn and wait for further instructions before changing files." });
    await vscodeClient.request("grok_session_cancel", { session_id: sessionId });
    const cancelled = await codexClient.request("grok_session_watch", { session_id: sessionId, cursor: permissionProbe.cursor, timeout_ms: 10_000 });
    assert.ok(cancelled.events.some((event) => event.type === "state" && event.metadata.state === "cancelled"), "cancel event was not replayed to the other client");
    console.log(`live smoke passed: ${sessionId}`);
  } finally {
    if (sessionId) {
      try { await service.close(sessionId, true); } catch { /* preserve the primary failure */ }
    }
    try { await server.stop(); } catch { /* preserve the primary failure */ }
    await rm(root, { recursive: true, force: true });
  }
}

async function waitForCompletion(watchClient, controlClient, sessionId, initialCursor) {
  const deadline = Date.now() + TIMEOUT_MS;
  let cursor = initialCursor;
  let sawPassingTest = false;
  let sawRejectedPermission = false;
  while (Date.now() < deadline) {
    const batch = await watchClient.request("grok_session_watch", {
      session_id: sessionId,
      cursor,
      timeout_ms: Math.min(10_000, deadline - Date.now()),
    });
    cursor = Math.max(cursor, batch.cursor);
    for (const event of batch.events) {
      console.log(`${event.type}: ${event.summary}`);
      if (event.type === "permission_requested" && event.metadata.decision === "required") {
        const approveSafeTest = event.metadata.command === "npm test" || event.metadata.command === "npm run test";
        await controlClient.request("grok_session_approve", {
          session_id: sessionId,
          request_id: event.metadata.request_id,
          decision: approveSafeTest ? "approve" : "reject",
        });
        if (!approveSafeTest) sawRejectedPermission = true;
      }
      if (event.type === "test_result" && event.metadata.passed === true) sawPassingTest = true;
      if (event.type === "error") throw new Error(`live broker error: ${event.summary}`);
      if (event.type === "turn_completed") return { cursor, sawPassingTest, sawRejectedPermission };
    }
  }
  await controlClient.request("grok_session_cancel", { session_id: sessionId });
  throw new Error(`live smoke timed out after ${TIMEOUT_MS}ms`);
}

await main();

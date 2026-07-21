import assert from "node:assert/strict";
import { mkdtemp, readFile, stat } from "node:fs/promises";
import os from "node:os";
import net from "node:net";
import path from "node:path";
import test from "node:test";

import { SocketClient, SocketServer } from "../dist/src/socket-transport.js";

test("authenticates local RPC and creates 0700 state plus 0600 token/socket", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-socket-test-"));
  const stateRoot = path.join(root, "state");
  const socketPath = path.join(root, "broker.sock");
  const server = new SocketServer(socketPath, stateRoot, async (method, params) => ({ method, params }));
  await server.start();
  try {
    const client = new SocketClient(socketPath, path.join(stateRoot, "auth-token"));
    assert.deepEqual(await client.request("ping", { ok: true }), { method: "ping", params: { ok: true } });
    assert.equal((await stat(stateRoot)).mode & 0o777, 0o700);
    assert.equal((await stat(socketPath)).mode & 0o777, 0o600);
    assert.equal((await stat(path.join(stateRoot, "auth-token"))).mode & 0o777, 0o600);
    assert.match(await readFile(path.join(stateRoot, "auth-token"), "utf8"), /^[0-9a-f]{64}\n$/);
  } finally {
    await server.stop();
  }
});

test("a reset client socket does not terminate the broker", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "grok-socket-reset-test-"));
  const stateRoot = path.join(root, "state");
  const socketPath = path.join(root, "broker.sock");
  const server = new SocketServer(socketPath, stateRoot, async (method) => {
    if (method === "slow") await new Promise((resolve) => setTimeout(resolve, 25));
    return { ok: true };
  });
  await server.start();
  try {
    const token = (await readFile(path.join(stateRoot, "auth-token"), "utf8")).trim();
    await new Promise<void>((resolve, reject) => {
      const socket = net.createConnection(socketPath);
      socket.once("error", reject);
      socket.once("connect", () => {
        socket.write(`${JSON.stringify({ id: 1, token, method: "slow" })}\n`, () => socket.destroy());
        resolve();
      });
    });
    await new Promise((resolve) => setTimeout(resolve, 75));

    const client = new SocketClient(socketPath, path.join(stateRoot, "auth-token"));
    assert.deepEqual(await client.request("ping"), { ok: true });
  } finally {
    await server.stop();
  }
});

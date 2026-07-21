import { randomBytes, timingSafeEqual } from "node:crypto";
import { chmod, lstat, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import net, { type Server } from "node:net";
import path from "node:path";

const MAX_MESSAGE_BYTES = 1_000_000;

export interface RpcRequest { id: string | number; token: string; method: string; params?: unknown }
export interface RpcResponse { id: string | number; result?: unknown; error?: { code: number; message: string } }
export type RpcHandler = (method: string, params: unknown) => Promise<unknown>;

export class SocketServer {
  #socketPath: string;
  #stateRoot: string;
  #handler: RpcHandler;
  #server?: Server;
  #token = "";

  constructor(socketPath: string, stateRoot: string, handler: RpcHandler) {
    if (!path.isAbsolute(socketPath) || !path.isAbsolute(stateRoot)) throw new Error("socket and state paths must be absolute");
    this.#socketPath = socketPath;
    this.#stateRoot = stateRoot;
    this.#handler = handler;
  }

  async start(): Promise<void> {
    await mkdir(this.#stateRoot, { recursive: true, mode: 0o700 });
    await chmod(this.#stateRoot, 0o700);
    const tokenPath = path.join(this.#stateRoot, "auth-token");
    try { this.#token = (await readFile(tokenPath, "utf8")).trim(); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      this.#token = randomBytes(32).toString("hex");
      await writeFile(tokenPath, `${this.#token}\n`, { mode: 0o600, flag: "wx" });
    }
    if (!/^[0-9a-f]{64}$/.test(this.#token)) throw new Error("invalid broker auth token");
    await chmod(tokenPath, 0o600);
    try {
      const info = await lstat(this.#socketPath);
      if (!info.isSocket()) throw new Error("refusing to replace non-socket runtime path");
      await rm(this.#socketPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    this.#server = net.createServer((socket) => {
      socket.setEncoding("utf8");
      // A webview can disappear while a request is in flight (for example when
      // VS Code reloads). Connection errors belong to that client and must not
      // become an unhandled EventEmitter error that terminates the broker.
      socket.on("error", () => { socket.destroy(); });
      let buffered = "";
      socket.on("data", (chunk: string) => {
        buffered += chunk;
        if (Buffer.byteLength(buffered) > MAX_MESSAGE_BYTES) { socket.destroy(new Error("request too large")); return; }
        let newline: number;
        while ((newline = buffered.indexOf("\n")) >= 0) {
          const line = buffered.slice(0, newline);
          buffered = buffered.slice(newline + 1);
          void this.#handleLine(line).then((response) => socket.write(`${JSON.stringify(response)}\n`));
        }
      });
    });
    await new Promise<void>((resolve, reject) => {
      this.#server?.once("error", reject);
      this.#server?.listen(this.#socketPath, () => resolve());
    });
    await chmod(this.#socketPath, 0o600);
  }

  async stop(): Promise<void> {
    if (this.#server) await new Promise<void>((resolve, reject) => this.#server?.close((error) => error ? reject(error) : resolve()));
    try { await rm(this.#socketPath); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
  }

  async #handleLine(line: string): Promise<RpcResponse> {
    let request: RpcRequest;
    try { request = JSON.parse(line) as RpcRequest; }
    catch { return { id: "invalid", error: { code: -32700, message: "malformed JSON" } }; }
    if ((typeof request.id !== "string" && typeof request.id !== "number") || typeof request.method !== "string") return { id: "invalid", error: { code: -32600, message: "invalid request" } };
    if (!validToken(request.token, this.#token)) return { id: request.id, error: { code: -32001, message: "unauthorized" } };
    try { return { id: request.id, result: await this.#handler(request.method, request.params) }; }
    catch (error) { return { id: request.id, error: { code: -32000, message: (error as Error).message } }; }
  }
}

export class SocketClient {
  #socketPath: string;
  #tokenPath: string;
  #nextId = 1;

  constructor(socketPath: string, tokenPath: string) { this.#socketPath = socketPath; this.#tokenPath = tokenPath; }

  async request(method: string, params?: unknown): Promise<unknown> {
    const token = (await readFile(this.#tokenPath, "utf8")).trim();
    const id = this.#nextId++;
    return new Promise((resolve, reject) => {
      const socket = net.createConnection(this.#socketPath);
      let buffered = "";
      const timer = setTimeout(() => { socket.destroy(); reject(new Error("broker socket timed out")); }, 35_000);
      socket.setEncoding("utf8");
      socket.on("connect", () => socket.write(`${JSON.stringify({ id, token, method, params })}\n`));
      socket.on("data", (chunk: string) => {
        buffered += chunk;
        const newline = buffered.indexOf("\n");
        if (newline < 0) return;
        clearTimeout(timer);
        socket.end();
        try {
          const response = JSON.parse(buffered.slice(0, newline)) as RpcResponse;
          if (response.error) reject(new Error(response.error.message));
          else resolve(response.result);
        } catch { reject(new Error("malformed broker response")); }
      });
      socket.on("error", (error) => { clearTimeout(timer); reject(error); });
    });
  }
}

function validToken(actual: unknown, expected: string): boolean {
  if (typeof actual !== "string" || actual.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(actual), Buffer.from(expected));
}

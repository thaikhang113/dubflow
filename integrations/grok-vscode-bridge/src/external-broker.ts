import * as fs from "node:fs/promises";
import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";

const MAX_RESPONSE_BYTES = 1_000_000;

export interface BrokerEvent {
  event_id: number;
  session_id: string;
  timestamp: string;
  type: "state" | "message" | "permission_requested" | "tool_started" | "tool_finished" | "file_changed" | "test_result" | "turn_completed" | "error";
  summary: string;
  metadata: Record<string, unknown>;
}

export interface BrokerSession {
  sessionId: string;
  state: string;
  task: string;
  repoRoot: string;
  worktreeRoot: string;
  createdAt: string;
}

export function resolveBrokerRuntimeDir(
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
  uid: number | undefined = process.getuid?.(),
): string {
  const configured = env.XDG_RUNTIME_DIR;
  if (configured !== undefined) {
    if (path.isAbsolute(configured)) return configured;
    throw new Error("XDG_RUNTIME_DIR is unavailable");
  }
  if (platform === "linux" && Number.isSafeInteger(uid) && (uid as number) >= 0) {
    return path.join("/run/user", String(uid));
  }
  throw new Error("XDG_RUNTIME_DIR is unavailable");
}

export class ExternalBrokerClient {
  private nextId = 1;
  readonly socketPath: string;
  readonly tokenPath: string;

  constructor(
    env: NodeJS.ProcessEnv = process.env,
    platform: NodeJS.Platform = process.platform,
    uid: number | undefined = process.getuid?.(),
  ) {
    const runtime = resolveBrokerRuntimeDir(env, platform, uid);
    const stateBase = env.XDG_STATE_HOME ?? path.join(env.HOME ?? os.homedir(), ".local", "state");
    this.socketPath = path.join(runtime, "openclaw-grok-broker.sock");
    this.tokenPath = path.join(stateBase, "openclaw-grok-broker", "auth-token");
  }

  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const token = (await fs.readFile(this.tokenPath, "utf8")).trim();
    if (!/^[0-9a-f]{64}$/.test(token)) throw new Error("Broker authentication is unavailable");
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const socket = net.createConnection(this.socketPath);
      let buffered = "";
      const timer = setTimeout(() => { socket.destroy(); reject(new Error("Broker request timed out")); }, 35_000);
      socket.setEncoding("utf8");
      socket.on("connect", () => socket.write(`${JSON.stringify({ id, token, method, params })}\n`));
      socket.on("data", (chunk: string) => {
        buffered += chunk;
        if (Buffer.byteLength(buffered) > MAX_RESPONSE_BYTES) {
          clearTimeout(timer);
          socket.destroy();
          reject(new Error("Broker response is too large"));
          return;
        }
        const newline = buffered.indexOf("\n");
        if (newline < 0) return;
        clearTimeout(timer);
        socket.end();
        try {
          const response = JSON.parse(buffered.slice(0, newline)) as { id?: number; result?: T; error?: { message?: string } };
          if (response.id !== id) throw new Error("Broker response id mismatch");
          if (response.error) reject(new Error(response.error.message ?? "Broker error"));
          else resolve(response.result as T);
        } catch (error) { reject(error instanceof Error ? error : new Error("Malformed broker response")); }
      });
      socket.on("error", (error) => { clearTimeout(timer); reject(error); });
    });
  }
}

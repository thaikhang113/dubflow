import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";

import type { NewBrokerEvent } from "./types.js";

interface Pending { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }
type PermissionDecision = "allow_once" | "reject_once";

export const DEFAULT_GROK_ARGS = ["--no-auto-update", "--disable-web-search", "agent", "stdio"] as const;

export interface AcpClientOptions {
  binary: string;
  binaryArgs?: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
  onEvent: (event: NewBrokerEvent) => void | Promise<void>;
  onPermission: (request: AcpPermissionRequest) => Promise<PermissionDecision>;
  detached?: boolean;
  fsRead?: (filePath: string) => Promise<string>;
  fsWrite?: (filePath: string, content: string) => Promise<void>;
  terminal?: {
    create(command: string, cwd?: string, outputLimit?: number): Promise<{ terminalId: string }> | { terminalId: string };
    output(id: string): { output: string; exitStatus: { exitCode: number } | null; truncated: boolean };
    waitForExit(id: string): Promise<{ exitCode: number }>;
    kill(id: string): void;
    release(id: string): void;
    killAll(): void;
  };
}

export interface AcpPermissionRequest {
  id: string;
  title: string;
  kind: string;
  options: Array<{ optionId: string; kind: string; name: string }>;
  rawInput?: Record<string, unknown>;
}

export class AcpClient {
  #options: AcpClientOptions;
  #process?: ChildProcessWithoutNullStreams;
  #nextId = 1;
  #pending = new Map<number, Pending>();
  #lineQueue: Promise<void> = Promise.resolve();
  #failed?: Error;
  #toolTitles = new Map<string, string>();
  sessionId?: string;

  constructor(options: AcpClientOptions) {
    if (!pathIsAbsolute(options.binary)) throw new Error("Grok binary must be absolute");
    this.#options = options;
  }

  async start(): Promise<void> {
    const args = this.#options.binaryArgs ?? DEFAULT_GROK_ARGS;
    this.#process = spawn(this.#options.binary, args, {
      cwd: this.#options.cwd,
      env: this.#options.env,
      stdio: ["pipe", "pipe", "pipe"],
      detached: this.#options.detached ?? true,
    });
    this.#process.stdin.on("error", () => undefined);
    let buffered = "";
    this.#process.stdout.setEncoding("utf8");
    this.#process.stdout.on("data", (chunk: string) => {
      buffered += chunk;
      let newline: number;
      while ((newline = buffered.indexOf("\n")) >= 0) {
        const line = buffered.slice(0, newline);
        buffered = buffered.slice(newline + 1);
        this.#lineQueue = this.#lineQueue.then(() => this.#handleLine(line)).catch((error: unknown) => this.#fail(error as Error));
      }
    });
    this.#process.on("exit", (code) => this.#fail(new Error(`Grok ACP exited (${code ?? "signal"})`)));
    this.#process.on("error", (error) => this.#fail(error));
    await this.#request("initialize", {
      protocolVersion: 1,
      clientCapabilities: { fs: { readTextFile: true, writeTextFile: true }, terminal: true },
    });
  }

  async newSession(): Promise<string> {
    const result = await this.#request("session/new", { cwd: this.#options.cwd, mcpServers: [] }) as { sessionId?: unknown };
    if (typeof result.sessionId !== "string") throw new Error("ACP session/new returned no session id");
    this.sessionId = result.sessionId;
    return result.sessionId;
  }

  async prompt(message: string): Promise<void> {
    if (!this.sessionId) throw new Error("ACP session not created");
    const result = await this.#request("session/prompt", {
      sessionId: this.sessionId,
      prompt: [{ type: "text", text: message }],
    }) as { stopReason?: string };
    await this.#emit({ type: "turn_completed", summary: `Turn completed: ${result.stopReason ?? "unknown"}` });
  }

  cancel(): void {
    if (this.sessionId) this.#write({ jsonrpc: "2.0", method: "session/cancel", params: { sessionId: this.sessionId } });
    this.#options.terminal?.killAll();
  }

  async dispose(): Promise<void> {
    this.cancel();
    const child = this.#process;
    if (!child || child.exitCode !== null) return;
    if (child.pid) {
      try { process.kill(-child.pid, "SIGKILL"); } catch { child.kill("SIGKILL"); }
    }
    await new Promise<void>((resolve) => { child.once("exit", () => resolve()); setTimeout(resolve, 2_000); });
  }

  #request(method: string, params: unknown): Promise<unknown> {
    if (this.#failed) return Promise.reject(this.#failed);
    const id = this.#nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.#pending.delete(id); reject(new Error(`ACP request timed out: ${method}`)); }, method === "session/prompt" ? 1_800_000 : 30_000);
      this.#pending.set(id, { resolve, reject, timer });
      this.#write({ jsonrpc: "2.0", id, method, params });
    });
  }

  #write(message: unknown): void {
    if (!this.#process?.stdin.writable) throw new Error("Grok ACP is not writable");
    this.#process.stdin.write(`${JSON.stringify(message)}\n`);
  }

  async #handleLine(line: string): Promise<void> {
    let message: Record<string, unknown>;
    try { message = JSON.parse(line) as Record<string, unknown>; }
    catch { this.#fail(new Error("malformed ACP JSON")); return; }
    if (message.id !== undefined && message.method === undefined) {
      const pending = this.#pending.get(Number(message.id));
      if (!pending) return;
      this.#pending.delete(Number(message.id));
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(safeError(message.error)));
      else pending.resolve(message.result);
      return;
    }
    if (message.method === "session/update") {
      await this.#handleUpdate((message.params as { update?: unknown } | undefined)?.update);
      return;
    }
    if (typeof message.method === "string" && message.id !== undefined) await this.#handleServerRequest(message);
  }

  async #handleUpdate(raw: unknown): Promise<void> {
    if (!raw || typeof raw !== "object") return;
    const update = raw as Record<string, unknown>;
    const kind = update.sessionUpdate;
    if (kind === "agent_message_chunk") {
      const text = (update.content as { text?: unknown } | undefined)?.text;
      if (typeof text === "string") await this.#emit({ type: "message", summary: text });
    } else if (kind === "tool_call") {
      const title = safeSummary(update.title, "Tool started");
      if (typeof update.toolCallId === "string") this.#toolTitles.set(update.toolCallId, title);
      await this.#emit({ type: "tool_started", summary: title, metadata: safeToolMetadata(update) });
    } else if (kind === "tool_call_update") {
      const content = Array.isArray(update.content) ? update.content : [];
      for (const item of content) {
        if (item && typeof item === "object" && (item as Record<string, unknown>).type === "diff") {
          const filePath = (item as Record<string, unknown>).path;
          await this.#emit({ type: "file_changed", summary: `Changed ${typeof filePath === "string" ? filePath : "a file"}`, metadata: typeof filePath === "string" ? { path: filePath } : {} });
        }
      }
      const toolCallId = typeof update.toolCallId === "string" ? update.toolCallId : undefined;
      const currentTitle = safeSummary(update.title, toolCallId ? this.#toolTitles.get(toolCallId) ?? "Tool finished" : "Tool finished");
      if (toolCallId && looksLikeTestTool(currentTitle, update.kind)) this.#toolTitles.set(toolCallId, currentTitle);
      const rememberedTitle = toolCallId ? this.#toolTitles.get(toolCallId) : undefined;
      const title = rememberedTitle && looksLikeTestTool(rememberedTitle, update.kind) ? rememberedTitle : currentTitle;
      const metadata = safeToolMetadata(update);
      const terminalStatus = update.status === "completed" || update.status === "failed" || update.status === "cancelled";
      if (terminalStatus) {
        await this.#emit({ type: "tool_finished", summary: title, metadata });
        if (looksLikeTestTool(title, update.kind)) {
          const passed = update.status === "completed";
          await this.#emit({ type: "test_result", summary: `${passed ? "Passed" : "Failed"}: ${title}`, metadata: { tool_call_id: toolCallId, passed } });
        }
        if (toolCallId) this.#toolTitles.delete(toolCallId);
      }
    }
  }

  async #handleServerRequest(message: Record<string, unknown>): Promise<void> {
    const method = String(message.method);
    const params = (message.params ?? {}) as Record<string, unknown>;
    try {
      if (method === "session/request_permission") {
        const tool = (params.toolCall ?? {}) as Record<string, unknown>;
        const request: AcpPermissionRequest = {
          id: String(message.id),
          title: safeSummary(tool.title, "Permission requested"),
          kind: typeof tool.kind === "string" ? tool.kind : "unknown",
          options: Array.isArray(params.options) ? params.options.filter(isPermissionOption) : [],
          ...(tool.rawInput && typeof tool.rawInput === "object" ? { rawInput: tool.rawInput as Record<string, unknown> } : {}),
        };
        const decision = await this.#options.onPermission(request);
        const option = request.options.find((candidate) => candidate.kind === decision);
        if (!option) throw new Error(`ACP permission option unavailable: ${decision}`);
        this.#respond(message.id, { outcome: { outcome: "selected", optionId: option.optionId } });
      } else if (method === "fs/read_text_file") {
        if (!this.#options.fsRead || typeof params.path !== "string") throw new Error("fs read unavailable");
        this.#respond(message.id, { content: await this.#options.fsRead(params.path) });
      } else if (method === "fs/write_text_file") {
        if (!this.#options.fsWrite || typeof params.path !== "string" || typeof params.content !== "string") throw new Error("fs write unavailable");
        await this.#options.fsWrite(params.path, params.content);
        this.#respond(message.id, {});
      } else if (method === "terminal/create") {
        if (!this.#options.terminal || typeof params.command !== "string") throw new Error("terminal unavailable");
        this.#respond(message.id, await this.#options.terminal.create(params.command, typeof params.cwd === "string" ? params.cwd : undefined, typeof params.outputByteLimit === "number" ? params.outputByteLimit : undefined));
      } else if (method === "terminal/output") {
        this.#respond(message.id, this.#options.terminal?.output(String(params.terminalId)));
      } else if (method === "terminal/wait_for_exit") {
        this.#respond(message.id, await this.#options.terminal?.waitForExit(String(params.terminalId)));
      } else if (method === "terminal/kill") {
        this.#options.terminal?.kill(String(params.terminalId)); this.#respond(message.id, {});
      } else if (method === "terminal/release") {
        this.#options.terminal?.release(String(params.terminalId)); this.#respond(message.id, {});
      } else {
        this.#respond(message.id, {});
      }
    } catch (error) {
      this.#write({ jsonrpc: "2.0", id: message.id, error: { code: -32603, message: (error as Error).message } });
    }
  }

  #respond(id: unknown, result: unknown): void { this.#write({ jsonrpc: "2.0", id, result }); }
  async #emit(event: NewBrokerEvent): Promise<void> { await this.#options.onEvent(event); }

  #fail(error: Error): void {
    if (this.#failed) return;
    this.#failed = error;
    for (const [id, pending] of this.#pending) { clearTimeout(pending.timer); pending.reject(error); this.#pending.delete(id); }
    this.#process?.kill("SIGKILL");
  }
}

function pathIsAbsolute(value: string): boolean { return value.startsWith("/"); }
function safeError(value: unknown): string { return value && typeof value === "object" && typeof (value as { message?: unknown }).message === "string" ? String((value as { message: string }).message) : "ACP error"; }
function safeSummary(value: unknown, fallback: string): string { return typeof value === "string" ? value.slice(0, 500) : fallback; }
function safeToolMetadata(value: Record<string, unknown>): Record<string, unknown> { return { tool_call_id: typeof value.toolCallId === "string" ? value.toolCallId : undefined, kind: typeof value.kind === "string" ? value.kind : undefined, status: typeof value.status === "string" ? value.status : undefined }; }
function looksLikeTestTool(title: string, kind: unknown): boolean {
  if (kind === "edit" || kind === "read") return false;
  const normalized = title.replace(/[`'"]/g, " ");
  return /(?:^|\s)(?:npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+test|pytest|vitest|jest|mocha|cargo\s+test|go\s+test)(?:\s|$)/i.test(normalized);
}
function isPermissionOption(value: unknown): value is { optionId: string; kind: string; name: string } { if (!value || typeof value !== "object") return false; const option = value as Record<string, unknown>; return typeof option.optionId === "string" && typeof option.kind === "string" && typeof option.name === "string"; }

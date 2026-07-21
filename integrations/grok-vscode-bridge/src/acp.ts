import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { createInterface, Interface } from "node:readline";
import { EventEmitter } from "node:events";
import {
  collectToolImages,
  extractGeneratedMediaPaths,
  isMediaGenToolCall,
  extractPromptMeta,
  makeAckResponse,
  makeExitPlanResponse,
  makePermissionResponse,
  makeQuestionCancelledResponse,
  makeQuestionResponse,
  makeRequest,
  parseAcpLine,
  resolveModelId,
  routeSessionUpdate,
} from "./acp-dispatch";
import {
  PLAN_BLOCKED_CODE,
  PLAN_BLOCKED_TERMINAL_MSG,
  PLAN_BLOCKED_WRITE_MSG,
  isPlanFileWrite,
  shouldBlockTerminal,
  shouldBlockWrite,
} from "./plan-gate";
import { resolveGrokHome } from "./sessions";
import { filterAdvertisedCommands } from "./slash-filter";

export type EffortLevel = "none" | "minimal" | "low" | "medium" | "high" | "xhigh";

export type PromptContentBlock =
  | { type: "text"; text: string }
  | { type: "image"; mimeType: string; data: string };

export interface AcpClientOptions {
  cliPath: string;
  cwd: string;
  effort?: EffortLevel;
  env?: NodeJS.ProcessEnv;
  log: (msg: string) => void;
}

export interface ModelInfo {
  modelId: string;
  name: string;
  description?: string;
  totalContextTokens?: number;
}

export interface SlashCommand {
  name: string;
  description?: string;
  input?: { hint?: string };
}

export interface PromptResultMeta {
  totalTokens?: number;
  inputTokens?: number;
  outputTokens?: number;
  cachedReadTokens?: number;
  reasoningTokens?: number;
  modelId?: string;
}

export interface PermissionOption {
  optionId: string;
  kind: string; // "allow_always" | "allow_once" | "reject_once" | ...
  name: string;
}

export interface PermissionRequest {
  id: number | string;
  sessionId: string;
  toolCall: {
    toolCallId: string;
    kind: string; // "edit" | "execute" | "read" | ...
    title: string;
    rawInput?: any;
  };
  options: PermissionOption[];
}

export interface ExitPlanRequest {
  id: number | string;
  sessionId: string;
  plan: string;
}

export interface QuestionOption {
  label: string;
  description?: string;
  preview?: string;
}

export interface QuestionItem {
  question: string;
  options: QuestionOption[];
  multiSelect?: boolean;
}

export interface QuestionRequest {
  id: number | string;
  sessionId: string;
  questions: QuestionItem[];
}

export interface FsReadHandler {
  (path: string): Promise<string>;
}
export interface FsWriteHandler {
  (path: string, content: string): Promise<void>;
}
export interface TerminalHandler {
  create(params: { command: string; env?: Array<{ name: string; value: string }>; cwd?: string; outputByteLimit?: number }): { terminalId: string };
  output(terminalId: string): { output: string; exitStatus: { exitCode: number } | null; truncated: boolean };
  waitForExit(terminalId: string): Promise<{ exitCode: number }>;
  kill(terminalId: string): void;
  release(terminalId: string): void;
}

type Pending = { resolve: (v: any) => void; reject: (e: any) => void; timer?: ReturnType<typeof setTimeout> };

export function buildGrokAgentArgs(effort?: EffortLevel): string[] {
  // `--reasoning-effort` is an `agent`-level flag, so it must precede the `stdio`
  // subcommand (after `stdio` the CLI errors "unexpected argument"). Only the
  // values grok actually accepts are offered (none|minimal|low|medium|high|xhigh);
  // the bogus `max` we used to expose made grok exit with code 2 (see #3/#4).
  return effort ? ["agent", "--reasoning-effort", effort, "stdio"] : ["agent", "stdio"];
}

export class AcpClient extends EventEmitter {
  private proc?: ChildProcessWithoutNullStreams;
  private rl?: Interface;
  private nextId = 1;
  private pending = new Map<number, Pending>();

  sessionId?: string;
  currentModelId?: string;
  currentModeId?: string;
  availableModels: ModelInfo[] = [];
  availableCommands: SlashCommand[] = [];
  lastMeta?: PromptResultMeta;

  /**
   * Tool-call ids known to be media generations (`/imagine`, `/imagine-video`).
   * grok's image_gen / image_to_video tools report their output as a JSON-in-text
   * path on the *completed* update, whose title is null — so we remember the id
   * from the initial titled call to recognize the result. See
   * research/image-generation.md.
   */
  private mediaGenCallIds = new Set<string>();

  /**
   * terminalId → the command that terminal is running. The chat shows each
   * finished command's full output as the row's expandable detail (#41); the
   * snapshot is taken at `terminal/release`, when the buffer holds exactly
   * what grok itself received (same byte cap).
   */
  private terminalCommands = new Map<string, string>();

  /**
   * Client-enforced plan gate. While true, workspace file writes and mutating
   * shell commands are refused at the (mandatory) fs/terminal handlers — see
   * `plan-gate.ts`. The host toggles this; the CLI's own plan mode is advisory.
   */
  planActive = false;

  // TEST COMMENT: added to demonstrate file editing in src/acp.ts

  /** Set by the host to satisfy server→client fs requests. */
  fsRead?: FsReadHandler;
  fsWrite?: FsWriteHandler;
  /** Set by the host to satisfy server→client terminal/* requests. */
  terminal?: TerminalHandler;

  constructor(private opts: AcpClientOptions) {
    super();
  }

  async start(): Promise<void> {
    const args = buildGrokAgentArgs(this.opts.effort);

    this.opts.log(`spawning ${this.opts.cliPath} ${args.join(" ")} (cwd=${this.opts.cwd})`);
    // Node 18+ refuses to spawn .cmd/.bat without `shell: true` on Windows
    // (CVE-2024-27980). Enable shell mode for those so installs that resolve to
    // a .cmd shim (e.g. some package managers, our test fake-CLI) still work.
    const needsShell = process.platform === "win32" && /\.(cmd|bat)$/i.test(this.opts.cliPath);
    this.proc = spawn(this.opts.cliPath, args, {
      cwd: this.opts.cwd,
      env: this.opts.env ?? process.env,
      shell: needsShell,
    });

    this.rl = createInterface({ input: this.proc.stdout });
    this.rl.on("line", (line) => this.onLine(line));

    // Without an `error` listener, an async write failure on the stdin pipe
    // (EPIPE / ERR_STREAM_DESTROYED after the CLI exits) becomes an uncaught
    // exception that crashes the extension host. Swallow it here; `writeLine`
    // handles the synchronous path.
    this.proc.stdin.on("error", (err) => {
      this.opts.log(`[acp] stdin error: ${(err as Error).message}`);
    });

    this.proc.stderr.on("data", (d) => {
      const text = d.toString();
      this.opts.log(`[stderr] ${text}`);
      this.emit("stderr", text);
    });
    this.proc.on("exit", (code) => {
      this.opts.log(`grok exited with code ${code}`);
      // Drop the process handle so later writes are skipped rather than hitting
      // a destroyed pipe (`this.proc?` alone stays truthy after exit).
      this.proc = undefined;
      for (const [id, p] of this.pending) {
        this.pending.delete(id);
        if (p.timer) clearTimeout(p.timer);
        p.reject(new Error(`Grok process exited (code ${code})`));
      }
      this.emit("exit", code);
    });
    this.proc.on("error", (err) => {
      this.opts.log(`spawn error: ${err.message}`);
      this.emit("error", err);
    });

    const init = await this.request("initialize", {
      protocolVersion: 1,
      clientCapabilities: {
        fs: { readTextFile: true, writeTextFile: true },
        terminal: true,
      },
    });
    this.emit("initialized", init);
  }

  async newSession(modelId?: string): Promise<{ sessionId: string }> {
    const res = await this.request("session/new", {
      cwd: this.opts.cwd,
      mcpServers: [],
    });
    this.sessionId = res.sessionId;
    this.availableModels = (res.models?.availableModels ?? []).map((m: any) => ({
      modelId: m.modelId,
      name: m.name,
      description: m.description,
      totalContextTokens: m._meta?.totalContextTokens,
    }));
    this.currentModelId = resolveModelId(res.models?.currentModelId, this.availableModels);
    this.emit("session", res);

    if (modelId && modelId !== this.currentModelId) {
      try {
        await this.setModel(modelId);
      } catch (err) {
        this.opts.log(`[acp] Failed to set model to ${modelId}: ${(err as Error).message}. Falling back to default model ${this.currentModelId}.`);
      }
    }
    return { sessionId: res.sessionId };
  }

  async loadSession(sessionId: string, modelId?: string): Promise<{ sessionId: string }> {
    const res = await this.request("session/load", {
      sessionId,
      cwd: this.opts.cwd,
      mcpServers: [],
    });
    this.sessionId = sessionId;
    if (res?.models?.availableModels) {
      this.availableModels = res.models.availableModels.map((m: any) => ({
        modelId: m.modelId,
        name: m.name,
        description: m.description,
        totalContextTokens: m._meta?.totalContextTokens,
      }));
    }
    this.currentModelId =
      resolveModelId(res?.models?.currentModelId, this.availableModels) ?? this.currentModelId;
    this.emit("session", { sessionId, ...(res ?? {}) });
    this.emit("sessionLoaded", { sessionId });
    if (modelId && modelId !== this.currentModelId) {
      try {
        await this.setModel(modelId);
      } catch (err) {
        this.opts.log(`[acp] Failed to set model to ${modelId}: ${(err as Error).message}. Keeping ${this.currentModelId}.`);
      }
    }
    return { sessionId };
  }

  async setModel(modelId: string): Promise<void> {
    if (!this.sessionId) throw new Error("no session");
    const res = await this.request("session/set_model", {
      sessionId: this.sessionId,
      modelId,
    });
    const ok = res?._meta?.model?.Ok;
    if (ok) {
      // grok's set_model echoes a *versioned* id ("grok-build-0.1") that carries no
      // name or context size and isn't in availableModels ("grok-build"). We
      // requested a list id (the picker only ever offers list ids), so anchor to
      // that — it always resolves to a name + context window. Only if the requested
      // id somehow isn't in the list (e.g. a stale grok.defaultModel) do we fall
      // back to normalizing grok's echo.
      const requestedInList = this.availableModels.some((m) => m.modelId === modelId);
      this.currentModelId = requestedInList
        ? modelId
        : (resolveModelId(ok, this.availableModels) ?? ok);
      this.emit("modelChanged", this.currentModelId);
    }
  }

  async setMode(modeId: string): Promise<void> {
    if (!this.sessionId) throw new Error("no session");
    await this.request("session/set_mode", {
      sessionId: this.sessionId,
      modeId,
    });
    // current_mode_update will arrive as a session/update
  }

  async prompt(textOrBlocks: string | PromptContentBlock[]): Promise<PromptResultMeta> {
    if (!this.sessionId) throw new Error("no session");
    const prompt: PromptContentBlock[] =
      typeof textOrBlocks === "string"
        ? [{ type: "text", text: textOrBlocks }]
        : textOrBlocks;
    const result = await this.request("session/prompt", {
      sessionId: this.sessionId,
      prompt,
    });
    const meta = extractPromptMeta(result);
    this.lastMeta = meta;
    this.emit("promptComplete", meta);
    return meta;
  }

  async cancel(reason = "unspecified"): Promise<void> {
    if (!this.sessionId) return;
    // Log every outbound cancel with its trigger — the CLI logs the receipt
    // (`shell.cancel.received … trigger:null`) but not who asked, so when a
    // user reports "my turn died and I touched nothing" (#37) this line is
    // what attributes the cancel to a Stop click / plan verdict / nothing-of-ours.
    this.opts.log(`[cancel] sending session/cancel (${reason}) for ${this.sessionId}`);
    // ACP defines session/cancel as a notification (no id) — sending it as a
    // request causes grok-cli to ignore it. Write directly to stdin without an
    // id and don't await a response.
    this.writeLine({ jsonrpc: "2.0", method: "session/cancel", params: { sessionId: this.sessionId } });
  }

  /** Respond to a pending permission request (from the agent) with the chosen option id. */
  respondPermission(requestId: number | string, optionId: string): void {
    this.writeLine(makePermissionResponse(requestId, optionId));
  }

  /** Respond to a pending exit_plan_mode request with the user's verdict. */
  respondExitPlan(requestId: number | string, type: "approved" | "abandoned" | "rejected"): void {
    this.writeLine(makeExitPlanResponse(requestId, type));
  }

  /** Respond to a pending ask_user_question request with the user's selections. */
  respondQuestion(
    requestId: number | string,
    answers: Record<string, string>,
    annotations: Record<string, { notes?: string; preview?: string }> = {},
  ): void {
    this.writeLine(makeQuestionResponse(requestId, answers, annotations));
  }

  /** Respond to a pending ask_user_question request that the user dismissed. */
  respondQuestionCancelled(requestId: number | string): void {
    this.writeLine(makeQuestionCancelledResponse(requestId));
  }

  /**
   * Tear the process down, resolving only once it has *actually* exited — a
   * caller that must replace the binary (`grok update`) can't race a still-open
   * Windows file lock on `grok.exe`. `kill()` only signals; the OS releases the
   * lock a beat later when the process finishes tearing down. On win32 the grok
   * agent backgrounds subagent / command children that a parent-only kill would
   * orphan (and which keep the executable locked), so kill the whole tree via
   * `taskkill /T /F`. Resolves on the `exit` event, or after `timeoutMs` as a
   * fallback so a wedged process can't hang the caller forever. Fire-and-forget
   * callers can ignore the returned promise — the kill is still initiated now.
   */
  dispose(timeoutMs = 3000): Promise<void> {
    this.rl?.close();
    const proc = this.proc;
    if (!proc || proc.exitCode !== null || proc.signalCode !== null) {
      try { proc?.kill(); } catch { /* already gone */ }
      return Promise.resolve();
    }
    return new Promise<void>((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(finish, timeoutMs);
      proc.once("exit", finish);
      const fallbackKill = () => { try { proc.kill(); } catch { finish(); } };
      if (process.platform === "win32" && proc.pid !== undefined) {
        // Parent-only kill orphans grok's backgrounded children, which keep
        // grok.exe locked; `/T` kills the tree, `/F` forces it. Fall back to a
        // plain signal if taskkill can't be spawned.
        try {
          const tk = spawn("taskkill", ["/PID", String(proc.pid), "/T", "/F"]);
          tk.on("error", fallbackKill);
        } catch {
          fallbackKill();
        }
      } else {
        fallbackKill();
      }
    });
  }

  // ---------- internals ----------

  /**
   * Single gated path for every stdin write. Returns false (and never throws)
   * if the process is gone or the pipe isn't writable — the optional-chaining
   * `this.proc?` check alone is not enough, since a destroyed pipe is still
   * non-null and `write()` on it throws/emits ERR_STREAM_DESTROYED.
   */
  private writeLine(obj: unknown): boolean {
    const proc = this.proc;
    if (!proc || proc.killed || !proc.stdin.writable) return false;
    try {
      proc.stdin.write(JSON.stringify(obj) + "\n");
      return true;
    } catch (err) {
      this.opts.log(`[acp] stdin write failed: ${(err as Error).message}`);
      return false;
    }
  }

  private request(method: string, params: any): Promise<any> {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const entry: Pending = { resolve, reject };
      this.pending.set(id, entry);
      if (!this.writeLine(makeRequest(id, method, params))) {
        this.pending.delete(id);
        reject(new Error(`Grok process is not running (${method})`));
        return;
      }
      const timeoutMs = method === "session/prompt" ? 1_800_000 : 120_000;
      // Tracked on the pending entry so the response/exit paths can clear it —
      // otherwise every resolved request leaves a live timer (and its closure)
      // armed for up to 30 min.
      entry.timer = setTimeout(() => {
        if (this.pending.delete(id)) {
          reject(new Error(`ACP request timed out: ${method}`));
        }
      }, timeoutMs);
    });
  }

  private respondOk(id: number | string, result: any = {}): void {
    this.writeLine(makeAckResponse(id, result));
  }

  private respondError(id: number | string, code: number, message: string): void {
    this.writeLine({ jsonrpc: "2.0", id, error: { code, message } });
  }

  private onLine(line: string): void {
    const ev = parseAcpLine(line);
    if (!ev) return;
    if (ev.kind === "non-json") {
      this.opts.log(`[non-json] ${ev.line.slice(0, 200)}`);
      return;
    }
    if (ev.kind === "response") {
      const p = this.pending.get(ev.id as number);
      if (p) {
        this.pending.delete(ev.id as number);
        if (p.timer) clearTimeout(p.timer);
        if (ev.error) p.reject(ev.error);
        else p.resolve(ev.result);
      }
      return;
    }
    if (ev.kind === "session-update") {
      this.handleSessionUpdate(ev.update);
      return;
    }
    void this.handleServerRequest({ id: ev.id, method: ev.method, params: ev.params });
  }

  private handleSessionUpdate(u: any): void {
    const r = routeSessionUpdate(u);
    if (!r) return;
    if (r.event === "modeChanged") {
      this.currentModeId = r.modeId;
      this.emit("modeChanged", r.modeId);
      return;
    }
    if (r.event === "commandsUpdate") {
      // Hide config-mutating no-op commands (`/always-approve`) from both the
      // autocomplete and the dispatch gate at the single ingestion point (#31).
      this.availableCommands = filterAdvertisedCommands(r.commands);
      this.emit("commandsUpdate", this.availableCommands);
      return;
    }
    if (r.event === "taskBackgrounded") { this.emit("taskBackgrounded", r.payload); return; }
    if (r.event === "taskCompleted") { this.emit("taskCompleted", r.payload); return; }
    if (r.event === "messageChunk") this.emit("messageChunk", r.text);
    else if (r.event === "userMessageChunk") this.emit("userMessageChunk", r.text);
    else if (r.event === "thoughtChunk") this.emit("thoughtChunk", r.text);
    else if (r.event === "mediaContent") this.emit("mediaContent", r.media);
    else if (r.event === "toolCall") {
      this.emit("toolCall", r.payload);
      this.emitToolMedia(r.payload);
    } else if (r.event === "toolCallUpdate") {
      this.emit("toolCallUpdate", r.payload);
      this.emitToolMedia(r.payload);
    } else if (r.event === "plan") this.emit("plan", r.payload);
    else this.emit("update", r.payload);
  }

  /**
   * Emit any media carried by a tool call: ACP-standard image/resource blocks
   * (`collectToolImages`) plus grok's image_gen / image_to_video path-in-JSON
   * result, which only the flagged tool-call ids are allowed to produce.
   */
  private emitToolMedia(payload: any): void {
    const id = payload?.toolCallId;
    if (isMediaGenToolCall(payload) && typeof id === "string") this.mediaGenCallIds.add(id);
    const media = collectToolImages(payload);
    if (typeof id === "string" && this.mediaGenCallIds.has(id)) {
      media.push(...extractGeneratedMediaPaths(payload));
    }
    for (const m of media) this.emit("mediaContent", m);
  }

  private async handleServerRequest(msg: any): Promise<void> {
    const { method, id, params } = msg;
    try {
      if (method === "fs/read_text_file") {
        if (!this.fsRead) throw new Error("fsRead handler not registered");
        const content = await this.fsRead(params.path);
        this.respondOk(id, { content });
        return;
      }
      if (method === "fs/write_text_file") {
        if (!this.fsWrite) throw new Error("fsWrite handler not registered");
        // Snoop grok's own plan file so the review card can show the plan
        // (exit_plan_mode itself arrives with planContent: null).
        if (isPlanFileWrite(params.path)) {
          this.emit("planFileContent", params.content ?? "");
        }
        if (shouldBlockWrite(params.path, {
          active: this.planActive,
          workspaceRoot: this.opts.cwd,
          grokHome: resolveGrokHome(this.opts.env ?? process.env),
        })) {
          this.emit("mutationBlocked", { kind: "write", target: params.path });
          this.respondError(id, PLAN_BLOCKED_CODE, PLAN_BLOCKED_WRITE_MSG);
          return;
        }
        await this.fsWrite(params.path, params.content);
        this.respondOk(id, {});
        return;
      }
      if (method === "terminal/create") {
        if (!this.terminal) throw new Error("terminal handler not registered");
        if (shouldBlockTerminal(params.command, { active: this.planActive, workspaceRoot: this.opts.cwd })) {
          this.emit("mutationBlocked", { kind: "terminal", target: params.command });
          this.respondError(id, PLAN_BLOCKED_CODE, PLAN_BLOCKED_TERMINAL_MSG);
          return;
        }
        const created = this.terminal.create(params);
        this.terminalCommands.set(created.terminalId, params.command);
        this.respondOk(id, created);
        return;
      }
      if (method === "terminal/output") {
        if (!this.terminal) throw new Error("terminal handler not registered");
        this.respondOk(id, this.terminal.output(params.terminalId));
        return;
      }
      if (method === "terminal/wait_for_exit") {
        if (!this.terminal) throw new Error("terminal handler not registered");
        const r = await this.terminal.waitForExit(params.terminalId);
        this.respondOk(id, r);
        return;
      }
      if (method === "terminal/kill") {
        if (!this.terminal) throw new Error("terminal handler not registered");
        this.terminal.kill(params.terminalId);
        this.respondOk(id, {});
        return;
      }
      if (method === "terminal/release") {
        if (!this.terminal) throw new Error("terminal handler not registered");
        // Snapshot the finished command's output before the buffer is dropped
        // (#41) — release is the last moment it exists.
        const cmd = this.terminalCommands.get(params.terminalId);
        if (cmd !== undefined) {
          this.terminalCommands.delete(params.terminalId);
          try {
            const snap = this.terminal.output(params.terminalId);
            this.emit("commandDone", {
              command: cmd,
              output: snap.output,
              exitCode: snap.exitStatus ? snap.exitStatus.exitCode : null,
              truncated: snap.truncated,
            });
          } catch { /* terminal already gone — nothing to report */ }
        }
        this.terminal.release(params.terminalId);
        this.respondOk(id, {});
        return;
      }
      if (method === "session/request_permission") {
        const req: PermissionRequest = {
          id,
          sessionId: params.sessionId,
          toolCall: params.toolCall,
          options: params.options ?? [],
        };
        this.emit("permissionRequest", req);
        return; // response is async, host calls respondPermission()
      }
      if (
        method === "x.ai/exit_plan_mode" ||
        method === "_x.ai/exit_plan_mode"
      ) {
        const req: ExitPlanRequest = {
          id,
          sessionId: params?.sessionId ?? this.sessionId ?? "",
          plan: params?.planContent ?? params?.plan ?? params?.input?.plan ?? "",
        };
        this.emit("exitPlanRequest", req);
        return;
      }
      if (
        method === "x.ai/ask_user_question" ||
        method === "_x.ai/ask_user_question"
      ) {
        const req: QuestionRequest = {
          id,
          sessionId: params?.sessionId ?? this.sessionId ?? "",
          questions: Array.isArray(params?.questions) ? params.questions : [],
        };
        this.emit("questionRequest", req);
        return; // response is async — host calls respondQuestion()/respondQuestionCancelled()
      }
      if (
        method === "_x.ai/session_notification" ||
        method === "x.ai/session_notification"
      ) {
        this.emit("xaiNotification", params?.update);
        if (id != null) this.respondOk(id, {});
        return;
      }
      if (
        method === "_x.ai/session/prompt_complete" ||
        method === "x.ai/session/prompt_complete"
      ) {
        this.emit("xaiPromptComplete", params);
        if (id != null) this.respondOk(id, {});
        return;
      }
      if (
        method === "_x.ai/session/update" ||
        method === "x.ai/session/update"
      ) {
        // Subagent lifecycle stream (subagent_spawned / subagent_finished) —
        // carries the duration_ms + child output that Composer's completed
        // tool_call_update lacks (wire capture:
        // test/fixtures/composer-subagent-session.jsonl), and doubles as a
        // completion backstop for the card.
        this.emit("subagentLifecycle", params?.update);
        if (id != null) this.respondOk(id, {});
        return;
      }

      // unknown server request: emit + ack so the agent doesn't hang
      this.emit("serverRequest", msg);
      if (id != null) this.respondOk(id, {});
    } catch (err) {
      this.opts.log(`server request handler error (${method}): ${(err as Error).message}`);
      if (id != null) {
        this.respondError(id, -32603, (err as Error).message || "Internal error");
      }
    }
  }
}

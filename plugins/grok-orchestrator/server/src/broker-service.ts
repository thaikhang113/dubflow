import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

import { AcpClient, type AcpPermissionRequest } from "./acp-client.js";
import { EventJournal, type EventBatch } from "./event-journal.js";
import { PathGuard } from "./path-guard.js";
import { PermissionPolicy, type PermissionRequest } from "./permission-policy.js";
import { SandboxExecutor, parseArgv } from "./sandbox-executor.js";
import { SessionStore } from "./session-store.js";
import type { BrokerSession } from "./types.js";
import { WorktreeManager, type WorktreeDiff } from "./worktree-manager.js";

const exec = promisify(execFile);
const DEFAULT_COMMANDS = [["npm", "test"], ["npm", "run", "lint"], ["npm", "run", "build"], ["npm", "run", "typecheck"]];

interface PendingPermission {
  resolve: (decision: "allow_once" | "reject_once") => void;
}

interface Runtime {
  client: AcpClient;
  journal: EventJournal;
  guard: PathGuard;
  policy: PermissionPolicy;
  executor: SandboxExecutor;
  turnQueue: Promise<void>;
  pendingPermissions: Map<string, PendingPermission>;
  approvedCommands: Set<string>;
}

export interface BrokerServiceOptions {
  stateRoot: string;
  grokBinary: string;
  expectedVersion?: string;
  binaryArgs?: string[];
  sandboxBinary?: string;
}

export interface CreateInput {
  repo_root: string;
  base_ref: string;
  task: string;
  acceptance_criteria: string[];
}

export class BrokerService {
  #options: BrokerServiceOptions;
  #sessions: SessionStore;
  #worktrees: WorktreeManager;
  #runtimes = new Map<string, Runtime>();

  constructor(options: BrokerServiceOptions) {
    if (!path.isAbsolute(options.grokBinary)) throw new Error("grok binary must be absolute");
    this.#options = options;
    this.#sessions = new SessionStore(options.stateRoot);
    this.#worktrees = new WorktreeManager(options.stateRoot);
  }

  async verifyGrokBinary(): Promise<string> {
    const { stdout } = await exec(this.#options.grokBinary, ["--version"], { encoding: "utf8", env: { PATH: "/usr/local/bin:/usr/bin:/bin" } });
    const version = stdout.trim();
    if (this.#options.expectedVersion && !version.includes(this.#options.expectedVersion)) {
      throw new Error(`unexpected Grok CLI version; expected ${this.#options.expectedVersion}`);
    }
    return version;
  }

  async create(input: CreateInput): Promise<BrokerSession> {
    if (!input.task.trim()) throw new Error("task is required");
    const sessionId = randomUUID();
    const worktree = await this.#worktrees.createWorktree(sessionId, input.repo_root, input.base_ref);
    const session = await this.#sessions.create({
      sessionId,
      repoRoot: worktree.repoRoot,
      baseRef: input.base_ref,
      baseSha: worktree.baseSha,
      worktreeRoot: worktree.worktreeRoot,
      task: input.task,
      acceptanceCriteria: input.acceptance_criteria,
    });
    const runtime = await this.#startRuntime(session);
    await runtime.journal.append({ type: "state", summary: "Session running", metadata: { state: "running", base_sha: session.baseSha } });
    const prompt = formatTask(input.task, input.acceptance_criteria);
    await runtime.journal.append({ type: "message", summary: input.task, metadata: { origin: "codex", kind: "task" } });
    runtime.turnQueue = this.#runTurn(sessionId, runtime, prompt);
    return this.#sessions.get(sessionId);
  }

  async send(sessionId: string, message: string, kind: "task" | "revision" | "clarification"): Promise<{ queued: true }> {
    if (!message.trim()) throw new Error("message is required");
    const runtime = this.#requireRuntime(sessionId);
    await runtime.journal.append({ type: "message", summary: message, metadata: { origin: "client", kind } });
    runtime.turnQueue = runtime.turnQueue.catch(() => undefined).then(() => this.#runTurn(sessionId, runtime, message));
    return { queued: true };
  }

  async watch(sessionId: string, cursor = 0, timeoutMs = 0): Promise<EventBatch> {
    await this.#sessions.get(sessionId);
    const journal = this.#runtimes.get(sessionId)?.journal ?? new EventJournal(this.#options.stateRoot, sessionId);
    return journal.waitAfter(Math.max(0, cursor), Math.min(Math.max(0, timeoutMs), 30_000));
  }

  async approve(sessionId: string, requestId: string, decision: "approve" | "reject"): Promise<{ resolved: true }> {
    const runtime = this.#requireRuntime(sessionId);
    const pending = runtime.pendingPermissions.get(requestId);
    if (!pending) throw new Error("permission request is not pending");
    runtime.pendingPermissions.delete(requestId);
    pending.resolve(decision === "approve" ? "allow_once" : "reject_once");
    await this.#sessions.update(sessionId, { state: "running", activePermissionRequestId: undefined });
    await runtime.journal.append({ type: "state", summary: `Permission ${decision === "approve" ? "approved" : "rejected"}`, metadata: { request_id: requestId, state: "running" } });
    return { resolved: true };
  }

  async diff(sessionId: string): Promise<WorktreeDiff> {
    const session = await this.#sessions.get(sessionId);
    return this.#worktrees.getDiff(session.worktreeRoot);
  }

  async cancel(sessionId: string): Promise<{ cancelled: true }> {
    const runtime = this.#requireRuntime(sessionId);
    runtime.client.cancel();
    for (const pending of runtime.pendingPermissions.values()) pending.resolve("reject_once");
    runtime.pendingPermissions.clear();
    await this.#sessions.update(sessionId, { state: "cancelled", activePermissionRequestId: undefined });
    await runtime.journal.append({ type: "state", summary: "Session cancelled", metadata: { state: "cancelled" } });
    return { cancelled: true };
  }

  async close(sessionId: string, preserveWorktree?: boolean): Promise<{ closed: true; worktree_preserved: boolean }> {
    const session = await this.#sessions.get(sessionId);
    const runtime = this.#runtimes.get(sessionId);
    if (runtime) { await runtime.client.dispose(); this.#runtimes.delete(sessionId); }
    const changes = await this.#worktrees.getDiff(session.worktreeRoot);
    const preserve = preserveWorktree ?? changes.hasChanges;
    if (!preserve) await this.#worktrees.removeWorktree(session.repoRoot, session.worktreeRoot);
    await this.#sessions.update(sessionId, { state: "closed", activePermissionRequestId: undefined });
    return { closed: true, worktree_preserved: preserve };
  }

  async list(): Promise<BrokerSession[]> { return this.#sessions.list(); }

  async #startRuntime(session: BrokerSession): Promise<Runtime> {
    const journal = new EventJournal(this.#options.stateRoot, session.sessionId);
    const guard = await PathGuard.create(session.worktreeRoot);
    const policy = new PermissionPolicy({ worktreeRoot: session.worktreeRoot, allowedCommands: DEFAULT_COMMANDS });
    const executor = new SandboxExecutor(
      session.worktreeRoot,
      this.#options.sandboxBinary,
      undefined,
      path.join(session.repoRoot, ".git"),
    );
    const pendingPermissions = new Map<string, PendingPermission>();
    const approvedCommands = new Set<string>();
    let runtime: Runtime;
    const client = new AcpClient({
      binary: this.#options.grokBinary,
      ...(this.#options.binaryArgs ? { binaryArgs: this.#options.binaryArgs } : {}),
      cwd: session.worktreeRoot,
      env: cleanCredentialEnvironment(),
      onEvent: (event) => journal.append(event).then(() => undefined),
      onPermission: (request) => this.#handlePermission(session.sessionId, journal, policy, pendingPermissions, approvedCommands, request),
      fsRead: async (filePath) => readFile(await guard.assertAllowed(resolveAcpPath(session.worktreeRoot, filePath), "read"), "utf8"),
      fsWrite: async (filePath, content) => writeFile(await guard.assertAllowed(resolveAcpPath(session.worktreeRoot, filePath), "write"), content, { mode: 0o600 }),
      terminal: {
        create: async (command, cwd, outputLimit) => {
          let normalized: ReturnType<typeof normalizeTerminalCommand>;
          try {
            normalized = normalizeTerminalCommand(command);
          } catch (error) {
            const reason = (error as Error).message;
            await journal.append({ type: "permission_requested", summary: "Denied command: unsafe shell wrapper", metadata: { decision: "deny", reason } });
            throw error;
          }
          const { argv } = normalized;
          const classification = policy.classify({ type: "command", argv });
          const key = JSON.stringify(argv);
          const preview = commandApprovalPreview(normalized.command);
          const summaryPreview = commandApprovalPreview(normalized.command, 240).command;
          if (classification.decision === "deny") {
            await journal.append({
              type: "permission_requested",
              summary: `Denied command: ${summaryPreview}`,
              metadata: { decision: "deny", reason: classification.reason, command: preview.command, command_truncated: preview.truncated },
            });
            throw new Error(`command denied: ${classification.reason}`);
          }
          if (classification.decision !== "allow" && !approvedCommands.delete(key)) {
            const requestId = `terminal-${randomUUID()}`;
            await this.#sessions.update(session.sessionId, { state: "waiting_permission", activePermissionRequestId: requestId });
            await journal.append({
              type: "permission_requested",
              summary: `Command needs approval: ${summaryPreview}`,
              metadata: {
                request_id: requestId,
                kind: "command",
                decision: "required",
                reason: classification.reason,
                command: preview.command,
                command_truncated: preview.truncated,
              },
            });
            const decision = await new Promise<"allow_once" | "reject_once">((resolve) => pendingPermissions.set(requestId, { resolve }));
            if (decision !== "allow_once") throw new Error("command permission rejected");
          }
          return executor.create(normalized.command, cwd, outputLimit);
        },
        output: (id) => executor.output(id),
        waitForExit: (id) => executor.waitForExit(id),
        kill: (id) => executor.kill(id),
        release: (id) => executor.release(id),
        killAll: () => executor.killAll(),
      },
    });
    runtime = { client, journal, guard, policy, executor, turnQueue: Promise.resolve(), pendingPermissions, approvedCommands };
    this.#runtimes.set(session.sessionId, runtime);
    await this.#sessions.transition(session.sessionId, "starting");
    try {
      await client.start();
      const acpSessionId = await client.newSession();
      await this.#sessions.update(session.sessionId, { state: "running", acpSessionId });
      return runtime;
    } catch (error) {
      this.#runtimes.delete(session.sessionId);
      await this.#sessions.update(session.sessionId, { state: "error" });
      await journal.append({ type: "error", summary: (error as Error).message });
      await client.dispose();
      throw error;
    }
  }

  async #runTurn(sessionId: string, runtime: Runtime, prompt: string): Promise<void> {
    await this.#sessions.update(sessionId, { state: "running" });
    try { await runtime.client.prompt(prompt); }
    catch (error) {
      await this.#sessions.update(sessionId, { state: "error" });
      await runtime.journal.append({ type: "error", summary: (error as Error).message });
    }
  }

  async #handlePermission(sessionId: string, journal: EventJournal, policy: PermissionPolicy, pending: Map<string, PendingPermission>, approvedCommands: Set<string>, request: AcpPermissionRequest): Promise<"allow_once" | "reject_once"> {
    const classified = classifyAcpPermission(policy, request);
    if (classified?.decision === "deny") {
      await journal.append({ type: "permission_requested", summary: `Denied: ${request.title}`, metadata: { request_id: request.id, decision: "deny", reason: classified.reason } });
      return "reject_once";
    }
    if (classified?.decision === "allow") return "allow_once";
    await this.#sessions.update(sessionId, { state: "waiting_permission", activePermissionRequestId: request.id });
    await journal.append({ type: "permission_requested", summary: request.title, metadata: { request_id: request.id, kind: request.kind, decision: "required" } });
    const commandKey = permissionCommandKey(request);
    return new Promise((resolve) => pending.set(request.id, { resolve: (decision) => {
      if (decision === "allow_once" && commandKey) approvedCommands.add(commandKey);
      resolve(decision);
    } }));
  }

  #requireRuntime(sessionId: string): Runtime {
    const runtime = this.#runtimes.get(sessionId);
    if (!runtime) throw new Error("session is not active in this broker process");
    return runtime;
  }
}

function formatTask(task: string, criteria: string[]): string { return criteria.length ? `${task}\n\nAcceptance criteria:\n${criteria.map((item) => `- ${item}`).join("\n")}` : task; }
function resolveAcpPath(root: string, filePath: string): string { return path.isAbsolute(filePath) ? filePath : path.join(root, filePath); }
export function normalizeTerminalCommand(command: string): { argv: string[]; command: string } {
  const outerArgv = parseArgv(command);
  const shell = path.basename(outerArgv[0] ?? "");
  if (!new Set(["bash", "sh", "zsh"]).has(shell)) return { argv: outerArgv, command };
  if (outerArgv.length !== 3 || (outerArgv[1] !== "-c" && outerArgv[1] !== "-lc")) {
    throw new Error("shell wrapper denied");
  }
  const innerCommand = outerArgv[2] ?? "";
  return { argv: parseArgv(innerCommand), command: innerCommand };
}
export function commandApprovalPreview(command: string, maxLength = 4_096): { command: string; truncated: boolean } {
  if (command.length <= maxLength) return { command, truncated: false };
  return { command: `${command.slice(0, maxLength - 1)}…`, truncated: true };
}
function cleanCredentialEnvironment(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { PATH: "/usr/local/bin:/usr/bin:/bin", HOME: process.env.HOME, XDG_CONFIG_HOME: process.env.XDG_CONFIG_HOME, XDG_DATA_HOME: process.env.XDG_DATA_HOME };
  return Object.fromEntries(Object.entries(env).filter((entry): entry is [string, string] => typeof entry[1] === "string"));
}
function classifyAcpPermission(policy: PermissionPolicy, request: AcpPermissionRequest): ReturnType<PermissionPolicy["classify"]> | undefined {
  const raw = request.rawInput;
  if (!raw) return undefined;
  if (typeof raw.path === "string") return policy.classify({ type: request.kind === "read" ? "read" : "write", path: raw.path });
  if (typeof raw.command === "string") {
    try { return policy.classify({ type: "command", argv: parseArgv(raw.command), network: Boolean(raw.network) }); }
    catch { return { decision: "deny", reason: "shell_syntax" }; }
  }
  if (Array.isArray(raw.argv) && raw.argv.every((value) => typeof value === "string")) return policy.classify({ type: "command", argv: raw.argv as string[], network: Boolean(raw.network) });
  return undefined;
}
function permissionCommandKey(request: AcpPermissionRequest): string | undefined {
  const raw = request.rawInput;
  if (typeof raw?.command === "string") { try { return JSON.stringify(parseArgv(raw.command)); } catch { return undefined; } }
  if (Array.isArray(raw?.argv) && raw.argv.every((value) => typeof value === "string")) return JSON.stringify(raw.argv);
  return undefined;
}

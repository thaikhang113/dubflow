import { randomUUID } from "node:crypto";
import { chmod, mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";

import type { BrokerSession, CreateSessionRecord, SessionState } from "./types.js";

const TRANSITIONS: Record<SessionState, ReadonlySet<SessionState>> = {
  created: new Set(["starting", "running", "cancelled", "error", "closed"]),
  starting: new Set(["running", "waiting_permission", "cancelled", "error"]),
  running: new Set(["waiting_permission", "completed", "cancelled", "error"]),
  waiting_permission: new Set(["running", "cancelled", "error"]),
  completed: new Set(["running", "closed"]),
  cancelled: new Set(["running", "closed"]),
  error: new Set(["running", "closed"]),
  closed: new Set(),
};

export class SessionStore {
  #root: string;
  #lastCreatedMs = 0;

  constructor(stateRoot: string) {
    this.#root = path.join(stateRoot, "sessions");
  }

  async create(input: CreateSessionRecord): Promise<BrokerSession> {
    await mkdir(this.#root, { recursive: true, mode: 0o700 });
    const nowMs = Math.max(Date.now(), this.#lastCreatedMs + 1);
    this.#lastCreatedMs = nowMs;
    const now = new Date(nowMs).toISOString();
    const session: BrokerSession = {
      sessionId: input.sessionId ?? randomUUID(),
      ...input,
      state: "created",
      createdAt: now,
      updatedAt: now,
    };
    await this.#write(session);
    return session;
  }

  async get(sessionId: string): Promise<BrokerSession> {
    if (!/^[0-9a-f-]{36}$/i.test(sessionId)) throw new Error("invalid session id");
    return JSON.parse(await readFile(this.#path(sessionId), "utf8")) as BrokerSession;
  }

  async list(): Promise<BrokerSession[]> {
    await mkdir(this.#root, { recursive: true, mode: 0o700 });
    const entries = await readdir(this.#root, { withFileTypes: true });
    const sessions = await Promise.all(
      entries.filter((entry) => entry.isDirectory()).map((entry) => this.get(entry.name)),
    );
    return sessions.sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  }

  async transition(sessionId: string, state: SessionState): Promise<BrokerSession> {
    const session = await this.get(sessionId);
    if (!TRANSITIONS[session.state].has(state)) throw new Error(`invalid transition ${session.state} -> ${state}`);
    return this.update(sessionId, { state });
  }

  async update(sessionId: string, patch: Partial<Pick<BrokerSession, "state" | "acpSessionId">> & { activePermissionRequestId?: string | undefined }): Promise<BrokerSession> {
    const current = await this.get(sessionId);
    const { activePermissionRequestId, ...definedPatch } = patch;
    const updated: BrokerSession = { ...current, ...definedPatch, updatedAt: new Date().toISOString() };
    if ("activePermissionRequestId" in patch) {
      if (activePermissionRequestId === undefined) delete updated.activePermissionRequestId;
      else updated.activePermissionRequestId = activePermissionRequestId;
    }
    await this.#write(updated);
    return updated;
  }

  #path(sessionId: string): string {
    return path.join(this.#root, sessionId, "session.json");
  }

  async #write(session: BrokerSession): Promise<void> {
    const filePath = this.#path(session.sessionId);
    await mkdir(path.dirname(filePath), { recursive: true, mode: 0o700 });
    const temporary = `${filePath}.${process.pid}.tmp`;
    await writeFile(temporary, `${JSON.stringify(session, null, 2)}\n`, { mode: 0o600 });
    await chmod(temporary, 0o600);
    await rename(temporary, filePath);
  }
}

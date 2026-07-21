import { appendFile, chmod, mkdir, readFile } from "node:fs/promises";
import path from "node:path";

import { redact } from "./redaction.js";
import type { BrokerEvent, NewBrokerEvent } from "./types.js";

export interface EventBatch {
  events: BrokerEvent[];
  cursor: number;
}

export class EventJournal {
  #sessionId: string;
  #filePath: string;
  #nextId = 1;
  #ready: Promise<void>;
  #writeQueue: Promise<void> = Promise.resolve();
  #waiters = new Set<() => void>();

  constructor(stateRoot: string, sessionId: string) {
    this.#sessionId = sessionId;
    this.#filePath = path.join(stateRoot, "sessions", sessionId, "events.jsonl");
    this.#ready = this.#initialize();
  }

  async #initialize(): Promise<void> {
    await mkdir(path.dirname(this.#filePath), { recursive: true, mode: 0o700 });
    try {
      const existing = await this.#readAll();
      this.#nextId = (existing.at(-1)?.event_id ?? 0) + 1;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      await appendFile(this.#filePath, "", { mode: 0o600 });
    }
    await chmod(this.#filePath, 0o600);
  }

  async append(input: NewBrokerEvent): Promise<BrokerEvent> {
    await this.#ready;
    let created: BrokerEvent | undefined;
    this.#writeQueue = this.#writeQueue.then(async () => {
      created = {
        event_id: this.#nextId++,
        session_id: this.#sessionId,
        timestamp: new Date().toISOString(),
        type: input.type,
        summary: String(redact(input.summary)),
        metadata: redact(input.metadata ?? {}) as Record<string, unknown>,
      };
      await appendFile(this.#filePath, `${JSON.stringify(created)}\n`, { mode: 0o600 });
    });
    await this.#writeQueue;
    for (const wake of this.#waiters) wake();
    this.#waiters.clear();
    if (!created) throw new Error("event append failed");
    return created;
  }

  async readAfter(cursor: number): Promise<EventBatch> {
    await this.#ready;
    await this.#writeQueue;
    const events = (await this.#readAll()).filter((event) => event.event_id > cursor);
    return { events, cursor: events.at(-1)?.event_id ?? cursor };
  }

  async waitAfter(cursor: number, timeoutMs: number): Promise<EventBatch> {
    const existing = await this.readAfter(cursor);
    if (existing.events.length > 0 || timeoutMs <= 0) return existing;
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        this.#waiters.delete(wake);
        resolve();
      }, Math.min(timeoutMs, 30_000));
      const wake = (): void => {
        clearTimeout(timer);
        resolve();
      };
      this.#waiters.add(wake);
    });
    return this.readAfter(cursor);
  }

  async #readAll(): Promise<BrokerEvent[]> {
    const content = await readFile(this.#filePath, "utf8");
    return content
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as BrokerEvent);
  }
}

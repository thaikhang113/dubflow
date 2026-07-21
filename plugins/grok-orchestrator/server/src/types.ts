export const EVENT_TYPES = [
  "state",
  "message",
  "permission_requested",
  "tool_started",
  "tool_finished",
  "file_changed",
  "test_result",
  "turn_completed",
  "error",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export interface BrokerEvent {
  event_id: number;
  session_id: string;
  timestamp: string;
  type: EventType;
  summary: string;
  metadata: Record<string, unknown>;
}

export interface NewBrokerEvent {
  type: EventType;
  summary: string;
  metadata?: Record<string, unknown>;
}

export type SessionState =
  | "created"
  | "starting"
  | "running"
  | "waiting_permission"
  | "completed"
  | "cancelled"
  | "error"
  | "closed";

export interface BrokerSession {
  sessionId: string;
  repoRoot: string;
  baseRef: string;
  baseSha: string;
  worktreeRoot: string;
  task: string;
  acceptanceCriteria: string[];
  state: SessionState;
  createdAt: string;
  updatedAt: string;
  acpSessionId?: string;
  activePermissionRequestId?: string;
}

export interface CreateSessionRecord {
  sessionId?: string;
  repoRoot: string;
  baseRef: string;
  baseSha: string;
  worktreeRoot: string;
  task: string;
  acceptanceCriteria: string[];
}

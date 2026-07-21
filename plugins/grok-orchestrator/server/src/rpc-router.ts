import type { BrokerService } from "./broker-service.js";

export function createRpcHandler(service: BrokerService): (method: string, params: unknown) => Promise<unknown> {
  return async (method, raw) => {
    const params = objectParams(raw);
    switch (method) {
      case "grok_session_create":
        return service.create({ repo_root: stringParam(params, "repo_root"), base_ref: stringParam(params, "base_ref"), task: stringParam(params, "task"), acceptance_criteria: stringArray(params, "acceptance_criteria") });
      case "grok_session_send":
        return service.send(stringParam(params, "session_id"), stringParam(params, "message"), enumParam(params, "kind", ["task", "revision", "clarification"]));
      case "grok_session_watch":
        return service.watch(stringParam(params, "session_id"), numberParam(params, "cursor", 0), numberParam(params, "timeout_ms", 0));
      case "grok_session_approve":
        return service.approve(stringParam(params, "session_id"), stringParam(params, "request_id"), enumParam(params, "decision", ["approve", "reject"]));
      case "grok_session_diff": return service.diff(stringParam(params, "session_id"));
      case "grok_session_cancel": return service.cancel(stringParam(params, "session_id"));
      case "grok_session_close": return service.close(stringParam(params, "session_id"), optionalBoolean(params, "preserve_worktree"));
      case "grok_session_list": return service.list();
      default: throw new Error("unknown broker method");
    }
  };
}

function objectParams(value: unknown): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("params must be an object"); return value as Record<string, unknown>; }
function stringParam(value: Record<string, unknown>, key: string): string { if (typeof value[key] !== "string") throw new Error(`${key} must be a string`); return value[key]; }
function stringArray(value: Record<string, unknown>, key: string): string[] { if (!Array.isArray(value[key]) || !(value[key] as unknown[]).every((item) => typeof item === "string")) throw new Error(`${key} must be a string array`); return value[key] as string[]; }
function numberParam(value: Record<string, unknown>, key: string, fallback: number): number { if (value[key] === undefined) return fallback; if (typeof value[key] !== "number" || !Number.isFinite(value[key])) throw new Error(`${key} must be a number`); return value[key]; }
function optionalBoolean(value: Record<string, unknown>, key: string): boolean | undefined { if (value[key] === undefined) return undefined; if (typeof value[key] !== "boolean") throw new Error(`${key} must be a boolean`); return value[key]; }
function enumParam<const T extends string>(value: Record<string, unknown>, key: string, choices: readonly T[]): T { const result = stringParam(value, key); if (!choices.includes(result as T)) throw new Error(`${key} is invalid`); return result as T; }

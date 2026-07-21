import { runtimePaths } from "./runtime-paths.js";
import { SocketClient } from "./socket-transport.js";

const paths = runtimePaths();
const client = new SocketClient(paths.socketPath, paths.tokenPath);
let buffered = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk: string) => {
  buffered += chunk;
  let newline: number;
  while ((newline = buffered.indexOf("\n")) >= 0) {
    const line = buffered.slice(0, newline);
    buffered = buffered.slice(newline + 1);
    void handle(line);
  }
});
process.stdin.resume();

async function handle(line: string): Promise<void> {
  let request: { jsonrpc?: string; id?: string | number; method?: string; params?: Record<string, unknown> };
  try { request = JSON.parse(line) as typeof request; }
  catch { write({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }); return; }
  if (request.id === undefined) return;
  if (request.method === "initialize") {
    write({ jsonrpc: "2.0", id: request.id, result: { protocolVersion: "2025-03-26", capabilities: { tools: { listChanged: false } }, serverInfo: { name: "grok-orchestrator", version: "0.1.0" } } });
  } else if (request.method === "tools/list") {
    write({ jsonrpc: "2.0", id: request.id, result: { tools: TOOLS } });
  } else if (request.method === "tools/call") {
    const name = request.params?.name;
    if (typeof name !== "string") { writeError(request.id, -32602, "tool name is required"); return; }
    try {
      const result = await client.request(name, request.params?.arguments ?? {});
      write({ jsonrpc: "2.0", id: request.id, result: { content: [{ type: "text", text: JSON.stringify(result) }], structuredContent: result } });
    } catch (error) {
      write({ jsonrpc: "2.0", id: request.id, result: { isError: true, content: [{ type: "text", text: (error as Error).message }] } });
    }
  } else writeError(request.id, -32601, "Method not found");
}

function write(value: unknown): void { process.stdout.write(`${JSON.stringify(value)}\n`); }
function writeError(id: string | number, code: number, message: string): void { write({ jsonrpc: "2.0", id, error: { code, message } }); }

const sessionId = { type: "string", description: "Broker session UUID" };
const TOOLS = [
  tool("grok_session_create", "Create an isolated Grok worktree session", { repo_root: { type: "string" }, base_ref: { type: "string" }, task: { type: "string" }, acceptance_criteria: { type: "array", items: { type: "string" } } }, ["repo_root", "base_ref", "task", "acceptance_criteria"], false),
  tool("grok_session_send", "Send a task, revision, or clarification", { session_id: sessionId, message: { type: "string" }, kind: { type: "string", enum: ["task", "revision", "clarification"] } }, ["session_id", "message", "kind"], false),
  tool("grok_session_watch", "Long-poll filtered session events", { session_id: sessionId, cursor: { type: "number", minimum: 0 }, timeout_ms: { type: "number", minimum: 0, maximum: 30000 } }, ["session_id"], true),
  tool("grok_session_approve", "Resolve one pending permission", { session_id: sessionId, request_id: { type: "string" }, decision: { type: "string", enum: ["approve", "reject"] } }, ["session_id", "request_id", "decision"], false),
  tool("grok_session_diff", "Read bounded worktree diff and file list", { session_id: sessionId }, ["session_id"], true),
  tool("grok_session_cancel", "Cancel the active turn and its process tree", { session_id: sessionId }, ["session_id"], false, true),
  tool("grok_session_close", "Close a session without applying its patch", { session_id: sessionId, preserve_worktree: { type: "boolean" } }, ["session_id"], false, true),
  tool("grok_session_list", "List broker sessions for reattachment", {}, [], true),
];
function tool(name: string, description: string, properties: Record<string, unknown>, required: string[], readOnly: boolean, destructive = false): unknown { return { name, description, inputSchema: { type: "object", properties, required, additionalProperties: false }, annotations: { readOnlyHint: readOnly, destructiveHint: destructive, idempotentHint: readOnly, openWorldHint: false } }; }

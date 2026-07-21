// Edit-diff wire probe for `grok agent stdio` (issue #45).
// Q1: when grok performs a file EDIT, does the tool_call/tool_call_update carry a
//     `type:"diff"` content block (with oldText/newText) the webview can render?
// Q2: does grok ALSO narrate a ```diff fenced block in agent_message_chunk text
//     (the renderDiffCode inline path)?
// Q3: does any of this change under AUTO-APPROVE (session/set_mode "yolo") vs the
//     Agent permission flow? -> the #45 core claim.
// Run: node <this> [--yolo]   (needs a logged-in grok; burns credits)
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

const GROK = process.env.GROK_BIN ||
  path.join(os.homedir(), ".grok", "bin", process.platform === "win32" ? "grok.exe" : "grok");
const YOLO = process.argv.includes("--yolo");
function log(s) { process.stderr.write("[exp] " + s + "\n"); }

const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "grok-editdiff-"));
const FILE = path.join(cwd, "note.txt");
fs.writeFileSync(FILE, "The quick brown alpha jumps over the lazy dog.\nSecond line stays.\n");
// GROK_SUPPORT_PERM=true|false writes a PROJECT-level .grok/config.toml in this
// throwaway cwd (never touches the user's global ~/.grok/config.toml) so we can
// test whether [features] support_permission gates session/request_permission.
const SUPPORT_PERM = process.env.GROK_SUPPORT_PERM; // "true" | "false" | undefined
if (SUPPORT_PERM != null) {
  fs.mkdirSync(path.join(cwd, ".grok"), { recursive: true });
  fs.writeFileSync(path.join(cwd, ".grok", "config.toml"),
    `[features]\nsupport_permission = ${SUPPORT_PERM}\n`);
}
log("grok: " + GROK);
log("cwd: " + cwd + "   mode: " + (YOLO ? "AUTO-APPROVE (yolo)" : "AGENT (permission)") +
    "   project support_permission=" + (SUPPORT_PERM ?? "(inherit global)"));

const proc = spawn(GROK, ["agent", "--reasoning-effort", "low", "stdio"], { cwd, env: process.env });
let nextId = 1;
const waiters = new Map();
function send(method, params) {
  const id = nextId++;
  proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  return new Promise((res) => waiters.set(id, res));
}
function respond(id, result) {
  proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, result }) + "\n");
}
proc.stderr.on("data", (d) => process.stderr.write("[grok-stderr] " + d.toString()));
proc.on("exit", (code) => log("grok exited: " + code));

let assembled = "";
let permissionAsked = 0;
const toolEvents = [];    // every tool_call / tool_call_update, verbatim
const seenUpdateKinds = {};
const rl = readline.createInterface({ input: proc.stdout });
rl.on("line", (line) => {
  if (!line.trim()) return;
  let msg;
  try { msg = JSON.parse(line); } catch { log("non-json: " + line.slice(0, 160)); return; }

  // Server -> client REQUESTS (have both method and id)
  if (msg.method && msg.id != null) {
    const m = msg.method;
    if (m === "fs/read_text_file") {
      let content = ""; try { content = fs.readFileSync(msg.params.path, "utf8"); } catch {}
      respond(msg.id, { content });
    } else if (m === "fs/write_text_file") {
      try { fs.writeFileSync(msg.params.path, msg.params.content); } catch {}
      respond(msg.id, {});
    } else if (m === "session/request_permission") {
      permissionAsked++;
      log("PERMISSION asked -> toolCall.kind=" + JSON.stringify(msg.params?.toolCall?.kind) +
          " title=" + JSON.stringify(msg.params?.toolCall?.title));
      // capture the toolCall shape delivered WITH the permission request
      toolEvents.push({ src: "request_permission.toolCall", data: msg.params?.toolCall });
      const opts = msg.params?.options || [];
      const allow = opts.find((o) => o.kind === "allow_once") || opts.find((o) => o.kind === "allow_always") || opts[0];
      respond(msg.id, { outcome: { outcome: "selected", optionId: allow?.optionId } });
    } else if (m === "terminal/create") respond(msg.id, { terminalId: "t1" });
    else if (m === "terminal/output") respond(msg.id, { output: "", exitStatus: { exitCode: 0 }, truncated: false });
    else if (m === "terminal/wait_for_exit") respond(msg.id, { exitCode: 0 });
    else if (m.startsWith("terminal/")) respond(msg.id, {});
    else { log("REQ (other) " + m); respond(msg.id, {}); }
    return;
  }

  // session/update NOTIFICATIONS
  if (msg.method === "session/update") {
    const u = msg.params && msg.params.update;
    if (!u) return;
    const kind = u.sessionUpdate;
    seenUpdateKinds[kind] = (seenUpdateKinds[kind] || 0) + 1;
    if (kind === "agent_message_chunk") assembled += (u.content && u.content.text) || "";
    if (kind === "tool_call" || kind === "tool_call_update") {
      toolEvents.push({ src: kind, data: u });
    }
    return;
  }

  if (msg.id != null && waiters.has(msg.id)) {
    const res = waiters.get(msg.id); waiters.delete(msg.id); res(msg);
  }
});

function summarizeContent(content) {
  if (!Array.isArray(content)) return content === undefined ? "(none)" : JSON.stringify(content);
  return content.map((c) => {
    if (c && c.type === "diff") {
      return { type: "diff", path: c.path,
        oldText: (c.oldText ?? "").slice(0, 120), newText: (c.newText ?? "").slice(0, 120),
        hasOld: c.oldText != null, hasNew: c.newText != null };
    }
    if (c && c.type === "content") return { type: "content", text: (c.content?.text ?? "").slice(0, 120) };
    return { type: c?.type, keys: c && Object.keys(c) };
  });
}

(async () => {
  const timer = setTimeout(() => { log("TIMEOUT (180s)"); dump(); proc.kill(); process.exit(2); }, 180_000);
  const init = await send("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: true, writeTextFile: true }, terminal: true },
    clientInfo: { name: "editdiff-probe", version: "0" },
  });
  const caps = init.result && init.result.agentCapabilities;
  log("promptCapabilities: " + JSON.stringify(caps && caps.promptCapabilities));

  const sess = await send("session/new", { cwd, mcpServers: [] });
  if (!sess.result) { log("session/new FAILED: " + JSON.stringify(sess.error)); proc.kill(); process.exit(1); }
  const sessionId = sess.result.sessionId;
  log("session: " + sessionId);
  log("available modes: " + JSON.stringify((sess.result.modes || sess.result.availableModes || []).map?.((m)=>m.id||m) ?? sess.result.modes));

  if (YOLO) {
    const sm = await send("session/set_mode", { sessionId, modeId: "yolo" });
    log("set_mode yolo -> " + (sm.error ? "ERR " + JSON.stringify(sm.error) : "ok " + JSON.stringify(sm.result)));
  }

  const reply = await send("session/prompt", {
    sessionId,
    prompt: [{ type: "text", text:
      "Edit the file note.txt in the current directory: change the word 'alpha' to 'beta'. " +
      "Make exactly that one edit using your file-editing tool. Do not run any shell commands." }],
  });
  clearTimeout(timer);
  log("stopReason: " + JSON.stringify(reply.result && reply.result.stopReason) + (reply.error ? "  ERR " + JSON.stringify(reply.error) : ""));
  dump();
  proc.kill();
  process.exit(0);

  function noop() {}
})().catch((e) => { log("probe error: " + e.stack || e.message); proc.kill(); process.exit(1); });

function dump() {
  const out = [];
  out.push("========== RESULT ==========");
  out.push("mode: " + (YOLO ? "AUTO-APPROVE (yolo)" : "AGENT (permission)"));
  out.push("permission requests: " + permissionAsked);
  out.push("update kinds seen: " + JSON.stringify(seenUpdateKinds));
  out.push("final file contents: " + JSON.stringify(fs.readFileSync(FILE, "utf8")));
  out.push("");
  out.push("--- agent_message text (does it contain a ```diff fence?) ---");
  out.push("contains ```diff fence: " + /```diff/i.test(assembled));
  out.push(assembled.slice(0, 1500));
  out.push("");
  out.push("--- tool events (" + toolEvents.length + ") ---");
  for (const ev of toolEvents) {
    const d = ev.data || {};
    out.push(`[${ev.src}] id=${d.toolCallId ?? d.id ?? "?"} kind=${JSON.stringify(d.kind)} status=${JSON.stringify(d.status)} title=${JSON.stringify(d.title)}`);
    out.push("    content: " + JSON.stringify(summarizeContent(d.content)));
    if (d.rawInput) out.push("    rawInput keys: " + JSON.stringify(Object.keys(d.rawInput)));
  }
  const text = out.join("\n");
  process.stderr.write("\n" + text + "\n");
  try {
    const p = path.join(__dirname, YOLO ? "edit-diff-yolo.log" : "edit-diff-agent.log");
    fs.writeFileSync(p, text + "\n\n===== FULL toolEvents JSON =====\n" + JSON.stringify(toolEvents, null, 2));
    log("wrote " + p);
  } catch (e) { log("write log failed: " + e.message); }
}

// Voice/audio capability probe for `grok agent stdio`.
// Q1: does grok advertise promptCapabilities.audio in its initialize result?
// Q2: if we send an audio content block in session/prompt, does it accept it,
//     reject it, or ignore it — and can it transcribe speech to text?
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

const GROK = path.join(os.homedir(), ".grok", "bin", "grok.exe");
const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "grok-voice-exp-"));
log("cwd: " + cwd);

const proc = spawn(GROK, ["agent", "stdio"], { cwd, env: process.env });
let nextId = 1;
const waiters = new Map();
function log(s) { process.stderr.write("[exp] " + s + "\n"); }
function send(method, params) {
  const id = nextId++;
  proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  return new Promise((res) => waiters.set(id, res));
}
function respond(id, result) {
  proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, result }) + "\n");
}

proc.stderr.on("data", (d) => process.stderr.write("[grok-stderr] " + d.toString()));

let assembled = "";
const rl = readline.createInterface({ input: proc.stdout });
rl.on("line", (line) => {
  if (!line.trim()) return;
  let msg;
  try { msg = JSON.parse(line); } catch { log("non-json: " + line.slice(0, 160)); return; }

  if (msg.method && msg.id != null) {
    const m = msg.method;
    if (m === "fs/read_text_file") {
      let content = ""; try { content = fs.readFileSync(msg.params.path, "utf8"); } catch {}
      respond(msg.id, { content });
    } else if (m === "fs/write_text_file") {
      respond(msg.id, {});
    } else if (m.startsWith("terminal/")) {
      if (m === "terminal/create") respond(msg.id, { terminalId: "t1" });
      else if (m === "terminal/output") respond(msg.id, { output: "", exitStatus: { exitCode: 0 }, truncated: false });
      else if (m === "terminal/wait_for_exit") respond(msg.id, { exitCode: 0 });
      else respond(msg.id, {});
    } else {
      log("REQ (other) " + m + "  " + JSON.stringify(msg.params).slice(0, 160));
      respond(msg.id, {});
    }
    return;
  }

  if (msg.method === "session/update") {
    const u = msg.params && msg.params.update;
    const t = u && u.sessionUpdate;
    if (t === "agent_message_chunk") { assembled += (u.content && u.content.text) || ""; }
    return;
  }
  if (msg.id != null) {
    const w = waiters.get(msg.id);
    if (w) { waiters.delete(msg.id); w(msg); }
  }
});

(async () => {
  try {
    const init = await send("initialize", {
      protocolVersion: 1,
      clientCapabilities: { fs: { readTextFile: true, writeTextFile: true }, terminal: true },
    });
    if (init.error) { log("initialize ERROR: " + JSON.stringify(init.error)); return finish(); }
    log("=== FULL initialize result ===");
    log(JSON.stringify(init.result, null, 2));
    const pc = init.result && init.result.agentCapabilities && init.result.agentCapabilities.promptCapabilities;
    log("=== promptCapabilities ===  " + JSON.stringify(pc));

    const ns = await send("session/new", { cwd, mcpServers: [] });
    if (ns.error) { log("session/new ERROR: " + JSON.stringify(ns.error)); return finish(); }
    const sessionId = ns.result.sessionId;
    log("session: " + sessionId);

    // A minimal valid WAV (44-byte header + tiny silent PCM) — NOT speech, just
    // tests whether the audio content block is ACCEPTED by the prompt schema.
    const wav = makeSilentWav();
    const b64 = wav.toString("base64");
    log("--- sending audio content block (mimeType audio/wav, " + wav.length + " bytes) ---");
    const pr = await send("session/prompt", {
      sessionId,
      prompt: [
        { type: "text", text: "Transcribe the attached audio to text. Reply with ONLY the transcription." },
        { type: "audio", data: b64, mimeType: "audio/wav" },
      ],
    });
    if (pr.error) log("prompt ERROR: " + JSON.stringify(pr.error));
    else log("prompt result: " + JSON.stringify(pr.result).slice(0, 300));
    log("=== assembled agent message ===\n" + assembled.slice(0, 800));
  } catch (e) {
    log("EXC " + (e && e.message));
  } finally {
    finish();
  }
})();

function makeSilentWav() {
  const sampleRate = 8000, seconds = 1, numSamples = sampleRate * seconds;
  const dataSize = numSamples * 2;
  const buf = Buffer.alloc(44 + dataSize);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + dataSize, 4); buf.write("WAVE", 8);
  buf.write("fmt ", 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22); buf.writeUInt32LE(sampleRate, 24);
  buf.writeUInt32LE(sampleRate * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write("data", 36); buf.writeUInt32LE(dataSize, 40);
  return buf;
}

function finish() {
  setTimeout(() => { try { proc.kill(); } catch {} process.exit(0); }, 500);
}
setTimeout(() => { log("TIMEOUT — killing"); try { proc.kill(); } catch {} process.exit(0); }, 120000);

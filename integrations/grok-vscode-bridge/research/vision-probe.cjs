// Vision-input capability probe for `grok agent stdio` (issue: e5e5eee review P0-1).
// Q1: does grok advertise promptCapabilities.image in its initialize result?
//     (research/plan-probe.log captured image:false on an older build)
// Q2: if we send an {type:"image"} content block in session/prompt anyway, does
//     the CLI accept it (model describes the image), ignore it, or reject the
//     whole prompt (-32602, the audio precedent from research/voice-input.md)?
// Run: node research/vision-probe.cjs   (needs a logged-in grok; burns credits)
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const zlib = require("node:zlib");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

const GROK = process.env.GROK_BIN ||
  path.join(os.homedir(), ".grok", "bin", process.platform === "win32" ? "grok.exe" : "grok");
function log(s) { process.stderr.write("[exp] " + s + "\n"); }

// Build a 1x1 solid-red PNG in-process so the expected answer ("red") proves
// the model actually decoded the pixels, not just the tag text.
function crc32(buf) {
  let c, table = [];
  for (let n = 0; n < 256; n++) {
    c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const b of buf) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}
function redPixelPng(size) {
  const n = size || 1;
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(n, 0); ihdr.writeUInt32BE(n, 4); // n x n
  ihdr[8] = 8; ihdr[9] = 2; // 8-bit depth, RGB
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(n * 3).fill(Buffer.from([255, 0, 0]))]);
  const raw = Buffer.concat(Array.from({ length: n }, () => row));
  return Buffer.concat([
    sig, chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0)),
  ]);
}

const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "grok-vision-exp-"));
log("grok: " + GROK);
log("cwd: " + cwd);
const proc = spawn(GROK, ["agent", "stdio"], { cwd, env: process.env });
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
    } else if (m === "fs/write_text_file") respond(msg.id, {});
    else if (m === "terminal/create") respond(msg.id, { terminalId: "t1" });
    else if (m === "terminal/output") respond(msg.id, { output: "", exitStatus: { exitCode: 0 }, truncated: false });
    else if (m === "terminal/wait_for_exit") respond(msg.id, { exitCode: 0 });
    else if (m.startsWith("terminal/")) respond(msg.id, {});
    else { log("REQ (other) " + m); respond(msg.id, {}); }
    return;
  }
  if (msg.method === "session/update") {
    const u = msg.params && msg.params.update;
    if (u && u.sessionUpdate === "agent_message_chunk") assembled += (u.content && u.content.text) || "";
    return;
  }
  if (msg.id != null && waiters.has(msg.id)) {
    const res = waiters.get(msg.id); waiters.delete(msg.id); res(msg);
  }
});

(async () => {
  const timer = setTimeout(() => { log("TIMEOUT (120s)"); proc.kill(); process.exit(2); }, 120_000);
  const init = await send("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: true, writeTextFile: true }, terminal: true },
    clientInfo: { name: "vision-probe", version: "0" },
  });
  const caps = init.result && init.result.agentCapabilities;
  log("=== promptCapabilities ===  " + JSON.stringify(caps && caps.promptCapabilities));

  const sess = await send("session/new", { cwd, mcpServers: [] });
  if (!sess.result) { log("session/new FAILED: " + JSON.stringify(sess.error)); proc.kill(); process.exit(1); }
  log("session: " + sess.result.sessionId);

  // PROBE_SVG=1 sends an SVG block instead — checks whether non-raster mimes
  // (which docs.x.ai says are unsupported: only jpg/jpeg/png) reject the turn.
  const asSvg = process.env.PROBE_SVG === "1";
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="red"/></svg>';
  const png = redPixelPng(Number(process.env.PROBE_PNG_SIZE || 256));
  const block = asSvg
    ? { type: "image", mimeType: "image/svg+xml", data: Buffer.from(svg).toString("base64") }
    : { type: "image", mimeType: "image/png", data: png.toString("base64") };
  log(asSvg ? "sending SVG block" : "png bytes: " + png.length);
  const reply = await send("session/prompt", {
    sessionId: sess.result.sessionId,
    prompt: [
      { type: "text", text: "[Image #1] What is the dominant color of this image? Reply with just the color name, one word." },
      { type: "image", mimeType: "image/png", data: png.toString("base64") },
    ],
  });
  clearTimeout(timer);
  if (reply.error) {
    log("=== session/prompt REJECTED ===");
    log(JSON.stringify(reply.error, null, 2));
  } else {
    log("=== session/prompt ACCEPTED ===  stopReason: " + JSON.stringify(reply.result && reply.result.stopReason));
    log("=== model reply ===  " + JSON.stringify(assembled.trim().slice(0, 300)));
    log(/red/i.test(assembled) ? "VERDICT: model SAW the image (answered red)" : "VERDICT: model did NOT clearly see the image");
  }
  proc.kill();
  process.exit(0);
})().catch((e) => { log("probe error: " + e.message); proc.kill(); process.exit(1); });

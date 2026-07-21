#!/usr/bin/env node
// Probe: WHEN does grok flush `signals.json` (contextTokensUsed /
// contextWindowTokens) relative to a turn's ACP response — in particular the
// /compact turn, whose response meta reports totalTokens:0 (never a real
// measurement, stripped by gateZeroTokenMeta)?
//
// The extension reads signals.json right after a stripped-zero turn (immediate
// + 1.5s delayed re-read, emitContextUsage in src/sidebar.ts) to refresh the
// context donut moments after "Compacted.". This probe validates that timing:
//
//   seed turn (~40KB filler) → read signals.json
//   /compact turn → read signals.json at t=0 / 250 / 500 / 1000 / 1500 / 3000ms
//   "after" turn → read once more (the value the next turn would report)
//
// PASS = some read ≤1500ms after the compact response shows a contextTokensUsed
// strictly below the post-seed value (compact shrinks context, doesn't empty it).
//
// Run: node research/signals-refresh-probe.cjs   (needs a logged-in grok)
// Env: GROK_BIN=… FILLER_BYTES=…

const { spawn } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

const FILLER_BYTES = Number(process.env.FILLER_BYTES || 40 * 1024);
const TIMEOUT_MS = 240_000;

function grokBin() {
  if (process.env.GROK_BIN) return process.env.GROK_BIN;
  const home = process.env.USERPROFILE || process.env.HOME || os.homedir();
  for (const name of ["grok.exe", "grok.cmd", "grok"]) {
    const p = path.join(home, ".grok", "bin", name);
    if (fs.existsSync(p)) return p;
  }
  return "grok";
}

function makeFiller(bytes) {
  const line = "signals-probe filler: the quick brown fox jumps over the lazy dog 0123456789\n";
  let out = "";
  while (out.length < bytes) out += line;
  return out.slice(0, bytes);
}

const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "grok-signals-probe-"));
fs.writeFileSync(path.join(cwd, "README.md"), "# signals probe\n");
const proc = spawn(grokBin(), ["agent", "stdio"], { cwd, env: process.env, shell: process.platform === "win32" });

let buf = "";
let nextId = 1;
let sessionId = "";
const waiters = new Map();
const readings = [];
let agentText = ""; // accumulated agent_message_chunk text (reset per turn by callers)

const timer = setTimeout(() => {
  console.log("TIMEOUT");
  finish(1);
}, TIMEOUT_MS);

function finish(code) {
  clearTimeout(timer);
  try { proc.kill(); } catch {}
  process.exit(code);
}

function write(obj) { proc.stdin.write(JSON.stringify(obj) + "\n"); }
function send(method, params) {
  const id = nextId++;
  write({ jsonrpc: "2.0", id, method, params });
  return new Promise((res) => waiters.set(id, res));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function readSignals(tag) {
  const home = process.env.USERPROFILE || process.env.HOME || os.homedir();
  const p = path.join(home, ".grok", "sessions", encodeURIComponent(cwd), sessionId, "signals.json");
  let used = null, window = null;
  try {
    const raw = JSON.parse(fs.readFileSync(p, "utf8"));
    used = raw.contextTokensUsed ?? null;
    window = raw.contextWindowTokens ?? null;
  } catch (e) {
    console.log(`[signals] ${tag}: unreadable (${e.message})`);
    readings.push({ tag, used: null });
    return null;
  }
  console.log(`[signals] ${tag}: contextTokensUsed=${used} window=${window}`);
  readings.push({ tag, used });
  return used;
}

// Does a turn land in chat_history.jsonl? A hidden /session-info that grows the
// history would replay as a visible user bubble on restore — dealbreaker info.
function historyLines(tag) {
  const home = process.env.USERPROFILE || process.env.HOME || os.homedir();
  const p = path.join(home, ".grok", "sessions", encodeURIComponent(cwd), sessionId, "chat_history.jsonl");
  try {
    const lines = fs.readFileSync(p, "utf8").split("\n").filter(Boolean).length;
    console.log(`[history] ${tag}: ${lines} lines`);
    return lines;
  } catch (e) {
    console.log(`[history] ${tag}: unreadable (${e.message})`);
    return null;
  }
}

proc.stdout.on("data", (d) => {
  buf += d;
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i);
    buf = buf.slice(i + 1);
    if (!line.trim()) continue;
    let m;
    try { m = JSON.parse(line); } catch { continue; }
    if (m.id != null && m.method == null) {
      const w = waiters.get(m.id);
      if (w) { waiters.delete(m.id); w(m); }
    } else if (m.method === "session/update") {
      const u = m.params?.update;
      if (u?.sessionUpdate === "agent_message_chunk") agentText += u.content?.text ?? "";
    } else if (m.method && m.id != null) {
      // server → client request: ack everything (probe workspace is inert)
      if (m.method === "fs/read_text_file") {
        let content = "";
        try { content = fs.readFileSync(m.params.path, "utf8"); } catch {}
        write({ jsonrpc: "2.0", id: m.id, result: { content } });
      } else if (m.method === "session/request_permission") {
        const opt = (m.params.options || [])[0];
        write({ jsonrpc: "2.0", id: m.id, result: { outcome: { outcome: "selected", optionId: opt?.optionId } } });
      } else {
        write({ jsonrpc: "2.0", id: m.id, result: {} });
      }
    }
  }
});
proc.on("exit", (code) => { console.log(`grok exited code=${code}`); });

(async () => {
  const init = await send("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: true, writeTextFile: true }, terminal: true },
  });
  if (init.error) { console.log("initialize error:", JSON.stringify(init.error)); return finish(1); }
  const ns = await send("session/new", { cwd, mcpServers: [] });
  if (ns.error || !ns.result?.sessionId) { console.log("session/new error:", JSON.stringify(ns.error ?? ns)); return finish(1); }
  sessionId = ns.result.sessionId;
  console.log(`session ${sessionId} model=${ns.result.models?.currentModelId}`);

  console.log("\n=== seed turn ===");
  const seed = await send("session/prompt", {
    sessionId,
    prompt: [{ type: "text", text: "Reply with exactly: seeded\n\nFiller for a context-size probe, no action needed:\n\n" + makeFiller(FILLER_BYTES) }],
  });
  console.log("seed _meta:", JSON.stringify(seed.result?._meta ?? seed.error));
  const preCompact = readSignals("post-seed t=0");
  await sleep(1500);
  const preCompactWaited = readSignals("post-seed t=1500");

  console.log("\n=== /compact turn ===");
  historyLines("pre-compact");
  const compact = await send("session/prompt", { sessionId, prompt: [{ type: "text", text: "/compact" }] });
  console.log("compact _meta:", JSON.stringify(compact.result?._meta ?? compact.error));
  // Short watch: run 1 established the compact turn itself NEVER flushes (the
  // pre-compact count survived 20s); keep a 3s tail as regression evidence.
  const start = Date.now();
  for (const ms of [0, 500, 1500, 3000]) {
    const wait = ms - (Date.now() - start);
    if (wait > 0) await sleep(wait);
    readSignals(`post-compact t=${ms}`);
    readings.at(-1).t = ms;
  }
  const historyAfterCompact = historyLines("post-compact");

  // The user-suggested fix shape: a hidden CLI-local /session-info turn (no
  // model inference — near-instant). Does ITS end flush the recomputed count?
  // And does it append to chat_history.jsonl (→ visible bubble on restore)?
  console.log("\n=== /session-info turn ===");
  agentText = "";
  const t0 = Date.now();
  const si = await send("session/prompt", { sessionId, prompt: [{ type: "text", text: "/session-info" }] });
  const siMs = Date.now() - t0;
  await sleep(300); // let trailing chunks land
  console.log(`session-info turn took ${siMs}ms, _meta:`, JSON.stringify(si.result?._meta ?? si.error));
  console.log("session-info reply text:", JSON.stringify(agentText));
  const start2 = Date.now();
  for (const ms of [0, 250, 500, 1000, 1500]) {
    const wait = ms - (Date.now() - start2);
    if (wait > 0) await sleep(wait);
    readSignals(`post-session-info t=${ms}`);
    readings.at(-1).t = ms;
    readings.at(-1).si = true;
  }
  const historyAfterSi = historyLines("post-session-info");

  console.log("\n=== after (inference) turn ===");
  const after = await send("session/prompt", { sessionId, prompt: [{ type: "text", text: "Reply with just: ok" }] });
  console.log("after _meta:", JSON.stringify(after.result?._meta ?? after.error));
  await sleep(800);
  readSignals("post-after");

  const pre = preCompactWaited ?? preCompact;
  const siReads = readings.filter((r) => r.si && r.used != null);
  const siShrunk = siReads.find((r) => pre != null && r.used < pre);
  console.log("\n================ VERDICT ================");
  console.log(`pre-compact contextTokensUsed: ${pre}`);
  console.log(`post-compact reads (expect stale): ${readings.filter((r) => r.tag.startsWith("post-compact")).map((r) => `t=${r.t}→${r.used}`).join(", ")}`);
  console.log(`/session-info turn latency: ${siMs}ms`);
  console.log(`post-/session-info reads: ${siReads.map((r) => `t=${r.t}→${r.used}`).join(", ") || "(none readable)"}`);
  console.log(`chat_history lines: post-compact=${historyAfterCompact} post-session-info=${historyAfterSi} (growth = restore-visible bubble)`);
  if (siShrunk) {
    console.log(`PASS — a hidden /session-info flushes the post-compact count by t=${siShrunk.t}ms (${siShrunk.used} < ${pre}).`);
  } else {
    console.log("NO — /session-info's end did not flush a recomputed count; only a real inference turn does (the post-/compact re-prime).");
  }
  finish(0);
})().catch((e) => { console.log("probe error:", e); finish(1); });

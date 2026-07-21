#!/usr/bin/env node
// #22 follow-up probe — the DECISIVE test for whether a grok build really fixes the
// stdio-EOF regression. The original probe only tested `initialize`; 0.2.67 answers
// that but then hangs at `session/new` (the bug moved one message later). This probe
// sends initialize THEN session/new with stdin held OPEN (as a real ACP client must).
//   • session/new answered with stdin open  → genuinely fixed
//   • session/new only flushed after we close stdin (EOF) → bug PERSISTS (just moved)
// Always re-verify a claimed fix with THIS, not just the initialize probe.
//   Usage: GROK_BIN=grok node research/stdio-eof-sessionnew-probe.cjs
const { spawn } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

const bin = process.env.GROK_BIN || "grok";
const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "grok-probe-"));
const child = spawn(bin, ["agent", "stdio"], { stdio: ["pipe", "pipe", "pipe"], shell: process.platform === "win32" });

let buf = "";
const t0 = Date.now();
let initOK = false, newOK = false, closedStdin = false;
const ms = () => Date.now() - t0;
const send = (obj) => child.stdin.write(JSON.stringify(obj) + "\n");

child.stdout.on("data", (d) => {
  buf += d.toString();
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line) continue;
    let msg; try { msg = JSON.parse(line); } catch { continue; }
    if (msg.id === 1 && (msg.result || msg.error)) {
      initOK = true;
      console.log(`✅ initialize answered @${ms()}ms (stdin open)`);
      console.log(`→ sending session/new (stdin stays OPEN)…`);
      send({ jsonrpc: "2.0", id: 2, method: "session/new", params: { cwd, mcpServers: [] } });
    } else if (msg.id === 2) {
      newOK = true;
      const tag = closedStdin ? "ONLY after closing stdin (EOF) — bug PERSISTS" : "with stdin OPEN — genuinely fixed";
      console.log(`✅ session/new answered @${ms()}ms ${tag}`);
      child.kill(); process.exit(closedStdin ? 1 : 0);
    } else if (msg.method) {
      console.log(`   …notification ${msg.method} @${ms()}ms`);
    }
  }
});
child.stderr.on("data", (d) => process.stderr.write(`[stderr] ${d}`));
child.on("exit", (c) => { if (!newOK) { console.log(`❌ exited code=${c} @${ms()}ms — session/new never answered (bug present)`); process.exit(1); } });

send({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: 1, clientCapabilities: { fs: { readTextFile: true, writeTextFile: true }, terminal: true } } });

// If session/new hasn't answered 8s after init, close stdin to test the EOF hypothesis.
setTimeout(() => {
  if (initOK && !newOK) { console.log(`… session/new still unanswered @${ms()}ms → CLOSING stdin (EOF) to test the bug`); closedStdin = true; child.stdin.end(); }
}, 8000);
setTimeout(() => { if (!newOK) { console.log(`❌ TIMEOUT @${ms()}ms (closedStdin=${closedStdin})`); child.kill(); process.exit(1); } }, 20000);

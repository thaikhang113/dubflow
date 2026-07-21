#!/usr/bin/env node
// Targeted reproduction of the #22 stdio-EOF regression, but on this macOS build.
// The regression: `grok agent stdio` won't read its first stdin line until stdin
// hits EOF — so a live ACP client (which keeps stdin open) hangs at `initialize`.
// This probe keeps stdin OPEN (as the real extension does) and checks whether
// `initialize` is answered. If we get a response, the build is NOT affected.
const { spawn } = require("node:child_process");

const bin = process.env.GROK_BIN || "grok";
const child = spawn(bin, ["agent", "stdio"], { stdio: ["pipe", "pipe", "pipe"] });

let buf = "";
let answered = false;
const t0 = Date.now();

child.stdout.on("data", (d) => {
  buf += d.toString();
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line) continue;
    try {
      const msg = JSON.parse(line);
      if (msg.id === 1 && msg.result) {
        answered = true;
        console.log(`✅ initialize ANSWERED after ${Date.now() - t0}ms (stdin still OPEN)`);
        console.log(`   protocolVersion: ${msg.result.protocolVersion}`);
        child.kill();
        process.exit(0);
      }
    } catch {
      /* non-JSON banner line, ignore */
    }
  }
});

child.stderr.on("data", (d) => process.stderr.write(`[stderr] ${d}`));
child.on("exit", (code) => {
  if (!answered) {
    console.log(`❌ process exited (code ${code}) WITHOUT answering initialize — regression present`);
    process.exit(1);
  }
});

// Send the ACP initialize request and DELIBERATELY keep stdin open.
const init = {
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: { protocolVersion: 1, clientCapabilities: { fs: { readTextFile: true, writeTextFile: true } } },
};
child.stdin.write(JSON.stringify(init) + "\n");
// NOTE: no child.stdin.end() — this is what triggered the hang on broken Windows builds.

setTimeout(() => {
  if (!answered) {
    console.log(`❌ TIMEOUT after 15s with stdin open — initialize never answered (regression present)`);
    child.kill();
    process.exit(1);
  }
}, 15_000);

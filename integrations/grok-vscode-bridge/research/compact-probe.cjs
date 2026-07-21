#!/usr/bin/env node
// Probe: does `/compact` actually compress the session, and what does the
// prompt response `_meta.totalTokens` report around it?
//
// Four variants. A and B mirror the extension's two send paths (src/sidebar.ts
// handleSend + src/prompt-builder.ts buildPrompt); C and D are the fix shapes
// (slash at position 0, context trailing) — findings in research/compact.md:
//   A) bare        — text block is exactly "/compact" (gear-menu path,
//                    bare:true clears chips, slash sits at position 0)
//   B) enveloped   — "<vscode-context …>…</vscode-context>\n\n/compact"
//                    (typed send with the implicit active-editor chip; the
//                    envelope pushes the slash OFF position 0)
//   C) trailing        — "/compact\n\n<envelope>" (post-fix wire shape)
//   D) trailing-block  — "/compact\n\n<envelope>\n\n<selection block>"
// Each variant runs in its own session: seed ~40KB filler → compact → "ok".
//
// Per prompt it prints the full response `_meta`; during the compact turn it
// prints every session/update type + the agent's reply text (the direct
// evidence for "CLI executed compact" vs "LLM chatted about the text").
// Also records any ACP `usage_update` (RFD session-usage — used/size) and
// whether available_commands advertises a compact command.
//
// Run: node research/compact-probe.cjs        (needs a logged-in grok)
// Env: GROK_BIN=… FILLER_BYTES=…

const { spawn } = require("node:child_process");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

const FILLER_BYTES = Number(process.env.FILLER_BYTES || 40 * 1024);
const PER_VARIANT_TIMEOUT_MS = 180_000;
// Native compact may be async on the CLI side — wait this long after the
// compact turn before sending the "after" probe (default matches the other
// inter-turn waits; A-variant retests set it higher).
const POST_COMPACT_WAIT_MS = Number(process.env.POST_COMPACT_WAIT_MS || 800);
const ONLY = process.env.VARIANT || "";

// Must match CONTEXT_TAG_OPEN/CLOSE in src/prompt-builder.ts — variant B is
// byte-identical to buildPrompt("/compact", [implicit README.md]).
const ENVELOPE =
  '<vscode-context note="added by the editor, not typed by the user">\n' +
  "Currently open in the editor (for context): README.md\n" +
  "</vscode-context>";

function grokBin() {
  if (process.env.GROK_BIN) return process.env.GROK_BIN;
  const home = process.env.HOME || os.homedir();
  const p = path.join(home, ".grok", "bin", "grok");
  return fs.existsSync(p) ? p : "grok";
}

function makeFiller(bytes) {
  const line = "compact-probe filler: the quick brown fox jumps over the lazy dog 0123456789\n";
  let out = "";
  while (out.length < bytes) out += line;
  return out.slice(0, bytes);
}

function runVariant(name, compactText) {
  return new Promise((resolve) => {
    const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "grok-compact-probe-"));
    fs.writeFileSync(path.join(cwd, "README.md"), "# compact probe\n");
    const proc = spawn(grokBin(), ["agent", "stdio"], { cwd, env: process.env });

    let buf = "";
    let nextId = 1;
    let sessionId = "";
    let phase = "startup";
    let agentText = "";
    const waiters = new Map();
    const report = {
      variant: name,
      compactCommandAdvertised: null,
      metas: {},          // phase → _meta
      compactUpdates: [], // sessionUpdate types seen during the compact turn
      compactReply: "",   // agent text during the compact turn
      usageUpdates: [],   // any usage_update payloads, tagged with phase
      errors: [],
    };

    const timer = setTimeout(() => {
      report.errors.push("TIMEOUT in phase " + phase);
      finish();
    }, PER_VARIANT_TIMEOUT_MS);

    function finish() {
      clearTimeout(timer);
      try { proc.kill(); } catch {}
      resolve(report);
    }

    function write(obj) { proc.stdin.write(JSON.stringify(obj) + "\n"); }
    function send(method, params) {
      const id = nextId++;
      write({ jsonrpc: "2.0", id, method, params });
      return new Promise((res) => waiters.set(id, res));
    }

    async function promptTurn(label, text) {
      phase = label;
      agentText = "";
      console.log(`\n=== [${name}] ${label} (${text.length} bytes) ===`);
      const res = await send("session/prompt", { sessionId, prompt: [{ type: "text", text }] });
      if (res.error) {
        report.errors.push(`${label}: ${JSON.stringify(res.error)}`);
        console.log(`[${name}] ${label} ERROR:`, JSON.stringify(res.error));
        return;
      }
      report.metas[label] = res.result?._meta ?? null;
      console.log(`[${name}] ${label} _meta:`, JSON.stringify(res.result?._meta ?? null));
      if (label === "compact") {
        report.compactReply = agentText;
        console.log(`[${name}] compact reply text: ${JSON.stringify(agentText.slice(0, 400))}`);
        logHistoryStats("post-compact");
        await new Promise((r) => setTimeout(r, POST_COMPACT_WAIT_MS));
        logHistoryStats("post-compact-waited");
        return;
      }
      // let trailing session/update notifications land before the next phase
      await new Promise((r) => setTimeout(r, 800));
      logHistoryStats(`post-${label}`);
    }

    // grok persists the session at ~/.grok/sessions/<urlencoded-cwd>/<id>/ —
    // a real compaction rewrites chat_history.jsonl, so its line count and
    // byte size before/after are ground truth the _meta can't fake.
    function logHistoryStats(tag) {
      try {
        const home = process.env.HOME || os.homedir();
        const dir = path.join(home, ".grok", "sessions", encodeURIComponent(cwd), sessionId);
        const hist = path.join(dir, "chat_history.jsonl");
        const st = fs.statSync(hist);
        const lines = fs.readFileSync(hist, "utf8").split("\n").filter(Boolean).length;
        console.log(`[${name}] ${tag}: chat_history.jsonl lines=${lines} bytes=${st.size}`);
      } catch (e) {
        console.log(`[${name}] ${tag}: chat_history.jsonl unreadable (${e.message})`);
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
        handle(m);
      }
    });
    proc.stderr.on("data", (d) => {
      const s = d.toString();
      if (/error|panic/i.test(s)) console.log(`[${name}] STDERR`, s.slice(0, 200));
    });
    proc.on("exit", (code) => {
      if (phase !== "done") {
        report.errors.push(`grok exited code=${code} in phase ${phase}`);
        finish();
      }
    });

    function handle(m) {
      // response to one of our requests
      if (m.id != null && m.method == null) {
        const w = waiters.get(m.id);
        if (w) { waiters.delete(m.id); w(m); }
        return;
      }
      // server → client request: ack everything (probe workspace is inert)
      if (m.method && m.id != null) {
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
        return;
      }
      // notification
      if (m.method === "session/update") {
        const u = m.params?.update;
        if (!u) return;
        const t = u.sessionUpdate;
        if (t === "agent_message_chunk") agentText += u.content?.text ?? "";
        if (phase === "compact" && !report.compactUpdates.includes(t)) report.compactUpdates.push(t);
        if (t === "available_commands_update") {
          const names = (u.availableCommands || []).map((c) => c?.name).filter(Boolean);
          report.compactCommandAdvertised = names.includes("compact");
          console.log(`[${name}] commands (compact=${report.compactCommandAdvertised}):`, names.join(", "));
        }
        if (t === "usage_update") {
          report.usageUpdates.push({ phase, update: u });
          console.log(`[${name}] usage_update in ${phase}:`, JSON.stringify(u));
        }
      }
    }

    (async () => {
      const init = await send("initialize", {
        protocolVersion: 1,
        clientCapabilities: { fs: { readTextFile: true, writeTextFile: true }, terminal: true },
      });
      if (init.error) { report.errors.push("initialize: " + JSON.stringify(init.error)); return finish(); }
      const ns = await send("session/new", { cwd, mcpServers: [] });
      if (ns.error || !ns.result?.sessionId) { report.errors.push("session/new: " + JSON.stringify(ns.error ?? ns)); return finish(); }
      sessionId = ns.result.sessionId;
      console.log(`[${name}] session ${sessionId} model=${ns.result.models?.currentModelId}`);

      await promptTurn("seed", "Reply with exactly: seeded\n\nFiller for a context-size probe, no action needed:\n\n" + makeFiller(FILLER_BYTES));
      await promptTurn("compact", compactText);
      await promptTurn("after", "Reply with just: ok");
      phase = "done";
      finish();
    })().catch((e) => { report.errors.push(String(e)); finish(); });
  });
}

(async () => {
  const variants = [
    ["A-bare", "/compact"],
    ["B-enveloped", ENVELOPE + "\n\n/compact"],
    // C/D: proposed fix shapes — slash at position 0, context TRAILING.
    // C is the plain envelope; D adds a selection block after it (the other
    // buildPrompt part that can ride a send). If C/D dispatch natively like A
    // (totalTokens=0, no updates, empty reply), moving the envelope behind the
    // text is a safe fix; if they chat like B, slash sends must drop context.
    ["C-trailing", "/compact\n\n" + ENVELOPE],
    ["D-trailing-block", "/compact\n\n" + ENVELOPE + "\n\n`README.md` (lines 1-1):\n```md\n# compact probe\n```"],
  ].filter(([n]) => !ONLY || n.startsWith(ONLY));
  const reports = [];
  for (const [n, text] of variants) reports.push(await runVariant(n, text));

  console.log("\n\n================ SUMMARY ================");
  for (const r of reports) {
    console.log(`\n[${r.variant}] compact advertised: ${r.compactCommandAdvertised}`);
    console.log(`[${r.variant}] totalTokens seed → compact → after: ` +
      `${r.metas.seed?.totalTokens} → ${r.metas.compact?.totalTokens} → ${r.metas.after?.totalTokens}`);
    console.log(`[${r.variant}] compact-turn updates: ${r.compactUpdates.join(", ") || "(none)"}`);
    console.log(`[${r.variant}] compact reply: ${JSON.stringify(r.compactReply.slice(0, 200))}`);
    console.log(`[${r.variant}] usage_updates: ${r.usageUpdates.length}`);
    if (r.errors.length) console.log(`[${r.variant}] ERRORS: ${r.errors.join(" | ")}`);
  }
  process.exit(0);
})();

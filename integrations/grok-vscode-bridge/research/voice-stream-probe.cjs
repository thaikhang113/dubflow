// Streaming STT probe: drive wss://api.x.ai/v1/stt with ws, observe the real
// event protocol, and A/B test whether the `keyterm` query param fixes the
// "grok send" → "Gronsent" mishearing.
//   node research/voice-stream-probe.cjs [wav]
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const WebSocket = require("ws");

function loadKey() {
  const env = path.join(__dirname, "..", ".env");
  const m = fs.readFileSync(env, "utf8").match(/(?:GROK_VOICE_API_KEY|XAI_API_KEY)\s*=\s*(.+)/);
  return (m && m[1].trim()) || process.env.GROK_VOICE_API_KEY || process.env.XAI_API_KEY;
}

// Decode any WAV → raw PCM s16le 16k mono (what the streaming endpoint expects).
function toPcm(wavPath) {
  const r = spawnSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-i", wavPath, "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"], { maxBuffer: 1 << 26 });
  return r.stdout;
}

function streamOnce(key, pcm, keyterms) {
  return new Promise((resolve) => {
    const qs = new URLSearchParams({ sample_rate: "16000", encoding: "pcm", interim_results: "true" });
    for (const k of keyterms || []) qs.append("keyterm", k);
    const url = `wss://api.x.ai/v1/stt?${qs.toString()}`;
    const ws = new WebSocket(url, { headers: { Authorization: `Bearer ${key}` } });
    const partials = [];
    let done = null;

    ws.on("open", () => {
      // Wait for transcript.created before streaming (per docs).
    });
    ws.on("message", (data, isBinary) => {
      if (isBinary) return;
      let ev; try { ev = JSON.parse(data.toString()); } catch { return; }
      if (ev.type === "transcript.created") {
        // Stream PCM in ~100ms chunks (3200 bytes @ 16k mono s16le), paced.
        const chunk = 3200;
        let i = 0;
        const pump = () => {
          if (i >= pcm.length) { ws.send(JSON.stringify({ type: "audio.done" })); return; }
          ws.send(pcm.subarray(i, i + chunk));
          i += chunk;
          setTimeout(pump, 40);
        };
        pump();
      } else if (ev.type === "transcript.partial") {
        partials.push(ev.text);
        console.error(`   partial is_final=${ev.is_final} speech_final=${ev.speech_final} start=${ev.start} dur=${ev.duration} text=${JSON.stringify(ev.text)}`);
      } else if (ev.type === "transcript.done") {
        done = ev;
        ws.close();
      } else if (ev.type === "error") {
        console.error("   WS error event:", JSON.stringify(ev));
      }
    });
    ws.on("error", (e) => { console.error("   ws error:", e.message); resolve({ error: e.message }); });
    ws.on("close", () => resolve({ partials, done }));
  });
}

(async () => {
  const key = loadKey();
  const wav = process.argv[2] || path.join(__dirname, "test-stream.wav");
  const pcm = toPcm(wav);
  console.error(`PCM: ${pcm.length} bytes (${(pcm.length / 32000).toFixed(2)}s @16k mono)\n`);

  console.error("=== A) NO keyterm ===");
  const a = await streamOnce(key, pcm, []);
  console.error("   partials:", JSON.stringify((a.partials || []).slice(-3)));
  console.error("   FINAL   :", JSON.stringify(a.done && a.done.text), "\n");

  console.error('=== B) keyterm="grok send" + "Grok" ===');
  const b = await streamOnce(key, pcm, ["grok send", "Grok"]);
  console.error("   partials:", JSON.stringify((b.partials || []).slice(-3)));
  console.error("   FINAL   :", JSON.stringify(b.done && b.done.text));
  console.error("   sample transcript.done keys:", b.done ? JSON.stringify(Object.keys(b.done)) : "(none)");
})();

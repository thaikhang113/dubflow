// Measure xAI Speech-to-Text cost for a given audio file. STT is billed by
// AUDIO DURATION, not word count: $0.10/hour (batch) and $0.20/hour (streaming).
// We POST the file, read the API's returned `duration`, and compute the cost.
//   node research/voice-cost-probe.cjs [wav]   (default: research/cost-sample.wav)
//
// Reproduce the default sample (510 real words from this project's design chat):
//   $t = Get-Content -Raw research\cost-sample.txt
//   Add-Type -AssemblyName System.Speech
//   $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
//   $s.SetOutputToWaveFile("research\cost-sample.wav"); $s.Speak($t); $s.Dispose()
const fs = require("node:fs");
const path = require("node:path");
const { Blob } = require("node:buffer");

const RATE_BATCH = 0.10;   // USD / hour
const RATE_STREAM = 0.20;  // USD / hour

function loadKey() {
  const env = path.join(__dirname, "..", ".env");
  const m = fs.readFileSync(env, "utf8").match(/(?:GROK_VOICE_API_KEY|XAI_API_KEY)\s*=\s*(.+)/);
  return (m && m[1].trim()) || process.env.GROK_VOICE_API_KEY || process.env.XAI_API_KEY;
}

(async () => {
  const wav = process.argv[2] || path.join(__dirname, "cost-sample.wav");
  if (!fs.existsSync(wav)) { console.error("No audio at " + wav + " (synthesize it — see header)."); process.exit(1); }
  const bytes = fs.readFileSync(wav);
  const form = new FormData();
  form.append("file", new Blob([bytes], { type: "audio/wav" }), path.basename(wav));
  const res = await fetch("https://api.x.ai/v1/stt", { method: "POST", headers: { Authorization: `Bearer ${loadKey()}` }, body: form });
  const j = await res.json();
  const dur = j.duration;                 // seconds of audio, per the API
  const words = j.text.trim().split(/\s+/).length;
  const hr = dur / 3600;
  console.error(`audio: ${dur}s (${(dur / 60).toFixed(2)} min), transcript ${words} words`);
  console.error(`batch  $${RATE_BATCH}/hr  -> $${(hr * RATE_BATCH).toFixed(5)}  (${(hr * RATE_BATCH * 100).toFixed(3)}¢)`);
  console.error(`stream $${RATE_STREAM}/hr -> $${(hr * RATE_STREAM).toFixed(5)}  (${(hr * RATE_STREAM * 100).toFixed(3)}¢)`);
  console.error(`~ $${(hr * RATE_BATCH / words * 1000).toFixed(5)} per 1,000 words (batch)`);
})();

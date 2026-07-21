// Grok Speech-to-Text round-trip probe.
//   node research/voice-stt-probe.cjs [path-to-audio]
// Reads XAI_API_KEY from env or .env, POSTs the audio file to api.x.ai/v1/stt,
// prints HTTP status + the transcript. Defaults to research/test-audio.wav
// (a known phrase synthesized via Windows SAPI), so the transcript can be
// asserted against "the quick brown fox jumps over the lazy dog".
//
// Regenerate the test WAV with no downloads (Windows PowerShell):
//   Add-Type -AssemblyName System.Speech
//   $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
//   $s.SetOutputToWaveFile("research\test-audio.wav")
//   $s.Speak("The quick brown fox jumps over the lazy dog."); $s.Dispose()
// (macOS: `say -o research/test-audio.aiff "..."`; Linux: `espeak -w ... "..."`.)
const fs = require("node:fs");
const path = require("node:path");

function loadKey() {
  for (const name of ["GROK_VOICE_API_KEY", "XAI_API_KEY"]) {
    if (process.env[name]) return process.env[name].trim();
  }
  const envPath = path.join(__dirname, "..", ".env");
  if (fs.existsSync(envPath)) {
    for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*(?:GROK_VOICE_API_KEY|XAI_API_KEY)\s*=\s*(.+?)\s*$/);
      if (m) return m[1].trim();
    }
  }
  return null;
}

(async () => {
  const key = loadKey();
  if (!key) { console.error("No XAI_API_KEY in env or .env"); process.exit(1); }

  const audioPath = process.argv[2] || path.join(__dirname, "test-audio.wav");
  if (!fs.existsSync(audioPath)) { console.error("No audio file at " + audioPath); process.exit(1); }

  const bytes = fs.readFileSync(audioPath);
  const ext = path.extname(audioPath).slice(1).toLowerCase();
  const mime = ext === "mp3" ? "audio/mpeg" : ext === "wav" ? "audio/wav" : "application/octet-stream";

  const form = new FormData();
  form.append("file", new Blob([bytes], { type: mime }), path.basename(audioPath));

  console.error(`POST https://api.x.ai/v1/stt  (${path.basename(audioPath)}, ${bytes.length} bytes, ${mime})`);
  const t0 = Date.now();
  let res;
  try {
    res = await fetch("https://api.x.ai/v1/stt", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}` },
      body: form,
    });
  } catch (e) {
    console.error("FETCH ERROR: " + (e && e.message));
    process.exit(2);
  }
  const ms = Date.now() - t0;
  const bodyText = await res.text();
  console.error(`HTTP ${res.status} ${res.statusText}  (${ms} ms)`);
  let json;
  try { json = JSON.parse(bodyText); } catch { console.error("non-JSON body:\n" + bodyText.slice(0, 800)); process.exit(0); }
  console.error("RESPONSE JSON:\n" + JSON.stringify(json, null, 2).slice(0, 1500));
  if (json && typeof json.text === "string") console.error("\nTRANSCRIPT: " + JSON.stringify(json.text));
})();

// End-to-end verification of the SHIPPED voice code (compiled out/*.js), not the
// standalone probe. Exercises three real paths:
//   1. Windows DirectShow device enumeration (VoiceRecorder.resolveWindowsDevice)
//   2. A live ~3s mic capture via ffmpeg (buildFfmpegArgs) — best-effort
//   3. transcribeAudio() against the real api.x.ai/v1/stt with the .env key
// Run:  node research/voice-e2e-verify.cjs
const path = require("node:path");
const fs = require("node:fs");
const { VoiceRecorder, transcribeAudio } = require("../out/voice-recorder.js");
const { parseDshowAudioDevices, buildListDevicesArgs } = require("../out/voice.js");
const { spawnSync } = require("node:child_process");

function loadKey() {
  const env = path.join(__dirname, "..", ".env");
  for (const line of fs.readFileSync(env, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*(?:GROK_VOICE_API_KEY|XAI_API_KEY)\s*=\s*(.+?)\s*$/);
    if (m) return m[1].trim();
  }
  return process.env.GROK_VOICE_API_KEY || process.env.XAI_API_KEY;
}

(async () => {
  const key = loadKey();
  const log = (m) => console.error(m);

  // 1. Device enumeration against real ffmpeg output
  const list = spawnSync("ffmpeg", buildListDevicesArgs(), { encoding: "utf8" });
  const devices = parseDshowAudioDevices(list.stderr || "");
  console.error("[1] dshow audio devices parsed from real ffmpeg:", JSON.stringify(devices));

  // 2. Live mic capture (best-effort — no mic / silence is fine, we just check it runs)
  const rec = new VoiceRecorder();
  const out = path.join(require("node:os").tmpdir(), "grok-voice-e2e.wav");
  let captured = false;
  try {
    await rec.start({ ffmpegPath: "ffmpeg", outputPath: out, log });
    console.error("[2] recording... (3s)");
    await new Promise((r) => setTimeout(r, 3000));
    const wav = await rec.stop();
    const size = fs.existsSync(wav) ? fs.statSync(wav).size : 0;
    console.error(`[2] captured ${size} bytes to ${wav}`);
    captured = size > 2048;
  } catch (e) {
    console.error("[2] capture failed (expected if no mic):", e.message);
  }

  // 3. transcribeAudio() via the SHIPPED code. Prefer the just-captured clip;
  //    fall back to the known SAPI phrase so this always exercises the API path.
  const fallback = path.join(__dirname, "test-audio.wav");
  const audio = captured && fs.existsSync(out) ? out : fallback;
  console.error(`[3] transcribing ${path.basename(audio)} via shipped transcribeAudio()...`);
  try {
    const text = await transcribeAudio(audio, key, log);
    console.error("[3] TRANSCRIPT:", JSON.stringify(text));
  } catch (e) {
    console.error("[3] transcription failed:", e.message);
    process.exit(1);
  }
})();

// End-to-end check of the SHIPPED VoiceStreamer class (out/voice-streamer.js):
// open the live STT WebSocket, capture the real mic via ffmpeg for 3s, finalize.
// Silence (empty transcript) is fine — this confirms connect → pipe → stop with
// no errors. Run: node research/voice-stream-verify.cjs
const fs = require("node:fs");
const path = require("node:path");
const { VoiceStreamer } = require("../out/voice-streamer.js");

const env = fs.readFileSync(path.join(__dirname, "..", ".env"), "utf8");
const key = (env.match(/(?:GROK_VOICE_API_KEY|XAI_API_KEY)\s*=\s*(.+)/) || [])[1].trim();

(async () => {
  const s = new VoiceStreamer();
  s.on("partial", (e) => console.error("PARTIAL:", JSON.stringify(e)));
  s.on("error", (e) => console.error("STREAM ERROR:", e.message));
  try {
    await s.start({ ffmpegPath: "ffmpeg", apiKey: key, keyterms: ["grok send", "Grok"], log: (m) => console.error(m) });
    console.error("=> streaming started; capturing 3s of mic...");
    await new Promise((r) => setTimeout(r, 3000));
    const text = await s.stop();
    console.error("=> FINAL TRANSCRIPT:", JSON.stringify(text));
    console.error("=> OK (clean connect → capture → finalize)");
  } catch (e) {
    console.error("=> FAILED:", e.message);
    process.exit(1);
  }
})();

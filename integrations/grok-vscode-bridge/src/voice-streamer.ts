// Real-time STT: stream microphone audio to xAI's WebSocket STT endpoint and
// emit live transcripts as the user speaks. ffmpeg captures raw PCM16 to stdout;
// we forward those frames to the socket and fold the `transcript.partial` events
// (keyed by `start` — the trailing `transcript.done` is often empty because
// smart-turn finalizes mid-stream) into the running transcript. Confirmed against
// the live endpoint in research/voice-stream-probe.cjs. Pure framing/accumulation
// logic lives in voice.ts and is unit-tested; this is the spawn/socket shell.
import { spawn, ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import WebSocket from "ws";
import {
  buildSttStreamUrl,
  buildFfmpegStreamArgs,
  applySegment,
  joinSegments,
  TranscriptSegment,
} from "./voice";
import { resolveWindowsAudioDevice } from "./voice-recorder";

export interface StreamStartOpts {
  ffmpegPath: string;
  apiKey: string;
  device?: string;
  keyterms?: string[];
  log?: (msg: string) => void;
}

export interface PartialEvent {
  text: string;
  speechFinal: boolean;
}

export class VoiceStreamer extends EventEmitter {
  private ws?: WebSocket;
  private proc?: ChildProcess;
  private segments: TranscriptSegment[] = [];
  private stopping = false;

  get active(): boolean {
    return !!this.ws || !!this.proc;
  }

  get transcript(): string {
    return joinSegments(this.segments);
  }

  /** Open the socket, start capturing, and resolve once audio is flowing.
   *  Emits "partial" ({text, speechFinal}) per update and "error" (Error). */
  start(opts: StreamStartOpts): Promise<void> {
    const url = buildSttStreamUrl({ keyterms: opts.keyterms });
    opts.log?.(`[voice-stream] connect ${url}`);
    const ws = new WebSocket(url, { headers: { Authorization: `Bearer ${opts.apiKey}` } });
    this.ws = ws;

    return new Promise<void>((resolve, reject) => {
      let settled = false;
      const fail = (err: Error) => {
        if (settled) { this.emit("error", err); return; }
        settled = true;
        clearTimeout(timer);
        try { ws.close(); } catch { /* ignore */ }
        reject(err);
      };
      const timer = setTimeout(
        () => fail(new Error("Speech-to-Text streaming did not start (timeout). Check your network and API key.")),
        8000,
      );

      ws.on("message", (data: WebSocket.RawData, isBinary: boolean) => {
        if (isBinary) return;
        let ev: any;
        try { ev = JSON.parse(data.toString()); } catch { return; }
        if (ev.type === "transcript.created") {
          clearTimeout(timer);
          this.beginCapture(opts)
            .then(() => { if (!settled) { settled = true; resolve(); } })
            .catch(fail);
        } else if (ev.type === "transcript.partial") {
          this.segments = applySegment(this.segments, ev);
          this.emit("partial", { text: joinSegments(this.segments), speechFinal: !!ev.speech_final } as PartialEvent);
        } else if (ev.type === "transcript.done") {
          if (this.segments.length === 0 && typeof ev.text === "string" && ev.text.trim()) {
            this.segments = applySegment(this.segments, { start: 0, text: ev.text });
            this.emit("partial", { text: joinSegments(this.segments), speechFinal: true } as PartialEvent);
          }
        } else if (ev.type === "error") {
          fail(new Error(ev.message || ev.error || "Speech-to-Text streaming error."));
        }
      });
      ws.on("error", (e: Error) => fail(e));
      ws.on("close", () => { clearTimeout(timer); this.stopCapture(); });
    });
  }

  private async beginCapture(opts: StreamStartOpts): Promise<void> {
    let device = opts.device;
    if (process.platform === "win32" && !device) {
      device = await resolveWindowsAudioDevice(opts.ffmpegPath, opts.log);
      if (!device) {
        throw new Error("No microphone (DirectShow audio device) was found. Set grok.voiceInputDevice to its name.");
      }
    }
    const args = buildFfmpegStreamArgs(process.platform, { device });
    opts.log?.(`[voice-stream] capture: ${opts.ffmpegPath} ${args.join(" ")}`);
    const proc = spawn(opts.ffmpegPath, args, { stdio: ["pipe", "pipe", "pipe"] });
    this.proc = proc;
    proc.stdout.on("data", (chunk: Buffer) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try { this.ws.send(chunk); } catch { /* socket closing */ }
      }
    });
    proc.stderr?.on("data", (d) => opts.log?.(`[voice-stream ffmpeg] ${d.toString().trim()}`));
    // ffmpeg exiting on its own (the -t cap after a long silence, or a device
    // error) — not via our stop/cancel — means the session ended; tell the host
    // so it can drop the mic out of "listening".
    proc.on("exit", () => { if (!this.stopping) this.emit("ended"); });
    return new Promise<void>((res, rej) => {
      let settled = false;
      proc.on("error", (e: NodeJS.ErrnoException) => {
        if (settled) return;
        settled = true;
        rej(e.code === "ENOENT"
          ? new Error("ffmpeg was not found. Install ffmpeg (https://ffmpeg.org) or set grok.ffmpegPath.")
          : e);
      });
      // No immediate spawn error within the grace window → capture is live.
      setTimeout(() => { if (!settled) { settled = true; res(); } }, 200);
    });
  }

  /** Stop capture, flush `audio.done`, and resolve with the final transcript. */
  async stop(): Promise<string> {
    this.stopping = true;
    const ws = this.ws;
    await this.drainCapture();
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: "audio.done" })); } catch { /* ignore */ }
      await new Promise<void>((res) => setTimeout(res, 600)); // let a trailing event land
    }
    const text = joinSegments(this.segments);
    this.dispose();
    return text;
  }

  /** Abort without finalizing. */
  cancel(): void {
    this.stopping = true;
    this.dispose();
  }

  /** Gracefully end ffmpeg (q → finalize) so trailing audio isn't dropped. */
  private drainCapture(): Promise<void> {
    const proc = this.proc;
    if (!proc) return Promise.resolve();
    return new Promise<void>((res) => {
      let done = false;
      const finish = () => { if (!done) { done = true; res(); } };
      proc.on("close", finish);
      try { proc.stdin?.write("q"); proc.stdin?.end(); } catch { /* fall through to kill */ }
      setTimeout(() => { try { proc.kill("SIGKILL"); } catch { /* gone */ } finish(); }, 2500);
    });
  }

  private stopCapture(): void {
    const proc = this.proc;
    this.proc = undefined;
    if (!proc) return;
    try { proc.stdin?.write("q"); proc.stdin?.end(); } catch { /* ignore */ }
    try { proc.kill(); } catch { /* ignore */ }
  }

  private dispose(): void {
    this.stopCapture();
    const ws = this.ws;
    this.ws = undefined;
    if (ws) { try { ws.close(); } catch { /* ignore */ } }
  }
}

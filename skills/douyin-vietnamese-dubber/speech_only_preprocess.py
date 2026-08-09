#!/usr/bin/env python3
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

CONFIG = {
    'demucs_chunk_seconds': int(os.environ.get('SPEECH_ONLY_DEMUCS_CHUNK_SECONDS', '600')),
    "subtitle_mode": os.environ.get("SUBTITLE_MODE", "dialogue_only"),
    "ignore_background_music": os.environ.get("IGNORE_BACKGROUND_MUSIC", "true").lower() != "false",
    "ignore_song_lyrics": os.environ.get("IGNORE_SONG_LYRICS", "true").lower() != "false",
    "keep_original_music_bed": os.environ.get("KEEP_ORIGINAL_MUSIC_BED", "true").lower() != "false",
    "enabled": os.environ.get("SPEECH_ONLY_PREPROCESS", "1") != "0",
    "demucs_enabled": os.environ.get("SPEECH_ONLY_DEMUCS", "1") != "0",
    "segmentation_backend": os.environ.get("SPEECH_SEGMENTATION_BACKEND", "auto"),
    "min_speech_segment_seconds": float(os.environ.get("MIN_SPEECH_SEGMENT_SECONDS", "0.35")),
    "merge_gap_seconds": float(os.environ.get("SPEECH_MERGE_GAP_SECONDS", "0.30")),
    "energy_frame_ms": int(float(os.environ.get("SPEECH_ENERGY_FRAME_MS", "30"))),
    "energy_threshold_ratio": float(os.environ.get("SPEECH_ENERGY_THRESHOLD_RATIO", "1.8")),
}

SPEECH_LABELS = {"speech", "male", "female"}
NON_SPEECH_LABELS = {"music", "noise", "noenergy", "silence", "singing", "song", "intro", "outro"}


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


def log(message):
    print(f"speech_only_preprocess: {message}", flush=True)


def ffmpeg_extract(input_video, audio_wav):
    run(["ffmpeg", "-y", "-i", str(input_video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ffmpeg_extract_demucs_input(input_video, audio_wav):
    run(["ffmpeg", "-y", "-i", str(input_video), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(audio_wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def convert_audio(input_audio, output_audio):
    run(["ffmpeg", "-y", "-i", str(input_audio), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output_audio)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def convert_music_bed(input_audio, output_audio):
    run(["ffmpeg", "-y", "-i", str(input_audio), "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(output_audio)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def find_demucs_outputs(demucs_dir):
    vocals = list(Path(demucs_dir).rglob("vocals.wav"))
    no_vocals = list(Path(demucs_dir).rglob("no_vocals.wav"))
    return (vocals[0] if vocals else None), (no_vocals[0] if no_vocals else None)


def concat_audio(inputs, output, channels, rate):
    list_path = Path(output).with_suffix('.concat.txt')
    list_path.write_text(
        ''.join('file ' + repr(str(Path(item).resolve())) + '\n' for item in inputs),
        encoding='utf-8',
    )
    try:
        run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_path),
            '-ac', str(channels), '-ar', str(rate), '-c:a', 'pcm_s16le', str(output),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        list_path.unlink(missing_ok=True)


def demucs_separate_chunked(audio_wav, work_dir, vocals_wav, no_vocals_wav):
    chunk_root = Path(work_dir) / 'demucs-chunks'
    chunk_root.mkdir(parents=True, exist_ok=True)
    pattern = chunk_root / 'input-%05d.wav'
    run([
        'ffmpeg', '-y', '-i', str(audio_wav), '-f', 'segment',
        '-segment_time', str(CONFIG['demucs_chunk_seconds']), '-c', 'copy', str(pattern),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    chunks = sorted(chunk_root.glob('input-*.wav'))
    if not chunks:
        raise RuntimeError('Demucs chunking produced no audio')
    vocals_parts = []
    music_parts = []
    try:
        for index, chunk in enumerate(chunks, 1):
            log(f'running Demucs chunk {index}/{len(chunks)}')
            chunk_vocals = chunk_root / f'vocals-{index:05d}.wav'
            chunk_music = chunk_root / f'no-vocals-{index:05d}.wav'
            report = demucs_separate(
                chunk, chunk_root / f'work-{index:05d}', chunk_vocals, chunk_music
            )
            if not report.get('used'):
                return report
            vocals_parts.append(chunk_vocals)
            music_parts.append(chunk_music)
        concat_audio(vocals_parts, vocals_wav, 1, 16000)
        concat_audio(music_parts, no_vocals_wav, 2, 48000)
        return {'used': True, 'reason': 'ok', 'chunks': len(chunks)}
    finally:
        shutil.rmtree(chunk_root, ignore_errors=True)


def demucs_separate(audio_wav, work_dir, vocals_wav, no_vocals_wav):
    demucs_bin = shutil.which("demucs")
    if not CONFIG["demucs_enabled"] or not demucs_bin:
        log("Demucs not available or disabled; using original audio as vocals fallback")
        convert_audio(audio_wav, vocals_wav)
        silence_like(audio_wav, no_vocals_wav)
        return {"used": False, "reason": "demucs_missing_or_disabled"}
    demucs_out = Path(work_dir) / "demucs"
    if duration_seconds(audio_wav) > CONFIG['demucs_chunk_seconds']:
        return demucs_separate_chunked(
            audio_wav, work_dir, vocals_wav, no_vocals_wav
        )
    demucs_out.mkdir(parents=True, exist_ok=True)
    log("running Demucs --two-stems=vocals")
    run([demucs_bin, "--two-stems=vocals", "-o", str(demucs_out), str(audio_wav)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    found_vocals, found_no_vocals = find_demucs_outputs(demucs_out)
    if not found_vocals or not found_no_vocals:
        log("Demucs output missing required stem; using original audio as vocals fallback")
        convert_audio(audio_wav, vocals_wav)
        silence_like(audio_wav, no_vocals_wav)
        return {"used": False, "reason": "demucs_output_missing"}
    convert_audio(found_vocals, vocals_wav)
    convert_music_bed(found_no_vocals, no_vocals_wav)
    return {"used": True, "reason": "ok"}


def wav_info(path):
    with wave.open(str(path), "rb") as wav_f:
        return wav_f.getnchannels(), wav_f.getframerate(), wav_f.getsampwidth(), wav_f.getnframes()


def duration_seconds(path):
    channels, rate, width, frames = wav_info(path)
    return frames / float(rate)


def silence_like(reference_wav, output_wav):
    dur = max(0.01, duration_seconds(reference_wav))
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", f"{dur:.3f}", "-c:a", "pcm_s16le", str(output_wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ina_segments(vocals_wav):
    try:
        from inaSpeechSegmenter import Segmenter
    except Exception as exc:
        raise RuntimeError(f"inaSpeechSegmenter unavailable: {exc}")
    log("running inaSpeechSegmenter")
    segmenter = Segmenter()
    raw = segmenter(str(vocals_wav))
    segments = []
    for label, start, end in raw:
        label_norm = str(label).lower()
        kind = "speech" if label_norm in SPEECH_LABELS else "non_speech"
        segments.append({"start": float(start), "end": float(end), "label": label_norm, "kind": kind, "backend": "inaSpeechSegmenter"})
    return segments


def read_pcm16(path):
    with wave.open(str(path), "rb") as wav_f:
        channels = wav_f.getnchannels()
        rate = wav_f.getframerate()
        width = wav_f.getsampwidth()
        frames = wav_f.readframes(wav_f.getnframes())
    if channels != 1 or rate != 16000 or width != 2:
        raise RuntimeError("expected 16kHz mono pcm16 wav")
    return frames, rate


def energy_vad_segments(vocals_wav):
    log("running fallback energy VAD segmentation")
    frames, rate = read_pcm16(vocals_wav)
    import audioop
    frame_size = max(1, int(rate * CONFIG["energy_frame_ms"] / 1000))
    byte_size = frame_size * 2
    rms_values = []
    for offset in range(0, len(frames), byte_size):
        chunk = frames[offset:offset + byte_size]
        if len(chunk) < 2:
            continue
        rms_values.append(audioop.rms(chunk, 2))
    if not rms_values:
        return []
    sorted_rms = sorted(rms_values)
    noise_floor = sorted_rms[max(0, int(len(sorted_rms) * 0.25) - 1)]
    threshold = max(80, noise_floor * CONFIG["energy_threshold_ratio"])
    segments = []
    in_seg = False
    start_idx = 0
    for idx, rms in enumerate(rms_values):
        speech = rms >= threshold
        if speech and not in_seg:
            start_idx = idx
            in_seg = True
        elif not speech and in_seg:
            segments.append({"start": start_idx * frame_size / rate, "end": idx * frame_size / rate, "label": "speech_energy", "kind": "speech", "backend": "energy_vad", "rms_threshold": threshold})
            in_seg = False
    if in_seg:
        segments.append({"start": start_idx * frame_size / rate, "end": len(rms_values) * frame_size / rate, "label": "speech_energy", "kind": "speech", "backend": "energy_vad", "rms_threshold": threshold})
    return segments


def merge_speech_segments(segments):
    speech = [s for s in segments if s.get("kind") == "speech" and s["end"] > s["start"]]
    speech.sort(key=lambda item: item["start"])
    merged = []
    for item in speech:
        if item["end"] - item["start"] < CONFIG["min_speech_segment_seconds"]:
            continue
        if merged and item["start"] - merged[-1]["end"] <= CONFIG["merge_gap_seconds"]:
            merged[-1]["end"] = max(merged[-1]["end"], item["end"])
            merged[-1]["labels"].append(item.get("label", "speech"))
            continue
        merged.append({"start": item["start"], "end": item["end"], "kind": "speech", "labels": [item.get("label", "speech")], "backend": item.get("backend", "unknown")})
    return merged


def build_speech_audio(vocals_wav, output_wav, speech_segments):
    if not speech_segments:
        silence_like(vocals_wav, output_wav)
        return
    filters = []
    filters.append("[0:a]volume=0[base]")
    for idx, seg in enumerate(speech_segments):
        delay_ms = max(0, int(round(seg["start"] * 1000)))
        filters.append(f"[0:a]atrim=start={seg['start']:.3f}:end={seg['end']:.3f},asetpts=PTS-STARTPTS,adelay={delay_ms}|{delay_ms}[s{idx}]")
    mix_inputs = "[base]" + "".join(f"[s{idx}]" for idx in range(len(speech_segments)))
    filters.append(f"{mix_inputs}amix=inputs={len(speech_segments) + 1}:duration=first:dropout_transition=0[out]")
    run(["ffmpeg", "-y", "-i", str(vocals_wav), "-filter_complex", ";".join(filters), "-map", "[out]", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output_wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def choose_segments(vocals_wav):
    backend = CONFIG["segmentation_backend"].lower()
    if backend in ("auto", "inaspeechsegmenter", "ina"):
        try:
            return ina_segments(vocals_wav)
        except Exception as exc:
            log(f"inaSpeechSegmenter failed: {exc}; fallback to energy VAD")
            if backend not in ("auto",):
                raise
    return energy_vad_segments(vocals_wav)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-video", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--audio-wav", required=True)
    parser.add_argument("--asr-audio-wav", required=True)
    parser.add_argument("--vocals-wav", required=True)
    parser.add_argument("--no-vocals-wav", required=True)
    parser.add_argument("--speech-regions-json", required=True)
    parser.add_argument("--report-json", required=True)
    args = parser.parse_args()

    if not CONFIG["enabled"]:
        log("disabled; extracting original audio for ASR fallback")
        ffmpeg_extract(args.input_video, args.audio_wav)
        shutil.copy2(args.audio_wav, args.asr_audio_wav)
        shutil.copy2(args.audio_wav, args.vocals_wav)
        silence_like(args.audio_wav, args.no_vocals_wav)
        report = {"config": CONFIG, "enabled": False, "fallback": "original_audio"}
        Path(args.speech_regions_json).write_text(json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8")
        Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    log("extracting mono 16k audio with ffmpeg")
    ffmpeg_extract(args.input_video, args.audio_wav)
    demucs_input = work_dir / "demucs_input.wav"
    log("extracting stereo 48k audio for Demucs")
    ffmpeg_extract_demucs_input(args.input_video, demucs_input)
    demucs_report = demucs_separate(demucs_input, work_dir, Path(args.vocals_wav), Path(args.no_vocals_wav))
    raw_segments = choose_segments(Path(args.vocals_wav))
    speech_segments = merge_speech_segments(raw_segments)
    log(f"speech segments kept: {len(speech_segments)}; raw segments: {len(raw_segments)}")
    build_speech_audio(Path(args.vocals_wav), Path(args.asr_audio_wav), speech_segments)
    total_dur = duration_seconds(args.audio_wav)
    speech_dur = sum(max(0.0, s["end"] - s["start"]) for s in speech_segments)
    report = {
        "config": CONFIG,
        "input_duration_seconds": total_dur,
        "speech_duration_seconds": speech_dur,
        "ignored_duration_seconds": max(0.0, total_dur - speech_dur),
        "demucs": demucs_report,
        "raw_segments": raw_segments,
        "speech_segments": speech_segments,
        "notes": [
            "ASR audio contains only detected speech/dialogue regions concatenated from vocals stem.",
            "Non-speech regions are silenced while preserving the original timeline for Whisper timestamps.",
            "Music/noise/singing/lyric-like non-speech regions are excluded from Whisper input.",
        ],
    }
    Path(args.speech_regions_json).write_text(json.dumps(speech_segments, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.report_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"done: speech={speech_dur:.2f}s ignored={max(0.0, total_dur - speech_dur):.2f}s")


if __name__ == "__main__":
    main()

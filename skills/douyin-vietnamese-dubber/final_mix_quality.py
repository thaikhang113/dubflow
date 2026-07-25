#!/usr/bin/env python3
"""Final-mix policy and quality reporting for the Vietnamese dub pipeline.

The helpers deliberately keep policy independent from ``run.sh`` so the mix,
tail, and local-freeze decisions can be regression-tested without rendering a
video.  It never edits media; ffmpeg remains the only renderer.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


TRUE_VALUES = {"1", "true", "yes", "on"}
CANONICAL_AUDIO_STAGE_PREFIXES = ("tts_", "voice_", "final_")


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in TRUE_VALUES


def _as_float(value: object, default: float, low: float | None = None, high: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if low is not None:
        result = max(low, result)
    if high is not None:
        result = min(high, result)
    return result


def _fmt(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def canonical_sample_rate_error(stage: str, sample_rate: int, expected_sample_rate: int = 48000) -> str | None:
    """Return an error for canonical TTS/final stages with the wrong sample rate."""
    stage_name = str(stage or "")
    if not stage_name.startswith(CANONICAL_AUDIO_STAGE_PREFIXES):
        return None
    actual = int(sample_rate or 0)
    expected = int(expected_sample_rate or 48000)
    if actual == expected:
        return None
    return (
        f"TTS_CANONICAL_SAMPLE_RATE_MISMATCH stage={stage_name} "
        f"expected={expected} actual={actual}"
    )

def build_final_mix_policy(env: Mapping[str, object]) -> dict[str, Any]:
    """Return safe, explicit B3 defaults without changing legacy sync mode."""
    return {
        "sync_mode": str(env.get("SYNC_MODE") or "balanced_dub"),
        "final_sample_rate": int(_as_float(env.get("FINAL_AUDIO_SAMPLE_RATE"), 48000, 8000, 192000)),
        "final_channels": int(_as_float(env.get("FINAL_AUDIO_CHANNELS"), 2, 1, 8)),
        "voice_volume": _as_float(env.get("VOICE_VOLUME"), 1.25, 0.0, 4.0),
        "music_bed_volume": _as_float(env.get("MUSIC_BED_VOLUME"), 0.12, 0.0, 2.0),
        "enable_bgm_ducking": _as_bool(env.get("ENABLE_BGM_DUCKING"), True),
        "bgm_duck_amount": _as_float(env.get("BGM_DUCK_AMOUNT"), 2.0, 1.0, 8.0),
        "final_loudness_target": _as_float(env.get("FINAL_LOUDNESS_TARGET"), -18.0, -30.0, -10.0),
        "final_true_peak_limit": _as_float(env.get("FINAL_TRUE_PEAK_LIMIT"), -1.5, -9.0, -0.1),
        "enable_final_loudness_normalization": _as_bool(env.get("ENABLE_FINAL_LOUDNESS_NORMALIZATION"), True),
        "allow_final_trim": _as_bool(env.get("ALLOW_FINAL_TRIM"), False),
        "strict_quality_gate": _as_bool(env.get("STRICT_QUALITY_GATE"), False),
        "allow_video_retime": _as_bool(env.get("ALLOW_VIDEO_RETIME"), False),
        "allow_freeze_frame": _as_bool(env.get("ALLOW_FREEZE_FRAME"), False),
        "max_freeze_per_segment_ms": int(_as_float(env.get("MAX_FREEZE_PER_SEGMENT_MS"), 500, 0, 10000)),
        "max_freeze_per_scene_ms": int(_as_float(env.get("MAX_FREEZE_PER_SCENE_MS"), 1200, 0, 60000)),
        "max_output_duration_increase": _as_float(env.get("MAX_OUTPUT_DURATION_INCREASE"), 10.0, 0.0, 100.0),
    }


def _master_filters(policy: Mapping[str, Any]) -> str:
    filters: list[str] = []
    if policy["enable_final_loudness_normalization"]:
        filters.append(
            "loudnorm=I={}:TP={}:LRA=11".format(
                _fmt(policy["final_loudness_target"]), _fmt(policy["final_true_peak_limit"])
            )
        )
    # 0.841 ~= -1.5 dBFS: limiter is only a ceiling, not a voice compressor.
    filters.append("alimiter=limit=0.841:level=false")
    # loudnorm can internally upsample for true-peak measurement; force the
    # configured delivery master afterwards so no 192 kHz intermediate leaks
    # into the AAC mux.
    filters.append("aformat=sample_rates={}:channel_layouts=stereo".format(policy.get("final_sample_rate", 48000)))
    return ",".join(filters)


def stereo_mix_filter(
    voice_volume: float,
    music_volume: float,
    ducking: bool,
    duck_amount: float,
    *,
    voice_input: str = "1:a",
    bed_input: str = "2:a",
    sample_rate: int = 48000,
    final_loudness_target: float = -18.0,
    final_true_peak_limit: float = -1.5,
    enable_loudness: bool = True,
) -> str:
    """Build a true-stereo ffmpeg graph: voice center + preserved stereo bed."""
    policy = {
        "enable_final_loudness_normalization": enable_loudness,
        "final_loudness_target": final_loudness_target,
        "final_true_peak_limit": final_true_peak_limit,
        "final_sample_rate": sample_rate,
    }
    voice = (
        f"[{voice_input}]aformat=sample_rates={sample_rate}:channel_layouts=mono,"
        f"volume={_fmt(voice_volume)},pan=stereo|c0=c0|c1=c0[voice]"
    )
    bed = (
        f"[{bed_input}]aformat=sample_rates={sample_rate}:channel_layouts=stereo,"
        f"volume={_fmt(music_volume)}[bed_pre]"
    )
    if ducking:
        # Voice is split for mix and a side-chain detector.  Mild ratio and
        # long release avoid the audible pumping of abrupt volume automation.
        return ";".join(
            [
                voice,
                bed,
                "[voice]asplit=2[voice_mix][voice_sidechain]",
                "[bed_pre][voice_sidechain]sidechaincompress=threshold=0.035:ratio={}:attack=35:release=450[bed]".format(
                    _fmt(duck_amount)
                ),
                "[voice_mix][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,{}[aout]".format(
                    _master_filters(policy)
                ),
            ]
        )
    return ";".join(
        [
            voice,
            bed,
            "[voice][bed_pre]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,{}[aout]".format(
                _master_filters(policy)
            ),
        ]
    )


def voice_only_filter(
    voice_volume: float,
    *,
    voice_input: str = "1:a",
    sample_rate: int = 48000,
    final_loudness_target: float = -18.0,
    final_true_peak_limit: float = -1.5,
    enable_loudness: bool = True,
) -> str:
    policy = {
        "enable_final_loudness_normalization": enable_loudness,
        "final_loudness_target": final_loudness_target,
        "final_true_peak_limit": final_true_peak_limit,
        "final_sample_rate": sample_rate,
    }
    return (
        f"[{voice_input}]aformat=sample_rates={sample_rate}:channel_layouts=mono,"
        f"volume={_fmt(voice_volume)},pan=stereo|c0=c0|c1=c0,{_master_filters(policy)}[aout]"
    )


def decide_video_fit(
    *,
    video_duration: float | None = None,
    voice_duration: float | None = None,
    video_seconds: float | None = None,
    voice_seconds: float | None = None,
    allow_video_retime: bool,
    allow_freeze_frame: bool,
    scene_safe: bool = False,
    max_freeze_per_segment_ms: int,
    max_freeze_per_scene_ms: int,
    max_output_duration_increase: float,
    allow_final_trim: bool = False,
    strict_quality_gate: bool = False,
) -> dict[str, Any]:
    """Return a bounded local-tail decision; never request global setpts.

    The current renderer has no scene-aware retimer.  Therefore the only
    implemented opt-in local operation is a bounded *tail* freeze.  Larger
    mismatches remain needs-attention instead of silently truncating speech.
    """
    # ``*_seconds`` names keep the pure helper pleasant to use in tests while
    # the CLI retains the duration-oriented option names.
    video = max(0.0, float(video_duration if video_duration is not None else (video_seconds or 0.0)))
    voice = max(0.0, float(voice_duration if voice_duration is not None else (voice_seconds or 0.0)))
    overhang_ms = max(0.0, (voice - video) * 1000.0)
    increase_percent = (overhang_ms / (video * 10.0)) if video > 0 else 0.0
    plan: dict[str, Any] = {
        "video_duration": round(video, 3),
        "voice_duration": round(voice, 3),
        "voice_overhang_ms": round(overhang_ms, 1),
        "segment_retime_ms": 0,
        "freeze_ms": 0,
        "output_duration_increase_percent": round(increase_percent, 3),
        "allow_final_trim": bool(allow_final_trim),
        "strict_quality_gate": bool(strict_quality_gate),
        "global_retime": False,
        "scene_safe": bool(scene_safe),
        "final_trim_warning": False,
    }
    if overhang_ms <= 0.01:
        return plan | {
            "action": "none",
            "mux_target_duration": round(video, 3),
            "message": "VOICE_MUX_GATE_OK: voice fits input video timeline",
        }

    max_freeze_ms = min(max(0, int(max_freeze_per_segment_ms)), max(0, int(max_freeze_per_scene_ms)))
    can_freeze = (
        allow_video_retime
        and allow_freeze_frame
        and scene_safe
        and overhang_ms > 0.01
        and overhang_ms <= max_freeze_ms
        and increase_percent <= max(0.0, float(max_output_duration_increase))
    )
    if can_freeze:
        return plan | {
            "action": "tail_freeze_local",
            "freeze_ms": round(overhang_ms, 1),
            "mux_target_duration": round(voice, 3),
            "message": "VOICE_MUX_LOCAL_TAIL_FREEZE: explicit feature flags enabled; no global retime",
        }
    if allow_final_trim:
        return plan | {
            "action": "trim_explicitly_allowed",
            "mux_target_duration": round(video, 3),
            "final_trim_warning": True,
            "message": "VOICE_MUX_TRIM_EXPLICITLY_ALLOWED: ALLOW_FINAL_TRIM=1; report warning required",
        }
    return plan | {
        "action": "needs_attention_no_trim",
        "mux_target_duration": round(video, 3),
        "final_trim_warning": True,
        "message": "VOICE_MUX_NEEDS_ATTENTION_NO_TRIM: voice overhang cannot use the opt-in bounded local freeze",
    }


def _probe_audio(path: str) -> dict[str, Any]:
    if not path or not Path(path).is_file():
        return {"file_path": path, "available": False}
    try:
        raw = subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=sample_rate,channels,codec_name,channel_layout:format=duration",
                "-of", "json", path,
            ], text=True
        )
        data = json.loads(raw)
        stream = (data.get("streams") or [{}])[0]
        return {
            "file_path": path,
            "available": True,
            "sample_rate": int(stream.get("sample_rate") or 0),
            "channels": int(stream.get("channels") or 0),
            "channel_layout": stream.get("channel_layout") or "",
            "codec": stream.get("codec_name") or "",
            "duration_ms": int(round(float((data.get("format") or {}).get("duration") or 0) * 1000)),
        }
    except Exception as exc:  # report diagnostics must not destroy a rendered output
        return {"file_path": path, "available": False, "probe_error": str(exc)}


def _loudness(path: str) -> dict[str, Any]:
    if not path or not Path(path).is_file():
        return {"available": False}
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-filter:a", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
            text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False,
        )
        blocks = re.findall(r"\{\s*\"input_i\".*?\}", proc.stderr, flags=re.S)
        if not blocks:
            return {"available": False, "error": "loudnorm analysis unavailable"}
        data = json.loads(blocks[-1])
        return {
            "available": True,
            "integrated_lufs": _as_float(data.get("input_i"), 0.0),
            "true_peak_dbfs": _as_float(data.get("input_tp"), 0.0),
            "loudness_range_lu": _as_float(data.get("input_lra"), 0.0),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _channel_warnings(final_path: str, final_probe: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    if final_probe.get("channels") != 2:
        warnings.append("FINAL_AUDIO_NOT_STEREO")
    # The exact dual-mono correlation measurement is intentionally deferred to
    # a future analyzer; we only warn when the final stream itself advertises a
    # mono layout.  This avoids false positives for centered voice + stereo BGM.
    if final_probe.get("channels") == 2 and final_probe.get("channel_layout") not in {"stereo", "2.0"}:
        warnings.append("FINAL_STEREO_LAYOUT_UNCONFIRMED")
    return warnings


def _rms_after_filter(path: str, filter_graph: str) -> dict[str, Any]:
    """Get a stable RMS diagnostic without decoding media into the repo."""
    if not path or not Path(path).is_file():
        return {"available": False}
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-filter:a", filter_graph, "-f", "null", "-"],
            text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False,
        )
        values = re.findall(r"RMS level dB:\s*(-?(?:inf|\d+(?:\.\d+)?))", proc.stderr, flags=re.I)
        if not values:
            return {"available": False, "error": "astats RMS unavailable"}
        raw = values[-1].lower()
        rms = -120.0 if "inf" in raw else float(raw)
        return {"available": True, "rms_dbfs": rms}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _stereo_diagnostics(path: str, probe: Mapping[str, Any]) -> dict[str, Any]:
    if probe.get("channels") != 2:
        return {"available": False, "reason": "not_stereo"}
    difference = _rms_after_filter(path, "pan=mono|c0=c0-c1,astats=metadata=1:reset=0")
    high_frequency = _rms_after_filter(path, "highpass=f=9000,astats=metadata=1:reset=0")
    # A near-silent L-R difference means duplicated mono, not a stereo bed.
    dual_mono = bool(difference.get("available") and float(difference.get("rms_dbfs", 0)) <= -65.0)
    # 16 kHz-derived speech normally has little usable energy above 8 kHz.
    hf_cutoff = bool(high_frequency.get("available") and float(high_frequency.get("rms_dbfs", 0)) <= -55.0)
    return {
        "available": bool(difference.get("available") or high_frequency.get("available")),
        "left_right_difference_rms_dbfs": difference.get("rms_dbfs"),
        "highpass_9khz_rms_dbfs": high_frequency.get("rms_dbfs"),
        "dual_mono_suspected": dual_mono,
        "high_frequency_cutoff_suspected": hf_cutoff,
    }


def _slow_fit_below_095_ratio(speed_report: str) -> dict[str, Any]:
    if not speed_report or not Path(speed_report).is_file():
        return {"available": False}
    try:
        values: list[float] = []
        with Path(speed_report).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                raw = row.get("post_atempo") or row.get("post_atempo_speed")
                try:
                    values.append(float(raw))
                except (TypeError, ValueError):
                    continue
        below = sum(value < 0.95 for value in values)
        return {
            "available": True,
            "segments": len(values),
            "below_095_segments": below,
            "below_095_ratio": round(below / len(values), 4) if values else 0.0,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def write_quality_report(
    *,
    stage_report: str,
    voice: str,
    music: str,
    final: str,
    timeline_report: str,
    fit_plan: str,
    speed_report: str,
    report_path: str,
    max_output_duration_increase: float,
) -> dict[str, Any]:
    """Build durable final diagnostics from probes and prior stage reports."""
    stages_data: dict[str, Any] = {}
    try:
        stages_data = json.loads(Path(stage_report).read_text(encoding="utf-8")) if Path(stage_report).is_file() else {}
    except Exception as exc:
        stages_data = {"stage_report_error": str(exc)}
    try:
        timeline = json.loads(Path(timeline_report).read_text(encoding="utf-8")) if Path(timeline_report).is_file() else {}
    except Exception:
        timeline = {}
    try:
        fit = json.loads(Path(fit_plan).read_text(encoding="utf-8")) if Path(fit_plan).is_file() else {}
    except Exception:
        fit = {}
    voice_probe, music_probe, final_probe = _probe_audio(voice), _probe_audio(music), _probe_audio(final)
    warnings = list(stages_data.get("warnings") or [])
    for stage in stages_data.get("stages") or []:
        if int(stage.get("sample_rate") or 0) == 16000 and str(stage.get("stage") or "").startswith(("ai33", "tts", "voice")):
            warnings.append("TTS_MASTER_DOWNGRADED_TO_ASR_FORMAT")
    voice_loudness, music_loudness, final_loudness = _loudness(voice), _loudness(music), _loudness(final)
    final_stereo = _stereo_diagnostics(final, final_probe)
    warnings.extend(_channel_warnings(final, final_probe))
    if final_stereo.get("dual_mono_suspected"):
        warnings.append("FINAL_STEREO_DUAL_MONO_SUSPECTED")
    if final_stereo.get("high_frequency_cutoff_suspected"):
        warnings.append("HIGH_FREQUENCY_CUTOFF_AROUND_8KHZ_SUSPECTED")
    slow_fit = _slow_fit_below_095_ratio(speed_report)
    if float(slow_fit.get("below_095_ratio") or 0.0) > 0.10:
        warnings.append("SLOW_FIT_BELOW_095_EXCEEDS_10_PERCENT")
    if float(fit.get("output_duration_increase_percent") or 0) > max_output_duration_increase:
        warnings.append("OUTPUT_DURATION_INCREASE_EXCEEDS_LIMIT")
    if fit.get("final_trim_warning"):
        warnings.append("FINAL_TRIM_WARNING")
    warnings = sorted(set(warnings))
    report = {
        "audio_stage_report": stages_data,
        "voice": voice_probe,
        "music": music_probe,
        "final": final_probe,
        "voice_loudness": voice_loudness,
        "music_loudness": music_loudness,
        "final_loudness": final_loudness,
        "true_peak": final_loudness.get("true_peak_dbfs"),
        "final_stereo_diagnostics": final_stereo,
        "slow_fit_below_095": slow_fit,
        "segment_retime_ms": fit.get("segment_retime_ms", 0),
        "freeze_ms": fit.get("freeze_ms", 0),
        "output_duration_increase_percent": fit.get("output_duration_increase_percent", 0),
        "final_trim_warning": bool(fit.get("final_trim_warning", False)),
        "timeline": timeline,
        "warnings": warnings,
    }
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg-filter", action="store_true")
    parser.add_argument("--voice-only-filter", action="store_true")
    parser.add_argument("--voice-input", default="1:a")
    parser.add_argument("--bed-input", default="2:a")
    parser.add_argument("--voice-volume", type=float, default=1.25)
    parser.add_argument("--music-volume", type=float, default=0.12)
    parser.add_argument("--ducking", default="1")
    parser.add_argument("--duck-amount", type=float, default=2.0)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--loudness-target", type=float, default=-18.0)
    parser.add_argument("--true-peak-limit", type=float, default=-1.5)
    parser.add_argument("--enable-loudness", default="1")
    parser.add_argument("--video-fit", action="store_true")
    parser.add_argument("--video-duration", type=float, default=0.0)
    parser.add_argument("--voice-duration", type=float, default=0.0)
    parser.add_argument("--allow-video-retime", default="0")
    parser.add_argument("--allow-freeze-frame", default="0")
    parser.add_argument("--scene-safe", default="0")
    parser.add_argument("--max-freeze-per-segment-ms", type=int, default=500)
    parser.add_argument("--max-freeze-per-scene-ms", type=int, default=1200)
    parser.add_argument("--max-output-duration-increase", type=float, default=10.0)
    parser.add_argument("--allow-final-trim", default="0")
    parser.add_argument("--strict-quality-gate", default="0")
    parser.add_argument("--plan-path")
    parser.add_argument("--stage-report")
    parser.add_argument("--voice")
    parser.add_argument("--music")
    parser.add_argument("--final")
    parser.add_argument("--timeline-report")
    parser.add_argument("--fit-plan")
    parser.add_argument("--speed-report")
    parser.add_argument("--report-path")
    args = parser.parse_args()
    if args.ffmpeg_filter:
        print(stereo_mix_filter(args.voice_volume, args.music_volume, _as_bool(args.ducking), args.duck_amount,
                                 voice_input=args.voice_input, bed_input=args.bed_input, sample_rate=args.sample_rate,
                                 final_loudness_target=args.loudness_target, final_true_peak_limit=args.true_peak_limit,
                                 enable_loudness=_as_bool(args.enable_loudness)))
        return 0
    if args.voice_only_filter:
        print(voice_only_filter(args.voice_volume, voice_input=args.voice_input, sample_rate=args.sample_rate,
                                final_loudness_target=args.loudness_target, final_true_peak_limit=args.true_peak_limit,
                                enable_loudness=_as_bool(args.enable_loudness)))
        return 0
    if args.video_fit:
        plan = decide_video_fit(
            video_duration=args.video_duration, voice_duration=args.voice_duration,
            allow_video_retime=_as_bool(args.allow_video_retime), allow_freeze_frame=_as_bool(args.allow_freeze_frame),
            scene_safe=_as_bool(args.scene_safe),
            max_freeze_per_segment_ms=args.max_freeze_per_segment_ms, max_freeze_per_scene_ms=args.max_freeze_per_scene_ms,
            max_output_duration_increase=args.max_output_duration_increase, allow_final_trim=_as_bool(args.allow_final_trim),
            strict_quality_gate=_as_bool(args.strict_quality_gate),
        )
        if args.plan_path:
            Path(args.plan_path).write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("{}\t{}\t{}\t{}".format(plan["action"], plan["mux_target_duration"], plan["freeze_ms"] / 1000.0, plan["message"]))
        return 0
    if args.report_path:
        report = write_quality_report(stage_report=args.stage_report or "", voice=args.voice or "", music=args.music or "",
                                      final=args.final or "", timeline_report=args.timeline_report or "", fit_plan=args.fit_plan or "",
                                      speed_report=args.speed_report or "",
                                      report_path=args.report_path, max_output_duration_increase=args.max_output_duration_increase)
        print("Final mix quality: warnings={}".format(",".join(report["warnings"]) or "none"))
        return 0
    parser.error("choose a filter, --video-fit, or --report-path")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())

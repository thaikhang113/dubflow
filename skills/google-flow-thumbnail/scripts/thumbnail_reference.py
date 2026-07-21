#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat

SCRIPT_DIR = Path(__file__).resolve().parent

REF_MIN_FRAMES = int(os.environ.get("THUMBNAIL_REF_MIN_FRAMES", "16"))
REF_MAX_FRAMES = int(os.environ.get("THUMBNAIL_REF_MAX_FRAMES", "48"))
REF_SAMPLE_INTERVAL = float(os.environ.get("THUMBNAIL_REF_SAMPLE_INTERVAL", "6"))
REF_VISION_SCORE = os.environ.get("THUMBNAIL_REF_VISION_SCORE", "1") != "0"

CDP_JSON_URLS = [u.strip() for u in os.environ.get(
    "THUMBNAIL_REFERENCE_CDP_JSON_URLS",
    "http://127.0.0.1:9222/json,http://127.0.0.1:9223/json,http://172.21.0.1:9223/json",
).split(",") if u.strip()]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def run_ffmpeg_frame(video: Path, second: float, out_path: Path) -> bool:
    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", f"{second:.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
            "-q:v", "2", str(out_path),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def video_duration(video: Path) -> float:
    try:
        raw = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nk=1:nw=1", str(video)
        ], text=True).strip()
        return max(0.1, float(raw))
    except Exception:
        return 60.0


def image_score(path: Path) -> float:
    try:
        img = Image.open(path).convert("RGB").resize((320, 180))
        gray = img.convert("L")
        contrast = ImageStat.Stat(gray).stddev[0]
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_score = ImageStat.Stat(edges).mean[0]
        saturation = ImageStat.Stat(img.convert("HSV").split()[1]).mean[0]
        return contrast * 1.4 + edge_score * 1.2 + saturation * 0.3
    except Exception:
        return -1.0


def extract_best_video_frame(video: Path, output: Path, debug_dir: Path) -> tuple[bool, dict]:
    if not video.exists():
        return False, {"source": "missing_input_mp4"}
    duration = video_duration(video)
    fractions = [0.08, 0.16, 0.25, 0.38, 0.50, 0.62, 0.75, 0.88]
    candidates = []
    frames_dir = debug_dir / "reference_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for idx, frac in enumerate(fractions, 1):
        second = min(max(0.2, duration * frac), max(0.2, duration - 0.2))
        frame = frames_dir / f"frame_{idx:02d}_{int(second)}s.jpg"
        if run_ffmpeg_frame(video, second, frame):
            candidates.append({"path": str(frame), "second": second, "score": image_score(frame)})
    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not candidates:
        return False, {"source": "video_frame_failed", "duration": duration}
    best = Path(candidates[0]["path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(best.read_bytes())
    return True, {"source": "video_frame", "duration": duration, "best": candidates[0], "candidates": candidates[:8]}


def parse_srt_cues(path: Path) -> list[tuple[float, str]]:
    """Return [(start_seconds, text)] cues for keyword matching. Empty if missing."""
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="ignore")
    cues: list[tuple[float, str]] = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        m = re.search(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", lines[0])
        if not m:
            continue
        h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
        start = h * 3600 + mi * 60 + s + ms / 1000.0
        text = " ".join(lines[1:]).strip()
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            cues.append((start, text))
    return cues


def cue_seconds_matching_keywords(srt_paths: list[Path], keywords: list[str]) -> list[float]:
    """Find subtitle cue start times whose text contains any keyword (case-insensitive)."""
    if not keywords:
        return []
    kws = [k.lower() for k in keywords if k and len(k) >= 2]
    if not kws:
        return []
    seconds: list[float] = []
    for path in srt_paths:
        for start, text in parse_srt_cues(path):
            low = text.lower()
            if any(k in low for k in kws):
                seconds.append(start)
    return seconds


def candidate_videos(output_dir: Path) -> list[Path]:
    base_dir = output_dir.parent
    candidates = [
        output_dir / "input.mp4",
        output_dir / "final_video_vi.mp4",
        base_dir / "VIDEO_MOI_NHAT.mp4",
        base_dir / "final_video_vi.mp4",
    ]
    meta_path = output_dir / "final_metadata.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        video = ((meta.get("outputs") or {}).get("video") or "")
        if video:
            candidates.insert(2, Path(video))
    except Exception:
        pass
    seen = set()
    result = []
    for item in candidates:
        key = str(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def candidate_images(output_dir: Path) -> list[Path]:
    base_dir = output_dir.parent
    candidates = [
        output_dir / "thumbnail.jpg",
        base_dir / "THUMBNAIL_MOI_NHAT.jpg",
        base_dir / "thumbnail.jpg",
    ]
    meta_path = output_dir / "final_metadata.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        thumb = ((meta.get("outputs") or {}).get("thumbnail") or "")
        if thumb:
            candidates.insert(1, Path(thumb))
    except Exception:
        pass
    seen = set()
    result = []
    for item in candidates:
        key = str(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def copy_image_reference(src: Path, output: Path) -> bool:
    try:
        img = Image.open(src).convert("RGB")
        img.thumbnail((1600, 1000))
        output.parent.mkdir(parents=True, exist_ok=True)
        img.save(output, "JPEG", quality=92)
        return output.exists() and output.stat().st_size > 0
    except Exception:
        return False


def fetch_url_to_jpeg(url: str, output: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        tmp = output.with_suffix(".download")
        tmp.write_bytes(data)
        img = Image.open(tmp).convert("RGB")
        img.thumbnail((1600, 1000))
        img.save(output, "JPEG", quality=92)
        tmp.unlink(missing_ok=True)
        return output.exists() and output.stat().st_size > 0
    except Exception:
        return False


def find_cdp_image_url(source_url: str) -> str:
    if not source_url:
        return ""
    for json_url in CDP_JSON_URLS:
        try:
            tabs = json.loads(urllib.request.urlopen(json_url, timeout=4).read().decode("utf-8"))
        except Exception:
            continue
        for tab in tabs:
            tab_url = str(tab.get("url") or "")
            if source_url and source_url.split("?")[0] not in tab_url:
                continue
            ws = tab.get("webSocketDebuggerUrl")
            # Keep v1 simple: avoid full CDP websocket dependency. Use tab title/favicon only if directly image-like.
            favicon = str(tab.get("faviconUrl") or "")
            if re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", favicon, re.I):
                return favicon
    return ""


def sample_schedule(duration: float, cue_seconds: list[float]) -> list[float]:
    """Build a list of sample times: uniform spread merged with cue-anchored times."""
    n_uniform = int(max(REF_MIN_FRAMES, min(REF_MAX_FRAMES, duration / max(1.0, REF_SAMPLE_INTERVAL))))
    n_uniform = max(REF_MIN_FRAMES, min(REF_MAX_FRAMES, n_uniform))
    times: list[float] = []
    for i in range(n_uniform):
        frac = (i + 0.5) / n_uniform
        times.append(min(max(0.2, duration * frac), max(0.2, duration - 0.2)))
    # Add ±1.5s around keyword cues, capped, dedup-sorted.
    for cue in cue_seconds[: REF_MAX_FRAMES]:
        for offset in (-1.5, 0.0, 1.5):
            t = cue + offset
            if 0.2 <= t <= max(0.2, duration - 0.2):
                times.append(t)
    times = sorted(set(round(t, 3) for t in times))
    return times[: REF_MAX_FRAMES + REF_MIN_FRAMES]


def _laplacian_variance(gray: Image.Image) -> float:
    # Use PIL edge filter as a cheap Laplacian proxy for variance of focus.
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).stddev[0])


def _region_edge_mean(edges: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Mean edge intensity in a normalized-region pixel box."""
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return 0.0
    crop = edges.crop((x1, y1, x2, y2))
    return float(ImageStat.Stat(crop).mean[0])


def score_frame(path: Path, angle_keywords: list[str]) -> dict:
    """CV heuristic scoring. Higher = better hero candidate."""
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return {"path": str(path), "score": -1.0, "reason": "open_failed"}
    work = img.resize((640, 360))
    w, h = work.size
    gray = work.convert("L")
    hsv = work.convert("HSV")

    stat_gray = ImageStat.Stat(gray)
    brightness = stat_gray.mean[0]
    contrast = stat_gray.stddev[0]
    saturation = ImageStat.Stat(hsv.split()[1]).mean[0]

    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_mean = ImageStat.Stat(edges).mean[0]
    blur = _laplacian_variance(gray)  # higher = sharper

    # Subject size: mass of edge energy in central 60% region.
    cx1, cy1 = int(w * 0.2), int(h * 0.15)
    cx2, cy2 = int(w * 0.8), int(h * 0.85)
    center_mass = _region_edge_mean(edges, (cx1, cy1, cx2, cy2))
    full_mass = edge_mean or 1.0
    subject_ratio = center_mass / full_mass

    # Face/silhouette clarity: edge energy in upper-center (where heads usually are).
    upper = _region_edge_mean(edges, (int(w * 0.25), int(h * 0.1), int(w * 0.75), int(h * 0.45)))

    # Text clutter: edge energy in bottom 12% (burned-in subs) and top 8%.
    bottom = _region_edge_mean(edges, (0, int(h * 0.88), w, h))
    top = _region_edge_mean(edges, (0, 0, w, int(h * 0.08)))
    clutter = (bottom + top) * 0.5

    # Relevance to angle keywords: real cue matching (caller sets near_keyword_cue),
    # nhưng score_frame không biết cue -> để 5.0 neutral, vision refine.
    relevance = 5.0
    # drama_energy: combo contrast + saturation + edge (cảm giác kịch tính).
    drama_energy = min(10.0, (contrast / 12.0) + (saturation / 24.0) + (edge_mean / 10.0))
    # text_safe_area: vùng ít edge ở góc (placeholder, layout tinh chi tiết).
    text_safe_area = max(0.0, 10.0 - (clutter / 8.0))

    score = (
        subject_ratio * 1.6
        + min(upper, 40) * 0.08
        + min(contrast, 80) * 0.05
        + min(blur, 60) * 0.06
        + min(saturation, 120) * 0.02
        + drama_energy * 0.4
        + text_safe_area * 0.3
        + (60 - min(brightness, 120)) * 0.0  # neutral on brightness
        - clutter * 0.5
    )
    return {
        "path": str(path),
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "saturation": round(saturation, 2),
        "edge_mean": round(edge_mean, 2),
        "blur": round(blur, 2),
        "subject_ratio": round(subject_ratio, 3),
        "upper_edge": round(upper, 2),
        "clutter": round(clutter, 2),
        "relevance": round(relevance, 2),
        "drama_energy": round(drama_energy, 3),
        "text_safe_area": round(text_safe_area, 3),
        "score": round(score, 3),
    }


def _score_provided_image(path: Path, source: str) -> dict:
    """Chấm ảnh provided (cover/reference) bằng cùng score_frame nhưng tag source riêng."""
    s = score_frame(path, [])
    s["source"] = source
    s["provided"] = True
    # Bonus nhỏ cho provided reference (cover thường đã là khung đẹp do nền tảng chọn),
    # nhưng KHÔNG đủ để tự thắng một frame kịch tính tốt hơn.
    s["score"] = round(s["score"] + 1.0, 3)
    return s


def _detect_provided_source(ref_path: Path) -> str:
    """Phân biệt cover Bilibili/Douyin vs reference user cung cấp tay."""
    name = str(ref_path).lower()
    if "bilibili" in name or "cover" in name or "thumbnail_reference_bilibili" in name:
        return "bilibili_cover"
    return "provided_reference"


def _vision_describe(image_path: Path) -> tuple[str, str]:
    """Call thumbnail_vision.py to get a short description + (we reuse its prompt_hint)."""
    script = SCRIPT_DIR / "thumbnail_vision.py"
    if not script.exists():
        return "", "vision_module_missing"
    analysis = image_path.with_suffix(".vision.json")
    prompt = image_path.with_suffix(".vision.txt")
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(image_path), str(analysis), str(prompt)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        return "", f"vision_error: {exc}"
    if proc.returncode != 0 or not analysis.exists():
        return "", f"vision_failed: {proc.stdout[-200:]}"
    try:
        data = json.loads(analysis.read_text(encoding="utf-8"))
    except Exception:
        return "", "vision_parse_failed"
    return str(data.get("prompt_hint") or data.get("raw_text") or ""), ""


def vision_rerank(top: list[dict], angle: str) -> list[dict]:
    """One vision call per top candidate (max 3) to refine emotion/relevance-to-angle."""
    if not REF_VISION_SCORE or not top:
        return top
    kws = [w for w in re.split(r"\s+", angle) if len(w) >= 2]
    for cand in top[:3]:
        hint, err = _vision_describe(Path(cand["path"]))
        cand["vision_hint"] = hint[:300]
        cand["vision_error"] = err
        if not hint:
            continue
        low = hint.lower()
        # Boost if vision sees a clear subject/face/emotion relevant to angle.
        boost = 0.0
        if any(w in low for w in ("face", "character", "subject", "person", "portrait", "nhân vật")):
            boost += 1.2
        if any(w in low for w in ("emotional", "dramatic", "intense", "kịch", "cảm xúc")):
            boost += 0.6
        if any(k.lower() in low for k in kws):
            boost += 1.0
        cand["vision_score"] = round(boost, 3)
        cand["score"] = round(cand["score"] + boost, 3)
    return top


def _write_reference_artifacts(output_dir: Path, scored: list[dict], hero: dict | None, sel: dict,
                               reference: Path, video: Path | None, duration: float) -> None:
    """Ghi artifact mới (reference_candidates/selection_report/primary/secondary/collage)
    + giữ artifact cũ (thumbnail_character_*, thumbnail_reference.jpg, meta).

    hero=None / scored rỗng được chấp nhận (case no-video + không có provided/fallback image):
    vẫn ghi reference_candidates.json + reference_selection_report.json với winner=None để
    downstream không crash và biết rõ không có reference.
    """
    # reference_candidates.json: toàn bộ candidate + score + source.
    (output_dir / "reference_candidates.json").write_text(json.dumps(
        {"candidates": scored[:30], "count": len(scored),
         "sources": sorted({c.get("source", "video_frame") for c in scored})},
        ensure_ascii=False, indent=2), encoding="utf-8")
    # primary/secondary copy (chỉ khi có hero).
    primary = output_dir / "reference_primary.jpg"
    secondary = output_dir / "reference_secondary.jpg"
    hero_path = Path(hero["path"]) if hero and hero.get("path") else None
    if hero_path and hero_path.exists():
        try:
            Image.open(hero_path).convert("RGB").save(primary, "JPEG", quality=92)
        except Exception:
            try:
                shutil.copyfile(hero_path, primary)
            except Exception:
                pass
    if hero_path and len(scored) >= 2:
        try:
            Image.open(Path(scored[1]["path"])).convert("RGB").save(secondary, "JPEG", quality=92)
        except Exception:
            pass
    # collage (primary + secondary cạnh nhau) nếu có 2.
    if primary.exists() and secondary.exists():
        try:
            a = Image.open(primary).convert("RGB").resize((640, 360))
            b = Image.open(secondary).convert("RGB").resize((640, 360))
            collage = Image.new("RGB", (1280, 360), (0, 0, 0))
            collage.paste(a, (0, 0)); collage.paste(b, (640, 0))
            collage.save(output_dir / "reference_collage.jpg", "JPEG", quality=90)
        except Exception:
            pass
    # reference_selection_report.json: winner + reason + source + score breakdown.
    if hero:
        winner_source = hero.get("source", "video_frame")
        winner_score = hero.get("score")
        if winner_source in ("bilibili_cover", "provided_reference"):
            reason = f"Cover/reference provided thắng vì score cao nhất ({winner_score})"
        else:
            reason = f"Frame video kịch tính nhất tại {hero.get('second','?')}s thắng (score {winner_score})"
    else:
        winner_source = "none"
        winner_score = None
        reason = ("Không có reference: không có video, không có provided image "
                  "(THUMBNAIL_REFERENCE_IMAGE) và không có fallback thumbnail image.")
    report = {
        "winner_source": winner_source,
        "winner_path": str(hero_path) if hero_path else "",
        "winner_score": winner_score,
        "reason": reason,
        "top5": [{k: c.get(k) for k in ("path", "source", "score", "second", "vision_score", "drama_energy")}
                 for c in scored[:5]],
        "reference_primary": str(primary) if primary.exists() else "",
        "reference_secondary": str(secondary) if secondary.exists() else "",
        "reference_collage": str(output_dir / "reference_collage.jpg") if (output_dir / "reference_collage.jpg").exists() else "",
        "legacy_reference": str(reference) if reference.exists() else "",
        "video": str(video) if video else "",
        "duration": duration,
    }
    (output_dir / "reference_selection_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def discover_character_references(output_dir: Path, angle: str, hook: str, debug_dir: Path) -> dict:
    """Sample many frames, score by CV, optional vision rerank for hero, write artifacts.

    Cover/reference provided (THUMBNAIL_REFERENCE_IMAGE) giờ là CANDIDATE (source tag),
    không còn short-circuit thắng tuyệt đối. Vẫn sample 16-48 frame + chấm điểm.
    Luôn ghi legacy thumbnail_reference.jpg (hero copy) + thumbnail_reference_meta.json.
    Thêm reference_candidates.json / reference_selection_report.json /
    reference_primary.jpg / reference_secondary.jpg / reference_collage.jpg.
    """
    refs_dir = output_dir / "thumbnail_character_refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    candidates_meta_path = output_dir / "thumbnail_character_candidates.json"
    selected_path = output_dir / "thumbnail_character_selected.json"
    reference = output_dir / "thumbnail_reference.jpg"
    meta_path = output_dir / "thumbnail_reference_meta.json"

    videos = [v for v in candidate_videos(output_dir) if v.exists()]
    fallback_reason = ""

    # Provided reference image -> candidate (KHÔNG short-circuit).
    provided_candidates: list[dict] = []
    provided_env = os.environ.get("THUMBNAIL_REFERENCE_IMAGE")
    if provided_env:
        ref = Path(provided_env)
        if ref.exists():
            src = _detect_provided_source(ref)
            # Copy provided vào refs_dir để score/compare đồng nhất + giữ bản gốc.
            provided_copy = refs_dir / f"provided_{src}.jpg"
            try:
                Image.open(ref).convert("RGB").save(provided_copy, "JPEG", quality=92)
            except Exception:
                shutil.copyfile(ref, provided_copy)
            if provided_copy.exists():
                provided_candidates.append(_score_provided_image(provided_copy, src))

    if not videos:
        fallback_reason = "no_input_video"
        sel = {
            "source": "missing_video", "hero_reference": "",
            "support_references": [], "score_breakdown": None,
            "fallback_reason": fallback_reason, "selected_angle": angle, "hook": hook,
        }
        selected_path.write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
        candidates_meta_path.write_text(json.dumps(
            {"candidates": provided_candidates, "fallback_reason": fallback_reason,
             "videos_checked": [str(v) for v in candidate_videos(output_dir)]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        # Provided candidate hoặc legacy image fallback cho reference.jpg.
        pool = provided_candidates + [{"path": str(im), "source": "existing_thumbnail_fallback"}
                                      for im in candidate_images(output_dir) if im.exists() and im.stat().st_size > 0]
        chosen = None
        for c in pool:
            if copy_image_reference(Path(c["path"]), reference):
                chosen = c; break
        if chosen:
            meta_path.write_text(json.dumps(
                {"source": chosen.get("source", "fallback"), "path": chosen["path"], "reference": str(reference)},
                ensure_ascii=False, indent=2), encoding="utf-8")
            sel["hero_reference"] = str(reference)
            sel["source"] = chosen.get("source", "fallback")
            selected_path.write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
            # Xuất artifact reference đầy đủ cho case chỉ có provided image / no video.
            _write_reference_artifacts(output_dir, pool, chosen, sel, reference, None, 0.0)
        else:
            # Không có provided image lẫn fallback image: vẫn xuất artifact reference
            # (winner=None) để downstream không crash và báo rõ không có reference.
            _write_reference_artifacts(output_dir, pool, None, sel, reference, None, 0.0)
        return sel

    video = videos[0]
    duration = video_duration(video)

    keywords = [w for w in re.split(r"\s+", hook) if len(w) >= 2] + [w for w in re.split(r"\s+", angle) if len(w) >= 2]
    srt_paths = [output_dir / "vietnamese.srt", output_dir / "original.srt", output_dir / "dub.srt"]
    cue_seconds = cue_seconds_matching_keywords(srt_paths, keywords)
    times = sample_schedule(duration, cue_seconds)

    scored: list[dict] = []
    for idx, t in enumerate(times, 1):
        frame = refs_dir / f"frame_{idx:02d}_{int(t)}s.jpg"
        if not run_ffmpeg_frame(video, t, frame):
            continue
        s = score_frame(frame, keywords)
        s["second"] = round(t, 3)
        s["near_keyword_cue"] = any(abs(t - c) <= 2.0 for c in cue_seconds)
        if s.get("near_keyword_cue"):
            s["relevance"] = 8.0
            s["score"] = round(s["score"] + 1.5, 3)
        scored.append(s)

    # Gộp provided candidates vào pool chấm điểm chung.
    scored = provided_candidates + scored

    if not scored:
        fallback_reason = "frame_extraction_failed"
        ok, _ = extract_best_video_frame(video, reference, debug_dir)
        if not ok:
            for image in candidate_images(output_dir):
                if image.exists() and copy_image_reference(image, reference):
                    break
        sel = {
            "source": "frame_extraction_failed", "hero_reference": str(reference) if reference.exists() else "",
            "support_references": [], "score_breakdown": None,
            "fallback_reason": fallback_reason, "selected_angle": angle, "hook": hook,
            "video": str(video), "duration": duration,
        }
        selected_path.write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
        candidates_meta_path.write_text(json.dumps(
            {"candidates": [], "fallback_reason": fallback_reason, "video": str(video), "duration": duration},
            ensure_ascii=False, indent=2), encoding="utf-8")
        if reference.exists():
            meta_path.write_text(json.dumps(
                {"source": "video_frame_fallback", "reference": str(reference), "source_video": str(video)},
                ensure_ascii=False, indent=2), encoding="utf-8")
        return sel

    scored.sort(key=lambda c: c["score"], reverse=True)
    candidates_meta_path.write_text(json.dumps(
        {"candidates": scored[:20], "count": len(scored), "video": str(video),
         "duration": duration, "cue_keyword_matches": len(cue_seconds)},
        ensure_ascii=False, indent=2), encoding="utf-8")

    # Vision rerank on top 3.
    top_for_vision = scored[:3]
    top_for_vision = vision_rerank([dict(c) for c in top_for_vision], angle)
    vision_by_path = {c["path"]: c for c in top_for_vision}
    for c in scored:
        if c["path"] in vision_by_path:
            c["score"] = vision_by_path[c["path"]]["score"]
            c["vision_hint"] = vision_by_path[c["path"]].get("vision_hint", "")
            c["vision_score"] = vision_by_path[c["path"]].get("vision_score", 0.0)
    scored.sort(key=lambda c: c["score"], reverse=True)

    hero = scored[0]
    hero_path = Path(hero["path"])
    try:
        Image.open(hero_path).convert("RGB").save(reference, "JPEG", quality=92)
    except Exception:
        shutil.copyfile(hero_path, reference)
    support = scored[1:4]
    hero_source = hero.get("source", "character_frame_discovery")
    sel_source = (hero_source if hero_source in ("bilibili_cover", "provided_reference")
                  else "character_frame_discovery")
    sel = {
        "source": sel_source,
        "hero_reference": str(reference),
        "hero_frame": str(hero_path),
        "support_references": [Path(c["path"]).name for c in support if Path(c["path"]).exists()],
        "score_breakdown": {
            "hero": {k: hero.get(k) for k in ("score", "source", "subject_ratio", "upper_edge", "blur", "clutter", "vision_score", "vision_hint", "drama_energy", "text_safe_area") if k in hero},
            "top": [{k: c.get(k) for k in ("path", "source", "score", "second", "near_keyword_cue", "vision_score", "drama_energy")} for c in scored[:6]],
        },
        "fallback_reason": "",
        "selected_angle": angle,
        "hook": hook,
        "video": str(video),
        "frame_count": len(scored),
    }
    selected_path.write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
    meta_path.write_text(json.dumps(
        {"source": sel_source, "reference": str(reference), "hero_frame": str(hero_path),
         "source_video": str(video), "selected_angle": angle,
         "hero_source": hero_source},
        ensure_ascii=False, indent=2), encoding="utf-8")
    _write_reference_artifacts(output_dir, scored, hero, sel, reference, video, duration)
    return sel


def create_reference(output_dir: Path) -> dict:
    debug_dir = output_dir / "google_flow_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    reference = output_dir / "thumbnail_reference.jpg"
    meta_path = output_dir / "thumbnail_reference_meta.json"
    source_url = read_text(output_dir / "source_input.txt")

    if os.environ.get("THUMBNAIL_REFERENCE_IMAGE"):
        ref = Path(os.environ["THUMBNAIL_REFERENCE_IMAGE"])
        if ref.exists():
            Image.open(ref).convert("RGB").save(reference, "JPEG", quality=92)
            meta = {"source": "user_reference_image", "path": str(ref), "reference": str(reference)}
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return meta

    image_url = find_cdp_image_url(source_url)
    if image_url and fetch_url_to_jpeg(image_url, reference):
        meta = {"source": "cdp_image", "image_url": image_url, "reference": str(reference)}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    for video in candidate_videos(output_dir):
        ok, meta = extract_best_video_frame(video, reference, debug_dir)
        if ok:
            meta["source_video"] = str(video)
            meta["reference"] = str(reference)
            meta["source_url"] = source_url
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return meta

    for image in candidate_images(output_dir):
        if image.exists() and image.stat().st_size > 0 and copy_image_reference(image, reference):
            meta = {"source": "existing_thumbnail_fallback", "source_image": str(image), "reference": str(reference), "source_url": source_url}
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return meta

    meta = {"source": "missing_video_and_thumbnail", "reference": "", "source_url": source_url, "checked_videos": [str(p) for p in candidate_videos(output_dir)], "checked_images": [str(p) for p in candidate_images(output_dir)]}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir")
    parser.add_argument("--mode", choices=["legacy", "discover"], default="discover",
                        help="discover: multi-frame CV+vision hero selection (default). legacy: old single best-frame.")
    parser.add_argument("--angle", default="", help="selected clickable angle for keyword cues")
    parser.add_argument("--hook", default="", help="selected hook text for keyword cues")
    args = parser.parse_args()
    out = Path(args.output_dir)
    debug_dir = out / "google_flow_debug"
    if args.mode == "legacy":
        meta = create_reference(out)
    else:
        meta = discover_character_references(out, args.angle, args.hook, debug_dir)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    ref = meta.get("hero_reference") or meta.get("reference") or ""
    return 0 if ref else 1


if __name__ == "__main__":
    raise SystemExit(main())

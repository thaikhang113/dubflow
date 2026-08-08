#!/usr/bin/env python3
import argparse
import asyncio
import copy
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

STATE_DIR = Path(os.environ.get("OPENCLAW_SERIES_STATE_DIR", "/home/haonguyen/.openclaw-series"))
STATE_FILE = STATE_DIR / "series.json"
QUEUE_DIR = Path(os.environ.get("OPENCLAW_HOST_RUNNER_QUEUE_DIR", "/mnt/hdd500/video douyin vietsub/host-runner-queue"))
TOKEN_FILE = Path(os.environ.get("OPENCLAW_HOST_RUNNER_TOKEN_FILE", "/home/haonguyen/.openclaw-host-runner/token"))
DEFAULT_NINEROUTER_MODEL = os.environ.get("NINEROUTER_MODEL", "ollama/minimax-m3:cloud")
BILIBILI_CDP = Path(os.environ.get("BILIBILI_CDP_HELPER", "/home/haonguyen/.openclaw/workspace/skills/bilibili-vietnamese-dubber/scripts/bilibili_cdp.py"))
CDP_URL = os.environ.get("BILIBILI_CDP_URL", "http://127.0.0.1:9222")
DUBBER_SKILL_DIR = Path(os.environ.get("OPENCLAW_DUBBER_SKILL_DIR", "/home/haonguyen/.openclaw/workspace/skills/douyin-vietnamese-dubber"))
if str(DUBBER_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(DUBBER_SKILL_DIR))
try:
    import voice_registry as voice_registry_lib
except Exception:
    voice_registry_lib = None

VIDEO_RE = re.compile(r"https?://(?:www\.)?bilibili\.com/video/[A-Za-z0-9]+")
CHANNEL_RE = re.compile(r"https?://space\.bilibili\.com/\d+")
SAFE_MEMORY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
GENRE_TAG_ALIASES = {
    "tu_tien": "tu_tien",
    "tutien": "tu_tien",
    "tu tien": "tu_tien",
    "仙侠": "tu_tien",
    "修仙": "tu_tien",
    "hoc_duong": "hoc_duong",
    "hocduong": "hoc_duong",
    "hoc duong": "hoc_duong",
    "校园": "hoc_duong",
    "giang_ho": "giang_ho",
    "giangho": "giang_ho",
    "giang ho": "giang_ho",
    "江湖": "giang_ho",
    "hien_dai": "hien_dai",
    "hiendai": "hien_dai",
    "hien dai": "hien_dai",
    "现代": "hien_dai",
    "co_trang": "co_trang",
    "cotrang": "co_trang",
    "co trang": "co_trang",
    "古装": "co_trang",
}


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_duration_seconds(value):
    """Parse numeric, HH:MM:SS, or MM:SS durations into seconds."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if value >= 0 else None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return float(raw) if "." in raw else int(raw)
    parts = raw.split(":")
    if len(parts) not in {2, 3} or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        if seconds >= 60:
            return None
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def migrate_state_v2(data):
    """Return a v2-compatible copy while retaining unrecognized legacy fields."""
    if not isinstance(data, dict):
        data = {}
    migrated = copy.deepcopy(data)
    series_list = migrated.get("series")
    if not isinstance(series_list, list):
        series_list = []
        migrated["series"] = series_list
    for series in series_list:
        if not isinstance(series, dict):
            continue
        episodes = series.get("episodes")
        if not isinstance(episodes, list):
            episodes = []
            series["episodes"] = episodes
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            episode.setdefault("url", "")
            episode.setdefault("episode_number", None)
            if episode.get("duration_seconds") is None:
                episode["duration_seconds"] = parse_duration_seconds(episode.get("duration"))
            status = episode.get("status") or "ready"
            episode["status"] = status
            default_stage_status = status if status in {"queued", "running", "done", "error"} else "not_started"
            episode.setdefault("download_status", default_stage_status)
            episode.setdefault("localization_status", default_stage_status)
            episode.setdefault("last_job_id", None)
            episode.setdefault("last_output_dir", None)
            episode.setdefault("final_video_path", None)
            if not isinstance(episode.get("compilations_used"), list):
                episode["compilations_used"] = []
    migrated["version"] = 2
    return migrated


def load_state():
    if not STATE_FILE.exists():
        return migrate_state_v2({})
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return migrate_state_v2(data)
    except Exception as exc:
        raise RuntimeError(f"SeriesStateInvalid: không đọc được {STATE_FILE}: {exc}") from exc


def save_state(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(migrate_state_v2(data), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def print_json(data):
    print(json.dumps(data, ensure_ascii=True, indent=2))


def make_series_id(name, keyword, source_url):
    raw = f"{name}|{keyword}|{source_url}".encode("utf-8")
    return "series-" + hashlib.sha1(raw).hexdigest()[:12]


def find_series(data, series_id):
    for item in data.get("series", []):
        if item.get("series_id") == series_id:
            return item
    return None


def normalize_video_url(url):
    match = VIDEO_RE.search(url or "")
    return match.group(0) if match else ""


def normalize_channel_url(url):
    match = CHANNEL_RE.search(url or "")
    return match.group(0) if match else ""


def normalize_bgm_mode(mode):
    value = (mode or "auto").strip().lower()
    if value in ("auto", "duck", "none", "demucs"):
        return value
    return "auto"


def fold_ascii(value):
    value = (value or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", value or "")
    return text.encode("ascii", "ignore").decode("ascii").lower()


def normalize_memory_id(value):
    value = (value or "").strip()
    return value if SAFE_MEMORY_ID_RE.match(value) else ""


def normalize_genre_tag(value):
    raw = (value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower().replace("-", "_")
    folded = fold_ascii(raw).replace("-", "_")
    candidates = {
        lowered,
        lowered.replace("_", " "),
        folded,
        folded.replace("_", " "),
        re.sub(r"[^a-z0-9]+", "_", folded).strip("_"),
    }
    for item in candidates:
        if item in GENRE_TAG_ALIASES:
            return GENRE_TAG_ALIASES[item]
    slug = re.sub(r"[^a-z0-9_]+", "_", folded).strip("_")
    return slug if slug in set(GENRE_TAG_ALIASES.values()) else ""


def normalize_genre_tags(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                data = json.loads(text)
                items = data if isinstance(data, list) else [text]
            except Exception:
                items = re.split(r"[,;]+", text)
        else:
            items = re.split(r"[,;]+", text)
    out = []
    seen = set()
    for item in items:
        tag = normalize_genre_tag(str(item))
        if tag and tag not in seen:
            out.append(tag)
            seen.add(tag)
    return out


def infer_genre_tags(*values):
    haystack_raw = " ".join(v or "" for v in values)
    haystack = (haystack_raw.lower() + " " + fold_ascii(haystack_raw)).replace("-", " ")
    out = []
    seen = set()
    for alias, tag in GENRE_TAG_ALIASES.items():
        alias_text = alias.lower().replace("_", " ")
        if alias_text and alias_text in haystack and tag not in seen:
            out.append(tag)
            seen.add(tag)
    return out


def normalize_voice(voice):
    kokoro_default = os.environ.get("KOKORO_DEFAULT_VOICE", "mai_linh")
    resona_default = os.environ.get("RESONA_DEFAULT_VOICE_ID", "ZJEpWoOyElCKuEljNTkm")
    ai33_mai_phuong = os.environ.get("AI33_MAI_PHUONG_VOICE_ID", "vbee_hn_female_maiphuong_vdts_48k-fhg")
    ai33_phanh = os.environ.get("AI33_PHANH_VOICE_ID", "elevenlabs_UuMSQK8FdLwaY2M8ZAnh")
    ai33_default = os.environ.get("AI33_DEFAULT_VOICE_ID", ai33_mai_phuong)
    default_voice = ""
    if voice_registry_lib is not None:
        try:
            default_voice = voice_registry_lib.default_voice()
        except Exception:
            default_voice = ""
    default_voice = default_voice or os.environ.get("OPENCLAW_DEFAULT_TTS_VOICE", f"ai33:{ai33_default}")
    if default_voice == f"ai33:{ai33_phanh}" and os.environ.get("OPENCLAW_KEEP_LEGACY_PHANH_DEFAULT") != "1" and voice_registry_lib is None:
        default_voice = f"ai33:{ai33_mai_phuong}"
    raw_voice = str(voice or default_voice).strip()
    value = raw_voice.lower()
    folded_value = fold_ascii(value)
    kokoro_voices = {
        "diem_trinh", "duc_an", "duc_duy", "hung_thinh", "mai_linh", "mai_loan",
        "manh_dung", "my_yen", "ngoc_huyen", "phat_tai", "storyvert",
        "thanh_dat", "thuc_trinh", "tuan_ngoc",
    }
    if value == "":
        return default_voice
    if value == "resona":
        return f"resona:{resona_default}"
    if value.startswith("resona:"):
        return raw_voice
    if value in {"ai33", "vbee", "vbee-maiphuong", "vbee-mai-phuong", "maiphuong", "mai-phuong", "mai_phuong", "ngochuyen", "vbee-ngochuyen", "elevenlabs", "elevenlabs-phanh", "eleven-phanh", "phanh", "phan"} or folded_value in {"ngoc huyen", "ngoc-huyen", "ngoc_huyen"} or value.startswith("ai33:") or value.startswith("elevenlabs_") or value.startswith("vbee_"):
        if voice_registry_lib is not None:
            try:
                if folded_value in {"ngoc huyen", "ngoc-huyen", "ngoc_huyen", "ngochuyen"}:
                    raw_voice = "ngoc huyen"
                return voice_registry_lib.normalize_ai33_voice(raw_voice)
            except Exception as exc:
                raise SystemExit(f"SeriesVoiceInvalid: {exc}") from exc
        if value in {"ai33", "vbee", "vbee-maiphuong", "vbee-mai-phuong", "maiphuong", "mai-phuong", "mai_phuong"}:
            return f"ai33:{ai33_mai_phuong}"
        if value in {"elevenlabs", "elevenlabs-phanh", "eleven-phanh", "phanh", "phan"}:
            return f"ai33:{ai33_phanh}"
        if folded_value in {"ngoc huyen", "ngoc-huyen", "ngoc_huyen", "ngochuyen"}:
            return "ai33:vbee_hn_female_ngochuyen_full_48k-fhg"
        if value.startswith("ai33:"):
            return raw_voice
        return f"ai33:{raw_voice or ai33_default}"
    if value == "kokoro":
        return f"kokoro:{kokoro_default}"
    if value.startswith("kokoro:"):
        return raw_voice
    if value in kokoro_voices:
        return f"kokoro:{value}"
    if value in {"nu", "nữ", "female", "woman"}:
        return "nu"
    if value in {"nam", "male", "man"}:
        return "nam"
    if value.startswith("capcut:"):
        raise SystemExit("SeriesVoiceInvalid: CapCut TTS đã tắt khỏi pipeline. Dùng kokoro:<voice>, ai33/maiphuong/phanh, resona, nam, nu hoặc vi-vn-*")
    if value.startswith("vi-vn-"):
        return raw_voice
    raise SystemExit("SeriesVoiceInvalid: voice phải là kokoro:<voice>, AI33 registry, resona, nam, nu hoặc vi-vn-*")


def parse_episode_numbers(title):
    title = title or ""
    numbers = []
    if re.search(r"\b序\b|《[^》]+》序|^序[:：]", title):
        numbers.append(0)
    patterns = [
        r"(?:第|EP|Ep|ep|集|话|話|tập|tap)\s*(\d{1,4})",
        r"(\d{1,4})\s*(?:集|话|話|\.mp4)",
        r"》\s*[:：|｜]?\s*(\d{1,4})\s*(?:集|话|話)?",
        r"[^\d](\d{1,4})\s*[:：]",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, title, flags=re.IGNORECASE):
            numbers.append(int(match.group(1)))
    dedup = []
    seen = set()
    for num in numbers:
        if num not in seen:
            seen.add(num)
            dedup.append(num)
    return dedup


async def fetch_bilibili_items(source_url, keyword, limit=500):
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise RuntimeError(f"Playwright chưa sẵn sàng: {exc}") from exc
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=10000)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = None
        try:
            video_url = normalize_video_url(source_url)
            if video_url:
                page = await context.new_page()
                await page.goto(video_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)
            else:
                pages = []
                for existing in context.pages:
                    try:
                        if "bilibili.com/video/" in existing.url:
                            pages.append(existing)
                    except Exception:
                        pass
                page = pages[0] if pages else None
                for candidate in pages:
                    title = await candidate.title()
                    if keyword and keyword in title:
                        page = candidate
                        break
            if page is None:
                raise RuntimeError("BilibiliPlaylistPageMissing: Không thấy tab video Bilibili trong Chrome CDP")
            await page.wait_for_timeout(1200)
            dom = await page.evaluate(r"""
            (limit) => {
              const norm = (u) => {
                if (!u) return '';
                if (u.startsWith('//')) return 'https:' + u;
                if (u.startsWith('/')) return 'https://www.bilibili.com' + u;
                return u;
              };
              const cleanVideo = (u) => {
                const m = norm(u).match(/https?:\/\/(?:www\.)?bilibili\.com\/video\/[A-Za-z0-9]+/);
                return m ? m[0] : '';
              };
              const items = [];
              const seen = new Set();
              const push = (url, title, duration, source) => {
                url = cleanVideo(url);
                title = String(title || '').replace(/\s+/g, ' ').trim();
                const key = url + '|' + title;
                if ((!url && !title) || seen.has(key)) return;
                seen.add(key);
                items.push({url, title, duration: String(duration || ''), source});
              };
              const selectors = ['.video-pod a[href*="/video/"]','.video-pod .simple-base-item','.video-sections-content-list a[href*="/video/"]','.base-video-sections a[href*="/video/"]','.video-section-list a[href*="/video/"]','.video-pod__item','.pod-item'];
              for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                  const a = el.tagName === 'A' ? el : el.querySelector('a[href*="/video/"]');
                  push((a && (a.getAttribute('href') || a.href)) || '', el.innerText || el.textContent || (a && a.getAttribute('title')) || '', '', 'cdp_playlist_dom');
                }
              }
              const state = window.__INITIAL_STATE__ || {};
              const walk = (node, depth=0) => {
                if (!node || depth > 8) return;
                if (Array.isArray(node)) { for (const child of node) walk(child, depth + 1); return; }
                if (typeof node !== 'object') return;
                const bvid = node.bvid || node.bv_id || (node.arc && node.arc.bvid) || '';
                const title = node.title || (node.arc && node.arc.title) || '';
                const duration = node.duration || (node.arc && node.arc.duration) || (node.page && node.page.duration) || '';
                if (bvid && title) push('https://www.bilibili.com/video/' + bvid, title, duration, 'cdp_playlist_state');
                for (const [key, value] of Object.entries(node)) {
                  if (/section|episode|archives|list|item|ugc|season/i.test(key)) walk(value, depth + 1);
                }
              };
              walk(state.sectionsInfo || state.videoData || state, 0);
              return {url: location.href, title: document.title, items: items.slice(0, limit)};
            }
            """, limit)
            return dom
        finally:
            try:
                if page is not None and normalize_video_url(source_url):
                    await page.close()
            except Exception:
                pass
            await browser.close()


def items_to_episodes(items, keyword):
    episodes = []
    seen = set()
    for raw in items:
        title = raw.get("title") or ""
        nums = parse_episode_numbers(title)
        if keyword and keyword not in title and not nums:
            continue
        if not nums:
            continue
        for num in nums[:1]:
            url = normalize_video_url(raw.get("url") or "")
            if not url:
                continue
            key = (num, url)
            if key in seen:
                continue
            seen.add(key)
            episodes.append({
                "episode_number": num,
                "title": title,
                "url": url,
                "duration": raw.get("duration") or "",
                "source": raw.get("source") or "cdp_playlist",
                "status": "ready",
                "last_job_id": None,
                "last_output_dir": None,
            })
    episodes.sort(key=lambda item: (item.get("episode_number", 999999), item.get("title") or ""))
    return episodes


def cmd_list(_args):
    print_json(load_state())


def cmd_add(args):
    data = load_state()
    series_id = args.series_id or make_series_id(args.name, args.keyword, args.source_url)
    existing = find_series(data, series_id)
    genre_tags = normalize_genre_tags(args.genre_tags) or infer_genre_tags(args.name, args.keyword, args.source_url)
    if existing and not args.genre_tags and not genre_tags:
        genre_tags = normalize_genre_tags(existing.get("genre_tags") or [])
    payload = {
        "series_id": series_id,
        "platform": "bilibili",
        "name": args.name.strip(),
        "keyword": args.keyword.strip(),
        "genre_tags": genre_tags,
        "channel_url": normalize_channel_url(args.channel_url or args.source_url),
        "source_url": args.source_url.strip(),
        "episodes": [],
        "last_refresh_at": None,
        "last_error": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if existing:
        existing.update({k: v for k, v in payload.items() if k not in {"created_at", "episodes"}})
        result = existing
    else:
        data["series"].append(payload)
        result = payload
    save_state(data)
    print_json({"ok": True, "series": result})


def cmd_remove(args):
    data = load_state()
    before = len(data.get("series", []))
    data["series"] = [item for item in data.get("series", []) if item.get("series_id") != args.series_id]
    save_state(data)
    print_json({"ok": True, "removed": before - len(data["series"])})


OPERATIONAL_EPISODE_FIELDS = {
    "status", "download_status", "localization_status", "last_job_id",
    "last_output_dir", "final_video_path", "compilations_used",
}


def merge_discovered_episodes(existing_episodes, discovered_episodes):
    """Merge a discovery result by URL without discarding prior episode progress."""
    existing_by_url = {
        ep.get("url"): ep for ep in existing_episodes
        if isinstance(ep, dict) and ep.get("url")
    }
    merged = []
    seen_urls = set()
    for discovered in discovered_episodes:
        if not isinstance(discovered, dict):
            continue
        url = discovered.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        previous = existing_by_url.get(url)
        if previous:
            episode = dict(previous)
            episode.update(discovered)
            for field in OPERATIONAL_EPISODE_FIELDS:
                if field in previous:
                    episode[field] = copy.deepcopy(previous[field])
        else:
            episode = dict(discovered)
            episode["status"] = "new"
        merged.append(episode)
    for previous in existing_episodes:
        if isinstance(previous, dict) and previous.get("url") and previous["url"] not in seen_urls:
            merged.append(copy.deepcopy(previous))
            seen_urls.add(previous["url"])
    return migrate_state_v2({"series": [{"episodes": merged}]})["series"][0]["episodes"]


def cmd_refresh(args):
    data = load_state()
    series = find_series(data, args.series_id)
    if not series:
        raise SystemExit("SeriesNotFound: không thấy series_id")
    try:
        dom = asyncio.run(fetch_bilibili_items(series.get("source_url") or "", series.get("keyword") or "", args.limit))
        episodes = items_to_episodes(dom.get("items") or [], series.get("keyword") or "")
        if not episodes:
            series["last_error"] = "needs_attention: Không thấy tập trong playlist CDP; mở Chrome thật vào trang series/video gốc rồi thử lại."
        else:
            series["episodes"] = merge_discovered_episodes(series.get("episodes", []), episodes)
            series["last_error"] = None
        series["last_refresh_at"] = now_iso()
        series["updated_at"] = now_iso()
        save_state(data)
        print_json({"ok": True, "series": series, "source_title": dom.get("title"), "source_url": dom.get("url")})
    except Exception as exc:
        series["last_error"] = f"needs_attention: {exc}"
        series["updated_at"] = now_iso()
        save_state(data)
        print_json({"ok": False, "series": series, "error": series["last_error"]})
        raise SystemExit(20)


def normalize_ninerouter_model(value):
    model = (value or DEFAULT_NINEROUTER_MODEL).strip()
    return model or DEFAULT_NINEROUTER_MODEL


def queue_run_bilibili(url, voice, bgm_mode="auto", ninerouter_model=None, translation_series_id="", translation_genre_tags=None):
    token = TOKEN_FILE.read_text(encoding="utf-8").strip() if TOKEN_FILE.exists() else ""
    if not token:
        raise SystemExit("SeriesTokenMissing: thiếu host-runner token")
    job_id = time.strftime("run-bilibili-%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    request_dir = QUEUE_DIR / "requests"
    log_path = QUEUE_DIR / "logs" / f"{job_id}.req.log"
    request_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = request_dir / f"{job_id}.tmp"
    req = request_dir / f"{job_id}.req"
    model = normalize_ninerouter_model(ninerouter_model)
    memory_series_id = normalize_memory_id(translation_series_id)
    memory_genre_tags = ",".join(normalize_genre_tags(translation_genre_tags or []))
    tmp.write_text(
        f"ACTION=run-bilibili\nURL={url}\nVOICE_PRESET={voice}\nBGM_MODE={bgm_mode}\n"
        f"NINEROUTER_MODEL={model}\nTRANSLATION_SERIES_ID={memory_series_id}\n"
        f"TRANSLATION_GENRE_TAGS={memory_genre_tags}\nTOKEN={token}\n",
        encoding="utf-8",
    )
    tmp.replace(req)
    return {"ok": True, "queued": True, "job_id": job_id, "request": str(req), "log": str(log_path)}


def cmd_download(args):
    url = normalize_video_url(args.url)
    if not url:
        raise SystemExit("SeriesDownloadInvalidUrl: chỉ nhận URL video Bilibili trực tiếp")
    voice = normalize_voice(args.voice)
    bgm_mode = normalize_bgm_mode(args.bgm_mode)
    ninerouter_model = normalize_ninerouter_model(args.ninerouter_model)
    data = load_state()
    series = find_series(data, args.series_id) if args.series_id else None
    result = queue_run_bilibili(
        url,
        voice,
        bgm_mode,
        ninerouter_model,
        translation_series_id=(series.get("series_id") if series else args.series_id),
        translation_genre_tags=(series.get("genre_tags") if series else []),
    )
    if series:
        for ep in series.get("episodes", []):
            if ep.get("url") == url:
                ep["status"] = "queued"
                ep["download_status"] = "queued"
                ep["localization_status"] = "queued"
                ep["last_job_id"] = result["job_id"]
                break
        series["updated_at"] = now_iso()
        save_state(data)
    print_json(result)


def parse_job_output_paths(text):
    """Extract paths only from the markers already used for job status detection."""
    final_match = re.search(r"^\s*(?:final_video|final_video_vi\.mp4)\s*:\s*(.+?)\s*$", text, re.MULTILINE)
    output_match = re.search(r"^\s*bilibili_output_dir\s*:\s*(.+?)\s*$", text, re.MULTILINE)
    final_video_path = final_match.group(1).strip().strip("\"'") if final_match else None
    output_dir = output_match.group(1).strip().strip("\"'") if output_match else None
    if final_video_path and not output_dir:
        output_dir = str(Path(final_video_path).parent)
    if output_dir and not final_video_path:
        final_video_path = str(Path(output_dir) / "final_video_vi.mp4")
    return final_video_path, output_dir


def cmd_job_status(args):
    job_id = args.job_id.strip()
    req = QUEUE_DIR / "requests" / f"{job_id}.req"
    log = QUEUE_DIR / "logs" / f"{job_id}.req.log"
    status = "queued" if req.exists() else "unknown"
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="replace")[-12000:]
        if "final_video:" in text or "final_video_vi.mp4" in text or "bilibili_output_dir:" in text:
            candidate, _ = parse_job_output_paths(text)
            if candidate and Path(candidate).is_file() and Path(candidate).stat().st_size > 0:
                status = "done"
            else:
                status = "needs_attention"
        elif "ERROR:" in text or "Failed" in text or "BilibiliDownloadFailed" in text:
            status = "error"
        else:
            status = "running"
    else:
        text = ""
    final_video_path, output_dir = parse_job_output_paths(text)
    data = load_state()
    episode = None
    for series in data.get("series", []):
        for candidate in series.get("episodes", []):
            if candidate.get("last_job_id") == job_id:
                episode = candidate
                series["updated_at"] = now_iso()
                break
        if episode:
            break
    if episode:
        episode["status"] = status
        stage_status = "completed" if status == "done" else status
        episode["download_status"] = stage_status
        episode["localization_status"] = stage_status
        if final_video_path:
            episode["final_video_path"] = final_video_path
        if output_dir:
            episode["last_output_dir"] = output_dir
        save_state(data)
    print_json({"ok": True, "job_id": job_id, "status": status, "request": str(req), "log": str(log), "log_tail": text})


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    p = sub.add_parser("add")
    p.add_argument("--name", required=True)
    p.add_argument("--keyword", required=True)
    p.add_argument("--source-url", required=True)
    p.add_argument("--channel-url", default="")
    p.add_argument("--series-id", default="")
    p.add_argument("--genre-tags", default="", help="Comma-separated tags: tu_tien,hoc_duong,giang_ho,hien_dai,co_trang")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("refresh")
    p.add_argument("series_id")
    p.add_argument("--limit", type=int, default=500)
    p.set_defaults(func=cmd_refresh)
    p = sub.add_parser("remove")
    p.add_argument("series_id")
    p.set_defaults(func=cmd_remove)
    p = sub.add_parser("download")
    p.add_argument("url")
    p.add_argument("--voice", default="")
    p.add_argument("--bgm-mode", default="auto")
    p.add_argument("--ninerouter-model", default=DEFAULT_NINEROUTER_MODEL)
    p.add_argument("--series-id", default="")
    p.set_defaults(func=cmd_download)
    p = sub.add_parser("job-status")
    p.add_argument("job_id")
    p.set_defaults(func=cmd_job_status)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

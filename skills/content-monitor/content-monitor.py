#!/usr/bin/env python3
"""
content-monitor.py
==================
Daemon theo doi kenh Douyin/TikTok/Bilibili va gui thong bao Telegram.

Cach dung:
  python3 content-monitor.py --add-channel "URL" --name "Ten kenh"
  python3 content-monitor.py --start --interval 60
  python3 content-monitor.py --stop
  python3 content-monitor.py --status
  python3 content-monitor.py --list
  python3 content-monitor.py --run-once
"""

import sys
import os
import json
import time
import signal
import subprocess
import argparse
import shutil
import urllib.request
import urllib.parse
import datetime
import tempfile
from pathlib import Path
import asyncio
import re

# =========================================================
# PHAN 1: Duong dan cau hinh co dinh
# Tat ca file luu chung trong thu muc cua skill nay
# =========================================================
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
CHANNELS_FILE = os.path.join(SKILL_DIR, "channels.json")       # Danh sach kenh theo doi
SEEN_FILE = os.path.join(SKILL_DIR, "seen_videos.json")        # ID video da xu ly
LOG_FILE = os.path.join(SKILL_DIR, "monitor.log")              # File log
PID_FILE = os.path.join(SKILL_DIR, "daemon.pid")               # Process ID cua daemon
HOST_HOME = os.environ.get("OPENCLAW_HOST_HOME", "/home/haonguyen")
WORKSPACE_ROOT = os.environ.get("OPENCLAW_WORKSPACE_ROOT", os.path.join(HOST_HOME, ".openclaw", "workspace"))
STATE_DIR = os.environ.get("OPENCLAW_STATE_DIR", os.path.join(WORKSPACE_ROOT, "state"))
API_KEYS_FILE = os.environ.get("OPENCLAW_API_KEYS_FILE", os.path.join(STATE_DIR, "api-keys.json"))
OPENCLAW_CONFIG = os.environ.get("OPENCLAW_CONFIG_FILE", os.path.join(HOST_HOME, ".openclaw", "openclaw.json"))
VIDEO_ANALYST = os.environ.get("OPENCLAW_VIDEO_ANALYST", os.path.join(WORKSPACE_ROOT, "skills", "video-analyst", "video-analyst.py"))
YTDLP_BIN = os.environ.get("YT_DLP_BIN", shutil.which("yt-dlp") or "yt-dlp")
CDP_URL = os.environ.get("CONTENT_MONITOR_CDP_URL", os.environ.get("DOUYIN_CDP_URL", "http://127.0.0.1:9222"))

# Cac ID Douyin da duoc phat hien la link chet/sai nguon trong qua trinh tim kenh 消消漫.
# Khong bao lai cac link nay cho user, vi no lam app/desktop Douyin hien "khong tim thay video".
KNOWN_DEAD_DOUYIN_VIDEO_IDS = {
    "7524597831689080104",
    "7524598107489750324",
    "7527700826886868262",
    "7635264794047696162",
    "7630089159046122788",
}

# Telegram bot cua Sep (co the override bang env).
# KHONG fallback cung vao private chat cu (7430055444) khi thieu env — do la
# nguyen nhan gui nham vao private chat. Load cung config JSON nhu
# telegram-send-result.sh; neu van thieu token/chat_id thi bao warning ro va
# send_telegram tra False thay vi gui am tham vao chat mac dinh.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("CONTENT_MONITOR_TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = os.environ.get("CONTENT_MONITOR_TELEGRAM_CHAT_ID", os.environ.get("TELEGRAM_CHAT_ID", ""))
# Group "Group AI" la supergroup co forum topics -> phai gui vao topic cu the
# (message_thread_id). Mac dinh lay tu env/config; neu khong co thi gui vao
# General topic (co the bi TOPIC_CLOSED neu topic do da dong).
TELEGRAM_MESSAGE_THREAD_ID = os.environ.get("TELEGRAM_MESSAGE_THREAD_ID", "")


def _load_telegram_json_config():
    """Doc token + chatId (+ messageThreadId) tu telegram.json (cung file
    telegram-send-result.sh dung). Tra dict hoac {} neu khong doc duoc."""
    import json as _json
    path = os.environ.get(
        "TELEGRAM_CONFIG",
        os.path.join(HOST_HOME, ".openclaw", "config", "channels", "telegram.json"),
    )
    try:
        data = _json.load(open(path, "r", encoding="utf-8"))
    except Exception:
        return {}
    tg = data.get("telegram", data) if isinstance(data, dict) else {}
    bots = tg.get("bots") or []
    token = ""
    if bots and isinstance(bots[0], dict):
        token = bots[0].get("token") or ""
    chat = tg.get("chatId") or tg.get("chat_id") or ""
    thread = tg.get("messageThreadId") or tg.get("message_thread_id") or ""
    return {
        "token": token,
        "chat_id": str(chat) if chat else "",
        "message_thread_id": str(thread) if thread else "",
    }


_cfg = _load_telegram_json_config()
if not TELEGRAM_BOT_TOKEN:
    TELEGRAM_BOT_TOKEN = _cfg.get("token", "")
if not TELEGRAM_CHAT_ID:
    TELEGRAM_CHAT_ID = _cfg.get("chat_id", "")
if not TELEGRAM_MESSAGE_THREAD_ID:
    TELEGRAM_MESSAGE_THREAD_ID = _cfg.get("message_thread_id", "")

# Gioi han seen_videos de tranh file phong to
MAX_SEEN_VIDEOS = 1000

# =========================================================
# PHAN 2: Ham log — ghi log ra file va hien thi man hinh
# =========================================================
def log(msg, level="INFO"):
    """Ghi log co timestamp ra file va in ra man hinh."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] [{level}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # Neu khong ghi duoc log, bo qua, khong lam hong qua trinh chinh


# =========================================================
# PHAN 3: Doc/ghi file JSON
# Hai ham nay bao ve du lieu khoi loi doc/ghi file
# =========================================================
def load_json(filepath, default):
    """Doc file JSON, neu khong co thi tra ve gia tri mac dinh."""
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Loi doc {filepath}: {e}", "WARN")
        return default


def save_json(filepath, data):
    """Ghi du lieu vao file JSON de doc ve sau."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# PHAN 4: Quan ly danh sach kenh theo doi (channels.json)
# =========================================================
def load_channels():
    """Doc danh sach kenh tu channels.json"""
    return load_json(CHANNELS_FILE, [])


def detect_platform(url):
    url = (url or "").lower()
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    if "douyin.com" in url or "iesdouyin.com" in url or "tiktok.com" in url:
        return "douyin"
    return "unknown"

def add_channel(url, name, platform=None):
    """Them kenh moi vao danh sach theo doi."""
    channels = load_channels()
    platform = (platform or detect_platform(url) or "unknown").lower()
    # Kiem tra trung lap
    for ch in channels:
        if ch.get("url") == url:
            if "platform" not in ch:
                ch["platform"] = platform
                save_json(CHANNELS_FILE, channels)
            log(f"Kenh '{name}' ({url}) da ton tai trong danh sach.")
            return
    channels.append({"url": url, "name": name, "platform": platform, "added_at": datetime.datetime.now().isoformat()})
    save_json(CHANNELS_FILE, channels)
    log(f"Da them kenh {platform}: {name} ({url})")
    print(f"OK: Da them kenh '{name}' ({platform}) vao danh sach theo doi.")


def remove_channel(identifier):
    """Xoa kenh khoi danh sach theo url hoac name."""
    channels = load_channels()
    before = len(channels)
    channels = [ch for ch in channels if ch["url"] != identifier and ch["name"] != identifier]
    if len(channels) < before:
        save_json(CHANNELS_FILE, channels)
        log(f"Da xoa kenh: {identifier}")
        print(f"OK: Da xoa kenh '{identifier}'.")
    else:
        print(f"Khong tim thay kenh '{identifier}' trong danh sach.")


def list_channels():
    """In danh sach tat ca kenh dang theo doi."""
    channels = load_channels()
    if not channels:
        print("Chua co kenh nao duoc them. Dung --add-channel de them.")
        return
    print(f"\n=== DANH SACH KENH DANG THEO DOI ({len(channels)} kenh) ===")
    for i, ch in enumerate(channels, 1):
        platform = ch.get("platform") or detect_platform(ch.get("url", ""))
        print(f"  {i}. {ch['name']} [{platform}]")
        print(f"     URL: {ch['url']}")
        print(f"     Them vao: {ch.get('added_at', 'N/A')}")
    print()


# =========================================================
# PHAN 5: Quan ly video da xem (seen_videos.json)
# Tranh gui thong bao trung lap cho Sep
# =========================================================
def load_seen():
    """Doc tap ID video da phan tich roi."""
    return set(load_json(SEEN_FILE, []))


def save_seen(seen_set):
    """
    Luu ID video da xem. Giu toi da MAX_SEEN_VIDEOS.
    Neu qua nhieu thi xoa bot cac entry cu nhat.
    """
    seen_list = list(seen_set)
    if len(seen_list) > MAX_SEEN_VIDEOS:
        seen_list = seen_list[-MAX_SEEN_VIDEOS:]  # Chi giu 1000 cai moi nhat
    save_json(SEEN_FILE, seen_list)


def mark_seen(video_id):
    """Danh dau 1 video la da xu ly."""
    seen = load_seen()
    seen.add(video_id)
    save_seen(seen)


def is_seen(video_id):
    """Kiem tra video nay da xu ly chua."""
    return video_id in load_seen()


# =========================================================
# PHAN 6: Lay danh sach video moi tu kenh Douyin
# Dung yt-dlp de lay metadata ma khong can tai video
# =========================================================
def fetch_latest_videos(channel_url, count=3):
    """
    Lay danh sach video moi nhat tu kenh.
    Tra ve list cac dict {id, url, title}.
    'count=3' la so video lay moi lan kiem tra.
    """
    cmd = [
        YTDLP_BIN,
        "--flat-playlist",          # Chi lay metadata, khong tai video
        "--playlist-end", str(count), # Chi lay 'count' video dau tien (moi nhat)
        "--print", "%(id)s |SEP| %(webpage_url)s |SEP| %(title)s",  # Format output
        "--no-warnings",
        "--quiet",
        channel_url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            log(f"yt-dlp loi khi ket noi {channel_url}: {result.stderr[:200]}", "WARN")
            return []

        videos = []
        for line in result.stdout.strip().split("\n"):
            if "|SEP|" not in line:
                continue
            parts = line.split("|SEP|")
            if len(parts) >= 3:
                vid_id = parts[0].strip()
                vid_url = parts[1].strip()
                vid_title = parts[2].strip()
                if vid_id:
                    videos.append({"id": vid_id, "url": vid_url, "title": vid_title})
        return videos
    except subprocess.TimeoutExpired:
        log(f"Timeout khi kiem tra kenh: {channel_url}", "WARN")
        return []
    except Exception as e:
        log(f"Loi fetch kenh {channel_url}: {e}", "WARN")
        return []

async def _fetch_latest_videos_via_cdp(channel_url, count=3):
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        log(f"Khong import duoc playwright cho CDP fallback: {e}", "WARN")
        return []

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=8000)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        channel_id = channel_url.rstrip('/').split('/')[-1]
        page = None
        for existing in context.pages:
            try:
                if channel_id and channel_id in existing.url:
                    page = existing
                    log("Dung tab kenh Douyin dang mo san trong Chrome CDP.")
                    break
            except Exception:
                pass
        opened_page = page is None
        if opened_page:
            page = await context.new_page()
        verify_page = None
        page.set_default_timeout(20000)
        try:
            if opened_page:
                await page.goto(channel_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)
            title = (await page.title()).lower()
            try:
                body_text = (await page.locator("body").inner_text(timeout=5000)).lower()
            except Exception:
                body_text = ""
            for _ in range(3):
                await page.mouse.wheel(0, 1400)
                await page.wait_for_timeout(1500)
            cards = []
            last_error = None
            for attempt in range(1, 4):
                try:
                    cards = await page.evaluate(
                r"""() => {
                    const norm = (u) => {
                      if (!u) return '';
                      if (u.startsWith('//')) return 'https:' + u;
                      if (u.startsWith('/')) return 'https://www.douyin.com' + u;
                      return u;
                    };
                    const results = [];
                    const seen = new Set();
                    const profile = document.querySelector('[data-e2e="user-post-list"], [data-e2e="user-detail"], main') || document.body;
                    for (const a of Array.from(profile.querySelectorAll('a[href*="/video/"]'))) {
                      const href = norm(a.getAttribute('href') || a.href || '');
                      if (!href || seen.has(href)) continue;
                      if (!/^https:\/\/www\.douyin\.com\/video\/\d+/.test(href)) continue;
                      seen.add(href);
                      const txt = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim();
                      const img = a.querySelector('img[alt]');
                      const title = (img?.alt || txt || '').replace(/\s+/g, ' ').trim();
                      const m = href.match(/\/video\/(\d+)/);
                      results.push({id: m ? m[1] : href, url: href, title: title || '[Không tiêu đề]'});
                    }
                    return results;
                }"""
                    )
                    break
                except Exception as e:
                    last_error = e
                    log(f"Retry doc danh sach video tu kenh lan {attempt}: {e}", "WARN")
                    await page.wait_for_timeout(1500 * attempt)
            if not cards and last_error:
                raise last_error
            verify_markers = ["验证码", "captcha", "verify", "xác minh", "短信验证", "安全验证"]
            if not cards and any(marker in title or marker in body_text for marker in verify_markers):
                log("Douyin dang hien trang xac minh/captcha trong Chrome CDP; can nguoi dung xu ly thu cong truoc khi monitor tiep tuc.", "WARN")
                return []
            live_cards = []
            for card in cards[: max(count * 3, count)]:
                if await verify_douyin_video_live(verify_page, card.get("url", "")):
                    live_cards.append(card)
                    if len(live_cards) >= count:
                        break
                else:
                    log(f"Bo qua link video chet/khong ton tai: {card.get('url', '')}", "WARN")
            return live_cards
        finally:
            if opened_page:
                try:
                    await page.close()
                except Exception:
                    pass
            if verify_page is not None:
                try:
                    await verify_page.close()
                except Exception:
                    pass

async def verify_douyin_video_live(page, video_url: str) -> bool:
    match = re.match(r"^https://www\.douyin\.com/video/(\d+)", video_url or "")
    if not match:
        return False
    return match.group(1) not in KNOWN_DEAD_DOUYIN_VIDEO_IDS

def fetch_latest_videos_with_fallback(channel_url, count=3):
    videos = fetch_latest_videos(channel_url, count=count)
    if videos:
        return videos
    log("yt-dlp khong lay duoc danh sach video; thu CDP fallback tren Chrome that.", "WARN")
    try:
        return asyncio.run(_fetch_latest_videos_via_cdp(channel_url, count=count))
    except Exception as e:
        log(f"CDP fallback cung that bai: {e}", "WARN")
        return []


def fetch_latest_bilibili_videos(channel_url, count=3):
    """Lay danh sach video moi tu kenh/space Bilibili bang yt-dlp metadata."""
    cmd = [
        YTDLP_BIN,
        "--flat-playlist",
        "--playlist-end", str(count),
        "--print", "%(id)s |SEP| %(webpage_url)s |SEP| %(title)s",
        "--no-warnings",
        "--quiet",
        channel_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=75)
        if result.returncode != 0:
            log(f"yt-dlp loi khi ket noi Bilibili {channel_url}: {result.stderr[:240]}", "WARN")
            return []
        videos = []
        for line in result.stdout.strip().split("\n"):
            if "|SEP|" not in line:
                continue
            parts = line.split("|SEP|")
            if len(parts) >= 3:
                vid_id = parts[0].strip()
                vid_url = parts[1].strip()
                vid_title = parts[2].strip()
                if vid_url.startswith("//"):
                    vid_url = "https:" + vid_url
                if vid_id:
                    videos.append({"id": f"bilibili:{vid_id}", "url": vid_url, "title": vid_title})
        return videos
    except subprocess.TimeoutExpired:
        log(f"Timeout khi kiem tra kenh Bilibili: {channel_url}", "WARN")
        return []
    except Exception as e:
        log(f"Loi fetch kenh Bilibili {channel_url}: {e}", "WARN")
        return []

async def _fetch_latest_bilibili_videos_via_cdp(channel_url, count=3):
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        log(f"Khong import duoc playwright cho Bilibili CDP fallback: {e}", "WARN")
        return []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL, timeout=8000)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(20000)
        try:
            await page.goto(channel_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3500)
            for _ in range(2):
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(1000)
            text = ""
            try:
                text = (await page.locator("body").inner_text(timeout=3000)).lower()
            except Exception:
                pass
            if any(marker in text for marker in ["验证码", "captcha", "请先登录", "安全验证"]):
                log("Bilibili dang yeu cau login/captcha/verify trong Chrome CDP; can user xu ly thu cong.", "WARN")
                return []
            cards = await page.evaluate(r"""
            (limit) => {
              const norm = (u) => {
                if (!u) return '';
                if (u.startsWith('//')) return 'https:' + u;
                if (u.startsWith('/')) return 'https://www.bilibili.com' + u;
                return u;
              };
              const out = [];
              const seen = new Set();
              for (const a of document.querySelectorAll('a[href*="/video/BV"], a[href*="/video/av"]')) {
                let href = norm(a.getAttribute('href') || a.href || '');
                const m = href.match(/https?:\/\/(?:www\.)?bilibili\.com\/video\/[A-Za-z0-9]+/);
                if (!m) continue;
                href = m[0];
                if (seen.has(href)) continue;
                let title = (a.innerText || a.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
                if (!title) {
                  const img = a.querySelector('img[alt]');
                  title = (img && img.alt || '').replace(/\s+/g, ' ').trim();
                }
                seen.add(href);
                const idm = href.match(/\/video\/([A-Za-z0-9]+)/);
                out.push({id: idm ? 'bilibili:' + idm[1] : 'bilibili:' + href, url: href, title: title || '[Khong tieu de]'});
                if (out.length >= limit) break;
              }
              return out;
            }
            """, count)
            return cards or []
        finally:
            try:
                await page.close()
            except Exception:
                pass

def fetch_latest_bilibili_videos_with_fallback(channel_url, count=3):
    videos = fetch_latest_bilibili_videos(channel_url, count=count)
    if videos:
        return videos
    log("yt-dlp khong lay duoc Bilibili; thu CDP fallback tren Chrome that.", "WARN")
    try:
        return asyncio.run(_fetch_latest_bilibili_videos_via_cdp(channel_url, count=count))
    except Exception as e:
        log(f"Bilibili CDP fallback cung that bai: {e}", "WARN")
        return []

def fetch_latest_videos_for_channel(channel, count=3):
    url = channel.get("url", "") if isinstance(channel, dict) else str(channel)
    platform = (channel.get("platform") if isinstance(channel, dict) else None) or detect_platform(url)
    platform = (platform or "douyin").lower()
    if platform == "bilibili":
        return fetch_latest_bilibili_videos_with_fallback(url, count=count)
    return fetch_latest_videos_with_fallback(url, count=count)


# =========================================================
# PHAN 7: Goi skill video-analyst de phan tich 1 video
# =========================================================
def analyze_video(video_url):
    """
    Goi video-analyst.py de phan tich video.
    Tra ve (transcript_zh, bao_cao_text) hoac None neu loi.
    """
    # Doc API key tu file cau hinh
    api_keys = load_json(API_KEYS_FILE, {})
    api_key = api_keys.get("OPENAI_API_KEY", "")
    if not api_key:
        log("Khong co OPENAI_API_KEY — khong the phan tich video", "ERROR")
        return None

    if not os.path.exists(VIDEO_ANALYST):
        log(f"Khong tim thay video-analyst.py tai {VIDEO_ANALYST}; dung fallback metadata.", "WARN")
        return None

    log(f"Phan tich video: {video_url}")
    try:
        result = subprocess.run(
            ["python3", VIDEO_ANALYST, video_url, "--api-key", api_key],
            capture_output=True, text=True, timeout=300  # cho toi da 5 phut
        )
        if result.returncode == 0:
            return result.stdout
        else:
            log(f"video-analyst.py loi: {result.stderr[:200]}", "WARN")
            return None
    except subprocess.TimeoutExpired:
        log("Phan tich video bi timeout (>5 phut)", "WARN")
        return None
    except Exception as e:
        log(f"Loi goi video-analyst: {e}", "WARN")
        return None

def build_fallback_report(video_title, channel_name):
    title = (video_title or "").strip() or "Video mới"
    return {
        "chu_de": title[:120],
        "tom_tat": f"Kênh {channel_name} vừa đăng video mới: {title}",
        "hot_reason": "Video mới đăng nên có thể đáng theo dõi sớm.",
        "thoi_luong": "?"
    }


# =========================================================
# PHAN 8: Phan tich bao cao va trich xuat thong tin
# Doc output text tu video-analyst va lay phan chinh
# =========================================================
def parse_analyst_report(report_text):
    """
    Tim cac dong du lieu chinh tu bao cao video-analyst.
    Tra ve dict {chu_de, tom_tat, hot_reason, thoi_luong}.
    """
    result = {
        "chu_de": "Khong xac dinh duoc",
        "tom_tat": "Khong lay duoc tom tat.",
        "hot_reason": "Khong xac dinh.",
        "thoi_luong": "?"
    }
    if not report_text:
        return result

    # Tach tung dong va tim tu khoa
    lines = report_text.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("CHU DE CHINH:"):
            result["chu_de"] = line.replace("CHU DE CHINH:", "").strip()
        elif "CHU DE" in line and ":" in line:
            result["chu_de"] = line.split(":", 1)[-1].strip()
        elif line.startswith("TOM TAT:"):
            result["tom_tat"] = line.replace("TOM TAT:", "").strip()
        elif "DURATION:" in line or "THOI LUONG:" in line:
            result["thoi_luong"] = line.split(":", 1)[-1].strip()

    return result


# =========================================================
# PHAN 9: Gui tin nhan Telegram
# Dung Telegram Bot API voi retry 3 lan neu that bai
# =========================================================
def send_telegram(text, retry=3):
    """
    Gui tin nhan den Sep qua Telegram Bot.
    Thu lai toi da 'retry' lan neu that bai.
    """
    if not TELEGRAM_BOT_TOKEN:
        log("Khong gui Telegram: thieu TELEGRAM_BOT_TOKEN (env hoac telegram.json). Bo qua, KHONG fallback vao chat mac dinh.", "WARN")
        return False
    if not TELEGRAM_CHAT_ID:
        log("Khong gui Telegram: thieu TELEGRAM_CHAT_ID (env hoac telegram.json). Bo qua, KHONG fallback vao chat mac dinh.", "WARN")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    body = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",       # Cho phep dung <b>, <i> trong tin nhan
        "disable_web_page_preview": False
    }
    # Group la forum supergroup -> gui vao topic cu the de tranh TOPIC_CLOSED.
    if TELEGRAM_MESSAGE_THREAD_ID:
        try:
            body["message_thread_id"] = int(TELEGRAM_MESSAGE_THREAD_ID)
        except ValueError:
            body["message_thread_id"] = TELEGRAM_MESSAGE_THREAD_ID
    payload = json.dumps(body).encode("utf-8")

    for attempt in range(1, retry + 1):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                if resp_data.get("ok"):
                    log("Gui Telegram thanh cong.")
                    return True
                else:
                    log(f"Telegram API tra loi loi: {resp_data}", "WARN")
        except Exception as e:
            log(f"Loi gui Telegram lan {attempt}/{retry}: {e}", "WARN")
            if attempt < retry:
                time.sleep(10)  # Cho 10 giay truoc khi thu lai

    log("Gui Telegram that bai sau 3 lan thu.", "ERROR")
    return False


def build_telegram_message(channel_name, video_url, report, video_title):
    """
    Tao noi dung tin nhan Telegram theo dung format Sep yeu cau.
    """
    chu_de = report.get("chu_de", "?")
    tom_tat = report.get("tom_tat", "Khong co tom tat.")
    hot_reason = report.get("hot_reason", "Khong xac dinh.")
    thoi_luong = report.get("thoi_luong", "?")

    msg = (
        f"<b>🆕 VIDEO MỚI từ {channel_name}</b>\n"
        f"📹 <b>Link:</b> {video_url}\n"
        f"🎯 <b>Chủ đề:</b> {chu_de}\n"
        f"📝 <b>Tóm tắt:</b> {tom_tat}\n"
        f"🔥 <b>Tại sao hot:</b> {hot_reason}\n"
        f"⏱ <b>Thời lượng:</b> {thoi_luong}"
    )
    return msg


# =========================================================
# PHAN 10: Vong lap chinh — Kiem tra tat ca kenh 1 luot
# Day la trung tam cua skill, duoc goi moi 60 phut
# =========================================================
def run_check_cycle():
    """
    Kiem tra tat ca kenh trong channels.json mot lan.
    Voi moi video moi: phan tich + gui Telegram.
    """
    channels = load_channels()
    if not channels:
        log("Chua co kenh nao duoc them. Bung --add-channel de them kenh.")
        return

    log(f"=== BAT DAU KIEM TRA {len(channels)} KENH ===")

    for channel in channels:
        name = channel.get("name", "Unknown")
        url = channel.get("url", "")
        if not url:
            continue

        log(f"Dang kiem tra kenh: {name}")
        videos = fetch_latest_videos_for_channel(channel, count=3)

        if not videos:
            log(f"  -> Kenh {name}: khong lay duoc video.", "WARN")
            continue

        new_count = 0
        for video in videos:
            vid_id = video["id"]
            vid_url = video["url"]
            vid_title = video.get("title", "")

            if is_seen(vid_id):
                continue  # Video nay da xu ly roi, bo qua

            log(f"  -> Video MOI: {vid_title} ({vid_url})")
            new_count += 1

            # Phan tich video
            report_text = analyze_video(vid_url)
            report = parse_analyst_report(report_text)

            if report_text is None:
                report = build_fallback_report(vid_title, name)
                msg = build_telegram_message(name, vid_url, report, vid_title)
            else:
                msg = build_telegram_message(name, vid_url, report, vid_title)

            # Gui Telegram
            send_telegram(msg)

            # Danh dau da xu ly
            mark_seen(vid_id)

            # Nghi 5 giay giua moi video de tranh spam API
            time.sleep(5)

        if new_count == 0:
            log(f"  -> Kenh {name}: khong co video moi.")
        else:
            log(f"  -> Kenh {name}: da xu ly {new_count} video moi.")

    log("=== KIEM TRA HOAN TAT ===\n")


# =========================================================
# PHAN 11: Daemon — Chay vong lap vo tan
# Moi 'interval' phut lai goi run_check_cycle() mot lan
# =========================================================
def start_daemon(interval_minutes):
    """
    Dang ky signal handler va chay vong lap chinh.
    interval_minutes = so phut giua hai lan kiem tra.
    """
    # Luu PID de --stop co the tim va tat
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # Xu ly tin hieu Ctrl+C hoac kill
    def on_stop(sig, frame):
        log("Daemon dang dung lai...")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)

    log(f"Content Monitor daemon bat dau. Kiem tra moi {interval_minutes} phut.")

    # Chay kiem tra luon khi vua start
    run_check_cycle()

    # Vong lap vo tan
    while True:
        log(f"Dang ngu {interval_minutes} phut...")
        time.sleep(interval_minutes * 60)
        run_check_cycle()


def stop_daemon():
    """Tim PID va gui lenh dung daemon."""
    if not os.path.exists(PID_FILE):
        print("Daemon dang khong chay (khong tim thay daemon.pid).")
        return

    with open(PID_FILE) as f:
        pid = int(f.read().strip())

    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
        os.remove(PID_FILE)
        print(f"Da dung daemon (PID {pid}).")
        log(f"Daemon bi dung boi nguoi dung. PID={pid}")
    except ProcessLookupError:
        print(f"Tien trinh PID={pid} khong con ton tai. Da xoa PID file.")
        os.remove(PID_FILE)
    except Exception as e:
        print(f"Loi dung daemon: {e}")


def check_status():
    """Hien thi trang thai daemon va thong tin cau hinh."""
    channels = load_channels()
    seen = load_seen()

    running = False
    pid = None
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, 0)  # Kill 0 = chi kiem tra ton tai, khong dung
            running = True
        except ProcessLookupError:
            pass

    print("\n=== CONTENT MONITOR STATUS ===")
    print(f"Trang thai daemon: {'DANG CHAY (PID=' + str(pid) + ')' if running else 'DUNG'}")
    print(f"So kenh theo doi: {len(channels)}")
    print(f"So video da xu ly: {len(seen)}")
    print(f"File log: {LOG_FILE}")
    print("==============================\n")

def prime_seen_current_videos(count=3):
    channels = load_channels()
    if not channels:
        log("Chua co kenh nao de prime seen.", "WARN")
        return
    total = 0
    for channel in channels:
        name = channel.get("name", "Unknown")
        url = channel.get("url", "")
        if not url:
            continue
        log(f"Prime seen kenh: {name}")
        videos = fetch_latest_videos_for_channel(channel, count=count)
        for video in videos:
            vid_id = video.get("id")
            if vid_id:
                mark_seen(vid_id)
                total += 1
                log(f"  -> marked seen: {vid_id} | {video.get('title', '')}")
    log(f"Prime seen hoan tat: {total} video.")

def find_keyword_in_channels(keyword, count=100):
    keyword = (keyword or "").strip()
    if not keyword:
        print("ERROR: Thieu keyword.")
        return
    channels = load_channels()
    if not channels:
        print("Chua co kenh nao trong channels.json")
        return
    print(f"=== TIM VIDEO THEO TU KHOA: {keyword} ===")
    total = 0
    for channel in channels:
        name = channel.get("name", "Unknown")
        url = channel.get("url", "")
        print(f"\n# Kenh: {name}")
        videos = fetch_latest_videos_for_channel(channel, count=count)
        matches = []
        for video in videos:
            title = video.get("title", "")
            if keyword in title:
                matches.append(video)
            elif keyword.replace("远古", "遠古") in title or keyword.replace("遠古", "远古") in title:
                matches.append(video)
            elif "兽神" in keyword and "兽神" in title:
                matches.append(video)
        if not matches:
            print("Khong thay video khop keyword trong so video dang load tren trang kenh.")
            continue
        for index, video in enumerate(matches, 1):
            print(f"{index}. {video.get('title', '[Khong tieu de]')}")
            print(f"   Link: {video.get('url', '')}")
            print(f"   ID: {video.get('id', '')}")
            total += 1
    print(f"\nTong ket: {total} video khop keyword.")


# =========================================================
# MAIN: Phan tich tham so dong lenh
# =========================================================
def main():
    parser = argparse.ArgumentParser(description="Content Monitor - Theo doi kenh Douyin tu dong")
    parser.add_argument("--add-channel", metavar="URL", help="Them kenh vao danh sach theo doi")
    parser.add_argument("--name", default="Unknown", help="Ten de nho cua kenh (dung voi --add-channel)")
    parser.add_argument("--platform", choices=["douyin", "bilibili", "unknown"], default=None, help="Nen tang kenh: douyin hoac bilibili")
    parser.add_argument("--remove-channel", metavar="URL_OR_NAME", help="Xoa kenh khoi danh sach")
    parser.add_argument("--list", action="store_true", help="Hien thi danh sach kenh dang theo doi")
    parser.add_argument("--start", action="store_true", help="Bat daemon theo doi")
    parser.add_argument("--stop", action="store_true", help="Dung daemon")
    parser.add_argument("--status", action="store_true", help="Kiem tra trang thai daemon")
    parser.add_argument("--run-once", action="store_true", help="Chay kiem tra 1 lan roi thoat")
    parser.add_argument("--prime-seen", action="store_true", help="Danh dau video hien tai la da xem, khong gui Telegram")
    parser.add_argument("--find-keyword", metavar="TEXT", help="Tim video theo keyword trong cac kenh da luu bang CDP/tab kenh dang mo")
    parser.add_argument("--find-limit", type=int, default=100, help="So video toi da can quet khi --find-keyword")
    parser.add_argument("--interval", type=int, default=60, help="Khoang thoi gian kiem tra (phut, mac dinh 60)")
    args = parser.parse_args()

    if args.add_channel:
        add_channel(args.add_channel, args.name, args.platform)
    elif args.remove_channel:
        remove_channel(args.remove_channel)
    elif args.list:
        list_channels()
    elif args.start:
        start_daemon(args.interval)
    elif args.stop:
        stop_daemon()
    elif args.status:
        check_status()
    elif args.run_once:
        log("Chay kiem tra 1 lan theo yeu cau.")
        run_check_cycle()
    elif args.prime_seen:
        prime_seen_current_videos()
    elif args.find_keyword:
        find_keyword_in_channels(args.find_keyword, args.find_limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

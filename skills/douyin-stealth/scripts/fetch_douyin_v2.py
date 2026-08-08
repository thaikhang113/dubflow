import asyncio
import os
import random
import sys
import time
import urllib.parse
import urllib.request
import json
import re
import uuid

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from clean_media_resolver import (
    ALLOW_WATERMARKED_FALLBACK,
    CLEAN_ONLY,
    resolve_media_candidates,
    safe_candidate_source_summary,
    safe_rejection_summary,
    validate_media_probe_response,
)

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(SKILL_DIR, "session", "stealth_v2.log")
CACHE_FILE = os.path.join(SKILL_DIR, "session", "search_cache.json")
STATE_FILE = os.path.join(SKILL_DIR, "session", "captcha_state.json")
TASK_FILE = os.path.join(SKILL_DIR, "session", "current_task.json")
SEEN_FILE = os.path.join(os.path.dirname(SKILL_DIR), "content-monitor", "seen_videos.json")
MAX_SEEN_VIDEOS = 1000

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = "7430055444"

task_data = {
    "task_id": str(uuid.uuid4()),
    "keyword": "",
    "target_count": 5,
    "started_at": time.time(),
    "updated_at": time.time(),
    "elapsed_seconds": 0,
    "status": "IDLE",
    "current_step": "INIT",
    "current_url": "",
    "cards_found": 0,
    "links_found": 0,
    "videos_extracted": 0,
    "cards_clicked": 0,
    "captcha_visible": False,
    "last_error": "",
    "debug_files": [],
    "cancel_requested": False,
    "timeout_triggered": False
}

def update_task(status=None, step=None, url=None, **kwargs):
    if status: task_data["status"] = status
    if step: task_data["current_step"] = step
    if url: task_data["current_url"] = url
    for k, v in kwargs.items():
        task_data[k] = v
    task_data["updated_at"] = time.time()
    task_data["elapsed_seconds"] = int(time.time() - task_data["started_at"])
    
    try:
        os.makedirs(os.path.dirname(TASK_FILE), exist_ok=True)
        with open(TASK_FILE, "w", encoding="utf-8") as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_task():
    try:
        if os.path.exists(TASK_FILE):
            with open(TASK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return None

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass
    except Exception as e:
        log(f"Lỗi gửi Telegram: {e}")

async def progress_reporter():
    last_report_time = task_data["started_at"]
    
    while True:
        await asyncio.sleep(1)
        now = time.time()
        
        current = load_task()
        if current and current.get("cancel_requested"):
            log("🛑 Có yêu cầu hủy task từ Telegram.")
            print("STATUS: CANCELLED")
            os._exit(1)

        elapsed = now - task_data["started_at"]
        if elapsed > 240:
            task_data["timeout_triggered"] = True

        if elapsed >= 60 and (now - last_report_time) >= 60:
            last_report_time = now
            cap_str = "yes" if task_data.get('captcha_visible') else "no"
            step = task_data.get('current_step', '')
            if len(step) > 20: step = step[:20]
            msg = f"Douyin: {step} | {int(elapsed)}s | {task_data.get('videos_extracted', 0)}/{task_data.get('target_count', 5)} | cap={cap_str}"
            send_telegram(msg)

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_seen(seen_set):
    seen_list = list(seen_set)
    if len(seen_list) > MAX_SEEN_VIDEOS:
        seen_list = seen_list[-MAX_SEEN_VIDEOS:]
    try:
        os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(seen_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Lỗi ghi seen_videos: {e}")

def extract_video_id(link):
    match = re.search(r'(?:video|modal_id|aweme_id|note)[/=](\d+)', link)
    if match:
        return match.group(1)
    return link

BAD_TITLES = {
    "相关搜索", "综合", "视频", "用户", "直播", "热点", "搜索",
    "Đăng nhập", "登录", "Log in", "", "#", "推荐", "精选", "发现",
    "查看更多", "查看详情", "打开看看", "关注", "评论", "分享", "收藏",
}

TITLE_NOISE_RE = re.compile(
    r"^(?:\d{1,2}:\d{2}(?::\d{2})?|\d+(?:\.\d+)?万?|\d+赞|\d+评论|\d+分享|\d+天前|\d+小时前|\d+分钟前|\d+月\d+日|20\d{2}[-.]\d{1,2}[-.]\d{1,2})$"
)

def trim_title(title: str) -> str:
    title = re.sub(r"\s+", " ", (title or "").strip())
    if len(title) > 120:
        title = title[:117].rstrip() + "..."
    return title

def is_title_noise(line: str) -> bool:
    line = trim_title(line)
    if not line or line in BAD_TITLES:
        return True
    if TITLE_NOISE_RE.fullmatch(line):
        return True
    if re.fullmatch(r"[\d:万赞.\w\s]+", line):
        return True
    return False

def score_title_line(line: str) -> int:
    line = trim_title(line)
    score = 0
    if re.search(r"[\u4e00-\u9fff]", line):
        score += 8
    if "#" in line:
        score += 4
    if len(line) >= 8:
        score += 3
    if len(line) >= 20:
        score += 2
    if re.search(r"原创|动画|二次元|一口气|合集|系列|漫画|漫动画|沙雕", line):
        score += 5
    return score

def build_title_from_parts(author: str = "", hashtags: str = "", desc: str = "") -> str:
    author = trim_title(author)
    hashtags = trim_title(hashtags)
    desc = trim_title(desc)
    parts = []
    if author and not is_title_noise(author):
        parts.append(author)
    if hashtags and not is_title_noise(hashtags):
        parts.append(hashtags)
    if desc and not is_title_noise(desc):
        parts.append(desc)
    if not parts:
        return "[Không tiêu đề]"
    return trim_title(" | ".join(parts[:3]))

def best_title_from_text(*texts: str) -> str:
    candidates = []
    for text in texts:
        for line in re.split(r"[\r\n]+", text or ""):
            line = trim_title(line)
            if is_title_noise(line):
                continue
            candidates.append(line)
    if not candidates:
        return "[Không tiêu đề]"
    candidates.sort(key=lambda x: (score_title_line(x), len(x)), reverse=True)
    return candidates[0]

def clean_title(title: str, *fallback_texts: str) -> str:
    title = trim_title(title)
    if not is_title_noise(title):
        return title
    return best_title_from_text(*fallback_texts)

def pick_title_and_source(video: dict) -> tuple[str, str]:
    direct_sources = [
        ("direct_title", video.get("title", "")),
        ("data_title", video.get("data_title", "")),
        ("aria", video.get("aria", "")),
        ("alt", video.get("alt", "")),
        ("text", video.get("text", "")),
        ("author", video.get("author", "")),
        ("hashtags", video.get("hashtags", "")),
        ("desc", video.get("desc", "")),
        ("outerHTML", video.get("outerHTML", "")),
    ]
    for source_name, raw in direct_sources:
        title = clean_title(raw)
        if title != "[Không tiêu đề]":
            return title, source_name

    combined = clean_title(*(raw for _, raw in direct_sources))
    if combined != "[Không tiêu đề]":
        return combined, "combined_fallback"

    built = build_title_from_parts(video.get("author", ""), video.get("hashtags", ""), video.get("desc", ""))
    if built != "[Không tiêu đề]":
        return built, "parts_fallback"
    return "[Không tiêu đề]", "fallback"

def enrich_missing_titles(results: list) -> list:
    by_video_id = {}
    for item in results:
        vid = item.get("video_id")
        if vid and item.get("title") and item["title"] != "[Không tiêu đề]":
            by_video_id[vid] = (item["title"], item.get("title_source", "same_video_id"))

    enriched = []
    for item in results:
        if item.get("title") == "[Không tiêu đề]":
            vid = item.get("video_id")
            backfill = by_video_id.get(vid)
            if backfill:
                item = dict(item)
                item["title"] = backfill[0]
                item["title_source"] = "cache_same_video_id"
        enriched.append(item)
    return enriched

def normalize_video_link(link: str) -> str:
    link = (link or "").strip()
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return "https://www.douyin.com" + link
    return link

def is_real_douyin_result_link(link: str) -> bool:
    link = normalize_video_link(link or "")
    return any(token in link for token in ("/video/", "modal_id=", "/note/", "aweme_id="))

def is_synthetic_candidate(video: dict) -> bool:
    source = str(video.get("linkSource") or video.get("url_source") or "")
    return source in {"element-id", "waterfall-html", "dataset-regex"}

def normalize_result(video: dict) -> dict:
    link = normalize_video_link(video.get("link", ""))
    video_id = extract_video_id(link)
    title, title_source = pick_title_and_source(video)
    return {
        "title": title,
        "link": link,
        "video_id": video_id,
        "type": video.get("type", "unknown"),
        "title_source": video.get("title_source", title_source),
        "url_source": video.get("url_source", video.get("linkSource", "")),
    }

def merge_results_prefer_new(results: list, seen_ids: set, limit: int):
    normalized = []
    used = set()
    for video in results:
        item = normalize_result(video)
        vid = item.get("video_id") or item.get("link")
        if not item.get("link") or vid in used:
            continue
        used.add(vid)
        normalized.append(item)
    fresh = [v for v in normalized if v.get("video_id") not in seen_ids]
    old = [v for v in normalized if v.get("video_id") in seen_ids]
    merged = enrich_missing_titles((fresh + old)[:limit])
    fresh_used = len([v for v in merged if v.get("video_id") not in seen_ids])
    seen_fill = len(merged) - fresh_used
    return merged, fresh_used, seen_fill

def print_search_results(results: list, header="--- KẾT QUẢ TÌM KIẾM ---"):
    print(f"\n{header}")
    for i, video in enumerate(results, 1):
        print(f"{i}. {video['title']} | 🔗 {video['link']}")

def has_bad_cached_title(results: list) -> bool:
    return any(clean_title(v.get("title", ""), v.get("text", ""), v.get("aria", ""), v.get("alt", ""), v.get("outerHTML", "")) == "[Không tiêu đề]" for v in results)

def cache_needs_title_refresh(results: list) -> bool:
    return any(not v.get("title_source") for v in results)

def cache_needs_url_refresh(results: list) -> bool:
    for item in results:
        link = item.get("link", "")
        if not item.get("url_source"):
            return True
        if "/jingxuan/search/" in link or ("/search/" in link and "modal_id=" in link):
            return True
        if re.fullmatch(r"https://www\\.douyin\\.com/video/\\d+", link or ""):
            return True
        if item.get("url_source") in {"element-id", "waterfall-html", "dataset-regex", "html-regex"}:
            return True
    return False

def get_cdp_candidates():
    cdp_hosts = []
    for name in ("DOUYIN_CDP_URL", "DOUYIN_CDP_ENDPOINT"):
        if os.environ.get(name):
            cdp_hosts.append(os.environ[name])
    cdp_hosts.extend([
        "http://127.0.0.1:9222", "http://127.0.0.1:9223",
        "http://172.21.0.1:9223", "http://172.21.0.1:9222",
        "http://172.19.0.1:9223", "http://172.19.0.1:9222",
        "http://172.17.0.1:9222", "http://172.18.0.1:9222",
        "http://host.docker.internal:9222",
        "http://192.168.1.33:9223", "http://host.docker.internal:9223",
        "http://172.17.0.1:9223", "http://172.18.0.1:9223",
    ])
    deduped = []
    seen = set()
    for url in cdp_hosts:
        if url and url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped

def write_netscape_cookies(cookies: list, output_path: str) -> int:
    lines = ["# Netscape HTTP Cookie File"]
    count = 0
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get("domain") or "").strip()
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")
        path = str(cookie.get("path") or "/")
        if not domain or not name:
            continue
        host_only = bool(cookie.get("hostOnly", False))
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        if host_only:
            include_subdomains = "FALSE"
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = cookie.get("expires", cookie.get("expirationDate", 0))
        try:
            expires = int(float(expires or 0))
        except Exception:
            expires = 0
        if expires < 0:
            expires = 0
        lines.append("\t".join([domain, include_subdomains, path, secure, str(expires), name, value]))
        count += 1
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return count

def cookie_metadata(cookies: list) -> dict:
    domains = sorted({str(c.get("domain") or "") for c in cookies if isinstance(c, dict) and c.get("domain")})
    names = {str(c.get("name") or "") for c in cookies if isinstance(c, dict)}
    important = ["ttwid", "passport_csrf_token", "sid_guard", "sessionid", "sid_tt", "s_v_web_id", "odin_tt"]
    return {
        "count": len(cookies),
        "domains": domains,
        "important_present": [name for name in important if name in names],
    }

async def export_cookies_from_cdp(output_path: str) -> int:
    browser = None
    try:
        async with async_playwright() as playwright:
            connected_url = ""
            for cdp_url in get_cdp_candidates():
                try:
                    browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=5000)
                    connected_url = cdp_url
                    break
                except Exception:
                    continue
            if not browser:
                print("STATUS: CDP_OFFLINE")
                print("Không kết nối được Chrome/CDP để export fresh Douyin cookies.")
                return 1
            contexts = browser.contexts
            if not contexts:
                print("STATUS: NO_CONTEXT")
                print("CDP reachable nhưng không tìm thấy browser context.")
                return 1
            ctx = contexts[0]
            cookies = await ctx.cookies(["https://www.douyin.com", "https://douyin.com"])
            douyin_cookies = [
                c for c in cookies
                if "douyin.com" in str(c.get("domain") or "") or "iesdouyin.com" in str(c.get("domain") or "")
            ]
            count = write_netscape_cookies(douyin_cookies, output_path)
            meta = cookie_metadata(douyin_cookies)
            print("STATUS: OK")
            print(f"CDP: connected ({connected_url})")
            print(f"Cookies exported: {count}")
            print("Domains: " + (", ".join(meta["domains"]) if meta["domains"] else "none"))
            print("Important cookies present: " + (", ".join(meta["important_present"]) if meta["important_present"] else "none"))
            print(f"Output: {output_path}")
            if count == 0:
                return 1
            return 0
    finally:
        if browser:
            await browser.close()

def log(msg: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

async def random_delay(min_s: float = 5.0, max_s: float = 15.0) -> None:
    delay = random.uniform(min_s, max_s)
    log(f"⏳ Đợi {delay:.1f}s...")
    chunks = int(delay * 10)
    for _ in range(chunks):
        if task_data.get("timeout_triggered"):
            raise TimeoutError("Task timeout triggered")
        current = load_task()
        if current and current.get("cancel_requested"):
            raise asyncio.CancelledError("Task cancelled")
        await asyncio.sleep(0.1)

def get_captcha_cooldown():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                expire_time = data.get("expire", 0)
                if time.time() < expire_time:
                    return expire_time - time.time()
        except Exception:
            pass
    return 0

def set_captcha_cooldown():
    cooldown = random.uniform(180, 600)
    data = {"expire": time.time() + cooldown}
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)
    log(f"⏸️ Đặt cooldown CAPTCHA {cooldown/60:.1f} phút")

def check_search_cache(keyword: str):
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if keyword in data:
                    item = data[keyword]
                    if time.time() - item["time"] < 1800:
                        return item["results"]
        except Exception:
            pass
    return None

def save_search_cache(keyword: str, results: list):
    data = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data[keyword] = {"time": time.time(), "results": results}
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

async def check_captcha(page: Page) -> str:
    JS_CHECK = '''() => {
        function isVisible(el) {
            if (!el) return false;
            let style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0' || style.opacity === '0.0') return false;
            let rect = el.getBoundingClientRect();
            if (rect.width < 100 || rect.height < 100) return false;
            return true;
        }

        let selectors = [
            "div#captcha-verify-image", 
            ".captcha_verify_container", 
            "div#captcha_container",
            "#verify-bar",
            "iframe[src*='verifycenter']"
        ];
        
        let hasHidden = false;
        
        for (let sel of selectors) {
            let els = document.querySelectorAll(sel);
            for (let el of els) {
                if (isVisible(el)) return "CAPTCHA_VISIBLE";
                hasHidden = true;
            }
        }
        
        let texts = ["安全验证", "拖拽", "滑块", "请完成验证", "请选择", "拖拽到这里", "请完成下列验证后继续", "按住左边按钮拖动完成上方拼图", "Verify you are human"];
        let walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while (node = walker.nextNode()) {
            let text = node.nodeValue.trim();
            if (text.length > 0) {
                for (let ct of texts) {
                    if (text.includes(ct)) {
                        let parent = node.parentElement;
                        if (parent) {
                            let style = window.getComputedStyle(parent);
                            if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && style.opacity !== '0.0') {
                                let card = parent.closest('div, section, iframe');
                                if (card && isVisible(card)) {
                                    return "CAPTCHA_VISIBLE";
                                }
                            }
                            hasHidden = true;
                        }
                    }
                }
            }
        }
        
        return hasHidden ? "CAPTCHA_HIDDEN" : "NO_CAPTCHA";
    }'''
    try:
        res = await page.evaluate(JS_CHECK)
        if res == "CAPTCHA_VISIBLE":
            log("🚨 [DETECTION] Phát hiện CAPTCHA đang hiển thị (VISIBLE)!")
            update_task(captcha_visible=True)
        elif res == "CAPTCHA_HIDDEN":
            log("ℹ️ [DETECTION] Có node CAPTCHA nhưng đang ẩn (HIDDEN), tiếp tục chạy bình thường.")
        return res
    except Exception as e:
        log(f"Lỗi khi check captcha: {e}")
        return "NO_CAPTCHA"

async def get_douyin_state(page: Page) -> str:
    cap_status = await check_captcha(page)
    if cap_status == "CAPTCHA_VISIBLE":
        return "CAPTCHA_WAIT"
    if await page.query_selector("video") or await page.query_selector("div[data-e2e='feed-active-video']") or await page.query_selector(".xgplayer"):
        return "LOGGED_IN"
    logged_in_signals = [
        "div.user-avatar", "text=发布视频", "text=Contribute",
        "text=notify", "text=private message", "text=通知",
        "text=私信", "text=Publish video", "text=Đóng góp",
        "text=thông báo", "text=tin nhắn riêng", "text=của tôi",
        "text=已关注", "text=关注"
    ]
    for sel in logged_in_signals:
        if await page.query_selector(sel):
            return "LOGGED_IN"
    
    if await page.query_selector("div.login-desktop-scan") or await page.query_selector("text=Đăng nhập") or await page.query_selector("text=登录") or await page.query_selector("text=Log in"):
        return "QR_LOGIN"
    
    return "NOT_LOGGED_IN"

def safe_url_hint(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc
        path = parsed.path[-80:] if parsed.path else ""
        return f"{host}{path}"
    except Exception:
        return "unknown"

def is_video_candidate_url(url: str) -> bool:
    url = str(url or "")
    if not url.startswith("http"):
        return False
    hay = url.lower()
    positive = [
        ".mp4", "video_mp4", "playwm", "play_addr", "aweme/v1/play",
        "douyinvod", "snssdk", "pstatp", "play?", "media-video-avc1", "/video/tos/"
    ]
    negative = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".m3u8", "audio", "poster", "cover", ".js", ".css", ".json", "manifest", "index.html", "captcha", "verify", "douyinstatic.com", "douyin_pc_client", "douyin-pc-web"]
    return any(x in hay for x in positive) and not any(x in hay for x in negative)

def is_audio_candidate_url(url: str) -> bool:
    url = str(url or "")
    if not url.startswith("http"):
        return False
    hay = url.lower()
    positive = ["audio", "mp4a", "audio_track", "/audio/", "media-audio", "mime_type=audio"]
    negative = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".js", ".css", ".json", "manifest", "index.html", "captcha", "verify"]
    return any(x in hay for x in positive) and not any(x in hay for x in negative)

def score_media_candidate(url: str, content_type: str = "", content_length: int = 0) -> int:
    score = 0
    hay = str(url or "").lower()
    ctype = str(content_type or "").lower()
    if ".mp4" in hay:
        score += 40
    if "play_addr" in hay or "aweme/v1/play" in hay:
        score += 25
    if "playwm" in hay:
        score -= 80
    if any(x in hay for x in ("douyinvod", "byteimg", "snssdk", "pstatp", "tos-cn")):
        score += 20
    if any(x in hay for x in ("watermark", "wm", "logo")):
        score -= 35
    if any(x in hay for x in ("nwm", "no_watermark", "clean")):
        score += 35
    if "video" in ctype:
        score += 20
    if content_length > 1024 * 1024:
        score += min(40, content_length // (1024 * 1024))
    return score

def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")

def clean_media_resolver_enabled() -> bool:
    return env_flag("DOUYIN_CLEAN_MEDIA_RESOLVER", False)

def clean_media_policy() -> str:
    if (
        not env_flag("DOUYIN_CLEAN_ONLY_DEFAULT", False)
        and env_flag("DOUYIN_ALLOW_WATERMARKED_FALLBACK", True)
    ):
        return ALLOW_WATERMARKED_FALLBACK
    # Prefer a clean stream, but keep the dub pipeline usable when only a
    # platform-watermarked stream is available. Operators can still opt into
    # strict clean-only behavior with DOUYIN_CLEAN_ONLY_DEFAULT=1.
    return CLEAN_ONLY

def media_request_headers(range_probe: bool = False) -> dict:
    headers = {
        "Referer": "https://www.douyin.com/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    }
    if range_probe:
        headers["Range"] = "bytes=0-65535"
    return headers

def response_status(resp) -> int:
    try:
        return int(resp.status)
    except Exception:
        return 0

async def extract_media_from_dom(page: Page):
    return await page.evaluate('''() => {
        const out = [];
        const push = (url, source) => {
            if (url && typeof url === 'string' && url.startsWith('http')) out.push({url, source});
        };
        const video = document.querySelector('video');
        if (video) {
            push(video.currentSrc || '', 'dom_video_currentSrc');
            push(video.src || '', 'dom_video_src');
            for (const s of Array.from(video.querySelectorAll('source[src]'))) push(s.src, 'dom_source');
        }
        for (const s of Array.from(document.scripts)) {
            const text = s.textContent || '';
            const patterns = [
                /https?:\\/\\/[^"'\\s]+(?:playwm|video_mp4|aweme\\/v1\\/play|douyinvod|byteimg|snssdk|pstatp)[^"'\\s]*/g,
                /https?:\\/\\/[^"'\\s]+\\.mp4[^"'\\s]*/g
            ];
            for (const re of patterns) {
                const matches = text.match(re) || [];
                for (const m of matches.slice(0, 10)) push(m, 'script_state');
            }
        }
        return out;
    }''')

async def download_video_via_browser(ctx, page: Page, video_url: str, output_path: str) -> int:
    media_candidates = []
    audio_candidates = []
    seen = set()
    seen_audio = set()

    def add_candidate(url: str, source: str, content_type: str = "", content_length: int = 0):
        if not is_video_candidate_url(url):
            return
        if url.startswith("blob:"):
            return
        if url in seen:
            return
        seen.add(url)
        media_candidates.append({
            "url": url,
            "source": source,
            "content_type": content_type,
            "content_length": int(content_length or 0),
            "score": score_media_candidate(url, content_type, int(content_length or 0)),
        })

    def add_audio_candidate(url: str, source: str, content_type: str = "", content_length: int = 0):
        if not is_audio_candidate_url(url):
            return
        if url in seen_audio:
            return
        seen_audio.add(url)
        audio_candidates.append({
            "url": url,
            "source": source,
            "content_type": content_type,
            "content_length": int(content_length or 0),
            "score": score_media_candidate(url, content_type, int(content_length or 0)),
        })

    async def handle_response(resp):
        try:
            url = resp.url
            headers = resp.headers or {}
            ctype = headers.get("content-type", "")
            clen = headers.get("content-length", "0")
            try:
                clen = int(clen)
            except Exception:
                clen = 0
            resource_type = ""
            try:
                resource_type = resp.request.resource_type
            except Exception:
                resource_type = ""
            if is_video_candidate_url(url) or "video" in str(ctype).lower() or resource_type == "media":
                add_candidate(url, f"network_response:{resource_type or 'unknown'}", ctype, clen)
            if is_audio_candidate_url(url) or "audio" in str(ctype).lower():
                add_audio_candidate(url, f"network_response:{resource_type or 'unknown'}", ctype, clen)
        except Exception:
            pass

    async def handle_request(req):
        try:
            url = req.url
            if is_video_candidate_url(url):
                resource_type = getattr(req, "resource_type", "")
                add_candidate(url, f"network_request:{resource_type or 'unknown'}")
            elif is_audio_candidate_url(url):
                resource_type = getattr(req, "resource_type", "")
                add_audio_candidate(url, f"network_request:{resource_type or 'unknown'}")
        except Exception:
            pass

    page.on("response", handle_response)
    page.on("request", handle_request)

    await page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
    await random_delay(2.0, 4.0)
    state = await get_douyin_state(page)
    if state == "CAPTCHA_WAIT":
        print("STATUS: CAPTCHA_REQUIRED")
        print("Douyin đang yêu cầu captcha/verify trên Chrome thật.")
        return 2
    if state in ("QR_LOGIN", "NOT_LOGGED_IN"):
        print("STATUS: LOGIN_REQUIRED")
        print("Phiên Douyin trên Chrome/CDP chưa sẵn sàng để tải video.")
        return 3

    for selector in ["video", "div[data-e2e='feed-active-video']", ".xgplayer", "[data-e2e='feed-active-video'] video"]:
        try:
            await page.wait_for_selector(selector, timeout=10000)
            break
        except Exception:
            pass

    try:
        await page.mouse.move(640, 360)
        await page.mouse.click(640, 360)
    except Exception:
        pass
    await random_delay(4.0, 8.0)

    for _ in range(2):
        try:
            for item in await extract_media_from_dom(page):
                add_candidate(item.get("url", ""), item.get("source", "dom"))
            if media_candidates:
                break
            await page.mouse.wheel(0, 300)
            await random_delay(3.0, 5.0)
        except Exception:
            pass

    media_candidates = [c for c in media_candidates if not any(bad in c["url"].lower() for bad in ("douyin_pc_client.mp4", "nocaptcha", "manifest.json"))]
    audio_candidates = [c for c in audio_candidates if not any(bad in c["url"].lower() for bad in ("manifest.json", "nocaptcha"))]
    media_candidates.sort(key=lambda x: (x["score"], x["content_length"]), reverse=True)
    audio_candidates.sort(key=lambda x: (x["score"], x["content_length"]), reverse=True)
    if not media_candidates:
        print("STATUS: MEDIA_URL_NOT_FOUND")
        print("Không tìm được media URL từ network/DOM/JS state.")
        return 4

    resolver_enabled = clean_media_resolver_enabled()
    resolver_policy = clean_media_policy()
    if resolver_enabled:
        resolution = resolve_media_candidates(media_candidates, policy=resolver_policy)
        if not resolution.accepted:
            print("STATUS: CLEAN_MEDIA_NOT_FOUND")
            print("Không có media candidate đạt chính sách clean_only; đã từ chối fallback có watermark/không rõ nguồn.")
            print(f"Clean media rejection counts: {safe_rejection_summary(resolution.rejected_counts)}")
            print(f"Clean media candidate sources: {safe_candidate_source_summary(media_candidates)}")
            return 6
        media_candidates = [
            {
                "url": item.url,
                "source": item.source,
                "content_type": item.content_type,
                "content_length": item.content_length,
                "score": item.score,
                "cleanliness": item.cleanliness,
                "clean_evidence": item.evidence,
                "candidate_id": item.candidate_id,
            }
            for item in resolution.ordered_candidates
        ]
        selected_report = resolution.to_public_dict().get("selected") or {}
        print(
            "Clean media resolver: "
            f"policy={resolver_policy}, selected={selected_report.get('cleanliness', 'unknown')}, "
            f"candidate={selected_report.get('candidate_id', 'none')}"
        )

    req_ctx = ctx.request
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    for candidate in media_candidates[:8]:
        url = candidate["url"]
        watermark_likely = "playwm" in url.lower() or "watermark" in url.lower()
        clean_hint = any(token in url.lower() for token in ("no_watermark", "nwm", "clean"))
        log(f"🎬 Thử tải media source={candidate['source']} host={safe_url_hint(url)}")
        try:
            probe_resp = await req_ctx.get(url, headers=media_request_headers(range_probe=True), timeout=30000)
            probe_headers = probe_resp.headers or {}
            probe_status = response_status(probe_resp)
            declared_probe_size = int(probe_headers.get("content-length", "0") or 0)
            # A server that ignores Range may otherwise make Playwright buffer the
            # whole file during a supposedly bounded validation request.
            if probe_status != 206 and (not declared_probe_size or declared_probe_size > 256 * 1024):
                log(f"⚠️ Media range probe was not bounded source={candidate['source']}")
                continue
            probe_body = await probe_resp.body()
            probe_validation = validate_media_probe_response(probe_status, probe_headers, probe_body)
            if not probe_validation.accepted:
                log(f"⚠️ Media range probe rejected source={candidate['source']} reason={probe_validation.reason}")
                continue

            resp = await req_ctx.get(url, headers=media_request_headers(), timeout=60000)
            if not resp.ok:
                continue
            ctype = (resp.headers or {}).get("content-type", "")
            declared_size = int((resp.headers or {}).get("content-length", "0") or 0)
            if declared_size > 512 * 1024 * 1024:
                log(f"⚠️ Media candidate exceeds download size cap source={candidate['source']}")
                continue
            body = await resp.body()
            full_validation = validate_media_probe_response(response_status(resp), resp.headers or {}, body[:65536])
            if not full_validation.accepted:
                log(f"⚠️ Media payload rejected source={candidate['source']} reason={full_validation.reason}")
                continue
            if len(body) < 1024 * 1024:
                continue
            with open(output_path, "wb") as f:
                f.write(body)
            needs_audio = True
            try:
                import subprocess
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", output_path],
                    capture_output=True, text=True, check=False
                )
                needs_audio = not probe.stdout.strip()
            except Exception:
                needs_audio = True
            if needs_audio and audio_candidates:
                audio_path = output_path + ".audio.tmp"
                for ac in audio_candidates[:6]:
                    try:
                        aresp = await req_ctx.get(ac["url"], headers=media_request_headers(), timeout=60000)
                        if not aresp.ok:
                            continue
                        abody = await aresp.body()
                        if len(abody) < 128 * 1024:
                            continue
                        with open(audio_path, "wb") as af:
                            af.write(abody)
                        import subprocess
                        muxed = output_path + ".muxed.mp4"
                        mux = subprocess.run(
                            ["ffmpeg", "-y", "-i", output_path, "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-shortest", muxed],
                            capture_output=True, text=True, check=False
                        )
                        if mux.returncode == 0 and os.path.exists(muxed) and os.path.getsize(muxed) > 1024 * 1024:
                            os.replace(muxed, output_path)
                            os.remove(audio_path)
                            needs_audio = False
                            break
                    except Exception as e:
                        log(f"⚠️ Audio candidate failed source={ac['source']} err={e}")
                        continue
            print("STATUS: OK")
            print(f"Media source: {candidate['source']}")
            print(f"Media host: {safe_url_hint(url)}")
            if resolver_enabled:
                print(
                    "Media URL-level cleanliness: "
                    f"{candidate.get('cleanliness', 'unknown')} ({resolver_policy}); "
                    "embedded source overlays are not removed"
                )
            elif clean_hint and not watermark_likely:
                print("Media cleanliness: preferred no-watermark candidate selected")
            elif watermark_likely:
                print("Media cleanliness: fallback source may contain Douyin logo/watermark")
            else:
                print("Media cleanliness: no explicit watermark marker detected; source kept as best available candidate")
            if audio_candidates:
                print(f"Audio candidates: {min(len(audio_candidates), 6)}")
            print(f"Saved: {output_path}")
            print(f"Size: {len(body)}")
            return 0
        except Exception as e:
            log(f"⚠️ Download candidate failed source={candidate['source']} err={e}")
            continue

    print("STATUS: DOWNLOAD_HTTP_ERROR")
    print("Đã tìm thấy media URL nhưng tải file không thành công trong browser context.")
    return 5

async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fetch_douyin_v2.py host-login | search <keyword> | download-video <url> --out <file> | export-cookies --out <file> | clear-captcha | status | stop")
        sys.exit(1)

    mode = sys.argv[1].lower()
    param = sys.argv[2] if len(sys.argv) > 2 else ""
    limit = 5
    include_seen = True
    args = sys.argv[3:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--limit", "-n") and i + 1 < len(args):
            try:
                limit = max(1, min(50, int(args[i + 1])))
            except ValueError:
                pass
            i += 2
            continue
        if arg.startswith("--limit="):
            try:
                limit = max(1, min(50, int(arg.split("=", 1)[1])))
            except ValueError:
                pass
        elif arg.isdigit():
            limit = max(1, min(50, int(arg)))
        elif arg in ("--allow-duplicates", "--include-seen"):
            include_seen = True
        elif arg == "--new-only":
            include_seen = False
        i += 1

    if mode == "export-cookies":
        out_path = ""
        raw = [param] + args if param else args
        j = 0
        while j < len(raw):
            arg = raw[j]
            if arg == "--out" and j + 1 < len(raw):
                out_path = raw[j + 1]
                j += 2
                continue
            if arg.startswith("--out="):
                out_path = arg.split("=", 1)[1]
            j += 1
        if not out_path:
            print("Usage: python3 fetch_douyin_v2.py export-cookies --out /tmp/douyin-cookies.txt")
            sys.exit(1)
        rc = await export_cookies_from_cdp(out_path)
        sys.exit(rc)

    if mode == "download-video":
        douyin_url = param
        out_path = ""
        raw = args
        j = 0
        while j < len(raw):
            arg = raw[j]
            if arg == "--out" and j + 1 < len(raw):
                out_path = raw[j + 1]
                j += 2
                continue
            if arg.startswith("--out="):
                out_path = arg.split("=", 1)[1]
            j += 1
        if not douyin_url or not out_path:
            print("Usage: python3 fetch_douyin_v2.py download-video <douyin_url> --out /tmp/input.mp4")
            sys.exit(1)
        browser = None
        try:
            async with async_playwright() as playwright:
                for cdp_url in get_cdp_candidates():
                    try:
                        browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=5000)
                        print(f"CDP: connected ({cdp_url})")
                        break
                    except Exception:
                        continue
                if not browser:
                    print("STATUS: CDP_OFFLINE")
                    print("Không kết nối được Chrome/CDP để tải video bằng browser context.")
                    sys.exit(1)
                if not browser.contexts:
                    print("STATUS: NO_CONTEXT")
                    print("CDP reachable nhưng không có browser context.")
                    sys.exit(1)
                ctx = browser.contexts[0]
                page = await ctx.new_page()
                rc = await download_video_via_browser(ctx, page, douyin_url, out_path)
                await page.close()
                sys.exit(rc)
        finally:
            if browser:
                await browser.close()

    if mode == "status":
        task = load_task()
        if task:
            print(json.dumps(task, ensure_ascii=False, indent=2))
        else:
            print("No active task")
        sys.exit(0)
        
    if mode == "stop":
        task = load_task()
        if task:
            task["cancel_requested"] = True
            with open(TASK_FILE, "w") as f:
                json.dump(task, f)
            print("Đã gửi yêu cầu dừng task.")
        else:
            print("No active task")
        sys.exit(0)

    if mode == "clear-captcha":
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            log("✅ Đã xóa trạng thái CAPTCHA_WAIT")
            print("STATUS: OK")
        sys.exit(0)

    log("=" * 70)
    log(f"🚀 DOUYIN CDP STEALTH | mode={mode} | param={param}")

    if mode == "search" and param:
        update_task(status="IDLE", step="CHECK_CACHE", keyword=param)
        asyncio.create_task(progress_reporter())
        
        cached_results = check_search_cache(param)
        if cached_results:
            seen_ids = load_seen()
            cache_out, fresh_count, seen_fill_count = merge_results_prefer_new(cached_results, seen_ids, limit if include_seen else 10_000)
            if not include_seen:
                cache_out = [v for v in cache_out if v.get("video_id") not in seen_ids][:limit]
                seen_fill_count = 0
            if cache_out and len(cache_out) >= limit and not has_bad_cached_title(cache_out[:limit]) and not cache_needs_title_refresh(cache_out[:limit]) and not cache_needs_url_refresh(cache_out[:limit]):
                cache_out = cache_out[:limit]
                log(f"✅ Dùng cache kết quả cho '{param}' limit={limit}")
                print("STATUS: LOGGED_IN")
                if seen_fill_count > 0:
                    print(f"Ghi chú: chỉ có {fresh_count} video mới trong cache, đã bổ sung {seen_fill_count} video đã seen để đủ tối đa {limit}.")
                for video in cache_out:
                    seen_ids.add(video.get('video_id') or extract_video_id(video['link']))
                save_seen(seen_ids)
                print_search_results(cache_out)
                update_task(status="COMPLETED", step="CACHE_HIT", videos_extracted=len(cache_out))
                sys.exit(0)
            else:
                log("🔄 Cache thiếu limit, còn title/link cũ hoặc thiếu metadata, tiến hành tìm kiếm trực tiếp...")

        rem = get_captcha_cooldown()
        if rem > 0:
            log(f"⏸️ Đang trong thời gian chờ CAPTCHA ({rem/60:.1f} phút nữa)")
            print("STATUS: CAPTCHA_WAIT")
            print("Douyin đang yêu cầu captcha. Sonic đã dừng để tránh bị khóa/chặn thêm. Vui lòng mở AnyDesk trên điện thoại để xử lý captcha trên Chrome thật.")
            update_task(status="CAPTCHA_WAIT", step="COOLDOWN_ACTIVE", captcha_visible=True)
            send_telegram("Douyin: CAPTCHA_WAIT | mở AnyDesk để xử lý")
            sys.exit(1)

    page = None
    browser = None
    try:
        async with async_playwright() as playwright:
            update_task(status="CONNECT_CDP", step="CONNECTING")
            cdp_hosts = get_cdp_candidates()

            connected = False
            for cdp_url in cdp_hosts:
                try:
                    log(f"🔌 Thử CDP: {cdp_url}")
                    browser = await playwright.chromium.connect_over_cdp(cdp_url, timeout=5000)
                    log(f"✅ Kết nối thành công tới: {cdp_url}")
                    connected = True
                    break
                except Exception as e:
                    continue

            if not connected:
                log("🔴 CDP_OFFLINE")
                print("STATUS: CDP_OFFLINE")
                update_task(status="ERROR", last_error="CDP_OFFLINE")
                sys.exit(1)

            contexts = browser.contexts
            if not contexts:
                print("LỖI: Không tìm thấy context browser.")
                update_task(status="ERROR", last_error="NO_CONTEXT")
                sys.exit(1)
            
            ctx = contexts[0]
            pages = ctx.pages
            
            douyin_pages = [p for p in pages if "douyin.com" in p.url]
            if len(douyin_pages) > 1:
                log(f"🧹 Đang đóng {len(douyin_pages)-1} tab Douyin thừa...")
                for p in douyin_pages[1:]:
                    await p.close()
                page = douyin_pages[0]
            elif douyin_pages:
                page = douyin_pages[0]
            elif pages:
                page = pages[0]
            else:
                page = await ctx.new_page()

            update_task(step="GOTO_DOUYIN", current_url=page.url)
            if "douyin.com" not in page.url:
                await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
                await random_delay(5.0, 10.0)

            update_task(status="CHECK_LOGIN")
            state = await get_douyin_state(page)

            if mode == "host-login":
                print(f"STATUS: {state}")
                if state == "CAPTCHA_WAIT":
                    print("Douyin đang yêu cầu captcha/verify, không thể xử lý tự động trong headless container.")
                sys.exit(0)

            elif mode == "search" and param:
                if state == "CAPTCHA_WAIT":
                    set_captcha_cooldown()
                    debug_png = os.path.join(SKILL_DIR, "session", "captcha_debug.png")
                    await page.screenshot(path=debug_png)
                    print("STATUS: CAPTCHA_WAIT")
                    print("Douyin đang yêu cầu captcha. Sonic đã dừng để tránh bị khóa/chặn thêm. Vui lòng mở AnyDesk trên điện thoại để xử lý captcha trên Chrome thật.")
                    update_task(status="CAPTCHA_WAIT", debug_files=["captcha_debug.png"], captcha_visible=True)
                    send_telegram("Douyin: CAPTCHA_WAIT | mở AnyDesk để xử lý")
                    sys.exit(1)
                    
                if state != "LOGGED_IN":
                    print(f"STATUS: {state}")
                    print("🔴 Không thể tìm kiếm vì chưa đăng nhập hoặc bị chặn. Sếp xử lý thủ công nhé.")
                    update_task(status="ERROR", last_error="NOT_LOGGED_IN")
                    sys.exit(1)
                
                update_task(status="SEARCHING", step="ENTER_KEYWORD")
                
                log("🔎 Thực hiện gõ từ khóa vào thanh tìm kiếm thay vì direct URL...")
                search_input = await page.query_selector('input[data-e2e="searchbar-input"]')
                if not search_input:
                    await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
                    await random_delay(4.0, 8.0)
                    search_input = await page.query_selector('input[data-e2e="searchbar-input"]')
                
                if search_input:
                    await search_input.fill("")
                    await random_delay(1.0, 3.0)
                    await search_input.fill(param)
                    await random_delay(1.0, 3.0)
                    await search_input.press("Enter")
                    
                    search_btn = await page.query_selector('button[data-e2e="searchbar-button"], button.search-button')
                    if search_btn:
                        await random_delay(0.5, 1.0)
                        await search_btn.click()
                else:
                    log("🔴 Vẫn không tìm thấy ô search, thử mở bằng direct URL...")
                    search_url = f"https://www.douyin.com/search/{urllib.parse.quote(param)}"
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                
                update_task(step="WAIT_RESULTS")
                await random_delay(8.0, 15.0)

                state = await get_douyin_state(page)
                if state == "CAPTCHA_WAIT":
                    set_captcha_cooldown()
                    debug_png = os.path.join(SKILL_DIR, "session", "captcha_debug.png")
                    await page.screenshot(path=debug_png)
                    print("STATUS: CAPTCHA_WAIT")
                    print("Douyin đang yêu cầu captcha. Sonic đã dừng để tránh bị khóa/chặn thêm. Vui lòng mở AnyDesk trên điện thoại để xử lý captcha trên Chrome thật.")
                    update_task(status="CAPTCHA_WAIT", debug_files=["captcha_debug.png"], captcha_visible=True)
                    send_telegram("Douyin: CAPTCHA_WAIT | mở AnyDesk để xử lý")
                    sys.exit(1)

                seen_ids = load_seen()
                
                JS_EXTRACT_A_B = '''(seenIdsJson) => {
                    let seen_globally = new Set(JSON.parse(seenIdsJson));
                    let results = [];
                    let seen = new Set();
                    
                    document.querySelectorAll('a').forEach(a => {
                        let href = a.getAttribute('href');
                        if (!href) return;
                        if (href.includes('/video/') || href.includes('modal_id=') || href.includes('aweme_id=') || href.includes('note/') || href.includes('/discover')) {
                            let link = href.startsWith('http') ? href : 'https://www.douyin.com' + href;
                            let idMatch = link.match(new RegExp('(?:video/|modal_id=|aweme_id=|note/)(\\\\d{8,})'));
                            let vidId = idMatch ? idMatch[1] : link;
                            if (seen.has(vidId)) return;
                            seen.add(vidId);
                            
                            let card = a.closest('li') || a.closest('[id^="waterfall_item_"]') || a.closest('[class*="waterfall"]') || a.parentElement?.parentElement?.parentElement;
                            let text = card ? (card.innerText || '') : (a.innerText || '');
                            let aria = a.getAttribute('aria-label') || card?.getAttribute('aria-label') || '';
                            let alt = card?.querySelector('img[alt]')?.getAttribute('alt') || a.querySelector('img[alt]')?.getAttribute('alt') || '';
                            let dataTitle = a.getAttribute('title') || card?.getAttribute('title') || card?.dataset?.title || card?.dataset?.desc || card?.dataset?.description || '';
                            let title = bestTitleFromSources(dataTitle, aria, alt, text);
                            
                            results.push({title: title.trim(), link: link, video_id: vidId, type: 'direct', text: text.substring(0, 300), aria: aria, alt: alt, data_title: dataTitle, title_source: title === dataTitle ? 'data_title' : title === aria ? 'aria' : title === alt ? 'alt' : 'dom_text'});
                        }
                    });

                    let candidates = [];
                    const badTitles = new Set(['相关搜索','综合','视频','用户','直播','热点','搜索','Đăng nhập','登录','Log in','推荐','精选','发现','查看更多','查看详情','打开看看','关注','评论','分享','收藏']);
                    const noiseRe = new RegExp('^(?:\\\\d{1,2}:\\\\d{2}(?::\\\\d{2})?|\\\\d+(?:\\\\.\\\\d+)?万?|\\\\d+赞|\\\\d+评论|\\\\d+分享|\\\\d+天前|\\\\d+小时前|\\\\d+分钟前|\\\\d+月\\\\d+日|20\\\\d{2}[-.]\\\\d{1,2}[-.]\\\\d{1,2})$');
                    function cleanLine(s) { return (s || '').replace(new RegExp('\\\\s+', 'g'), ' ').trim(); }
                    function isNoise(s) {
                        s = cleanLine(s);
                        if (!s || badTitles.has(s)) return true;
                        if (noiseRe.test(s)) return true;
                        if (new RegExp('^[\\\\d:万赞.\\\\w\\\\s]+$').test(s)) return true;
                        return false;
                    }
                    function scoreLine(s) {
                        let score = 0;
                        if (new RegExp('[\\\\u4e00-\\\\u9fff]').test(s)) score += 8;
                        if (s.includes('#')) score += 4;
                        if (s.length >= 8) score += 3;
                        if (s.length >= 20) score += 2;
                        if (new RegExp('原创|动画|二次元|一口气|合集|系列|漫画|漫动画|沙雕').test(s)) score += 5;
                        return score;
                    }
                    function bestTitleFromSources(...sources) {
                        let lines = [];
                        for (let src of sources) {
                            for (let line of String(src || '').split(new RegExp('\\n+'))) {
                                line = cleanLine(line);
                                if (!isNoise(line)) lines.push(line);
                            }
                        }
                        if (!lines.length) return '[Không tiêu đề]';
                        lines.sort((a,b) => (scoreLine(b) - scoreLine(a)) || (b.length - a.length));
                        let title = lines[0];
                        return title.length > 120 ? title.slice(0,117).trim() + '...' : title;
                    }
                    let elements = document.querySelectorAll('div, li, a');
                    function isRealResultCard(el, rect) {
                        if (!el || !rect) return false;
                        if (el.id === 'root' || el.closest('#douyin-navigation') || el.closest('[data-e2e="douyin-navigation"]')) return false;
                        if (el.closest('[class*="searchbar"], [data-e2e*="searchbar"]')) return false;
                        if (rect.width > 460 || rect.height > 620) return false;
                        if (el.id && el.id.startsWith('waterfall_item_')) return true;
                        if (el.querySelector('.search-result-card')) return true;
                        if (el.closest('.search-result-card')) return true;
                        return false;
                    }
                    elements.forEach(el => {
                        let rect = el.getBoundingClientRect();
                        if (rect.width > 120 && rect.height > 120 && rect.top >= 0 && rect.top < window.innerHeight * 2 && isRealResultCard(el, rect)) {
                            let text = el.innerText || "";
                            let durationMatch = text.match(new RegExp('\\\\b\\\\d{1,2}:\\\\d{2}(?::\\\\d{2})?\\\\b'));
                            let hasDuration = !!durationMatch;
                            let hasLike = text.includes('万') || text.includes('赞') || el.querySelector('svg');
                            
                            if (hasDuration || hasLike || el.querySelector('img') || el.querySelector('video')) {
                                let aria = el.getAttribute('aria-label') || '';
                                let alt = el.querySelector('img[alt]')?.getAttribute('alt') || '';
                                let dataTitle = el.getAttribute('title') || el.dataset?.title || el.dataset?.desc || el.dataset?.description || '';
                                let author = cleanLine(el.querySelector('[class*="author"], [class*="user"], [class*="nickname"]')?.innerText || '');
                                let hashtagMatches = Array.from(text.matchAll(new RegExp('#[^#\\\\s]{1,30}', 'g'))).map(m => m[0]).slice(0, 4).join(' ');
                                let title = bestTitleFromSources(dataTitle, aria, alt, text, author, hashtagMatches);
                                
                                let link = "";
                                let linkSource = "";
                                let anchors = [];
                                if (el.tagName === 'A') anchors.push(el);
                                anchors.push(...Array.from(el.querySelectorAll('a[href]')));
                                let closestAnchor = el.closest && el.closest('a[href]');
                                if (closestAnchor) anchors.push(closestAnchor);
                                for (let a of anchors) {
                                    let href = a.getAttribute('href') || '';
                                    if (href.includes('/video/') || href.includes('modal_id=') || href.includes('aweme_id=') || href.includes('/note/')) {
                                        link = href.startsWith('http') ? href : 'https://www.douyin.com' + href;
                                        linkSource = 'anchor';
                                        break;
                                    }
                                }
                                if (!link) {
                                    let html = el.outerHTML || '';
                                    let m = html.match(new RegExp('(?:video/|modal_id=|aweme_id=|note/)(\\\\d{8,})'));
                                    if (m && isRealResultCard(el, rect)) {
                                        link = 'https://www.douyin.com/video/' + m[1];
                                        linkSource = 'html-regex';
                                    }
                                }
                                if (!link) {
                                    let idText = el.id || '';
                                    let m = idText.match(new RegExp('waterfall_item_(\\\\d{8,})'));
                                    if (m) {
                                        link = 'https://www.douyin.com/video/' + m[1];
                                        linkSource = 'element-id';
                                    }
                                }
                                if (!link) {
                                    let html = el.outerHTML || '';
                                    let m = html.match(new RegExp('waterfall_item_(\\\\d{8,})'));
                                    if (m) {
                                        link = 'https://www.douyin.com/video/' + m[1];
                                        linkSource = 'waterfall-html';
                                    }
                                }
                                if (!link) {
                                    let datasetText = JSON.stringify(el.dataset || {});
                                    let m = datasetText.match(new RegExp('(?:^|\\\\D)(\\\\d{12,})(?:\\\\D|$)'));
                                    if (m) {
                                        link = 'https://www.douyin.com/video/' + m[1];
                                        linkSource = 'dataset-regex';
                                    }
                                }
                                let vidMatch = link ? link.match(new RegExp('(?:video/|modal_id=|aweme_id=|note/)(\\\\d{8,})')) : null;
                                let videoId = vidMatch ? vidMatch[1] : '';
                                let alreadyExists = results.some(r => {
                                    if (!r.link || !link) return false;
                                    let rm = r.link.match(new RegExp('(?:video/|modal_id=|aweme_id=|note/)(\\\\d{8,})'));
                                    let rv = rm ? rm[1] : r.link;
                                    return rv === (videoId || link);
                                });
                                
                                if (!alreadyExists && title.length > 2 && link && videoId) {
                                    candidates.push({
                                        title: title,
                                        link: link,
                                        video_id: videoId,
                                        linkSource: linkSource,
                                        duration: durationMatch ? durationMatch[0] : "",
                                        rect: {cx: rect.x + rect.width/2, cy: rect.y + rect.height/2, width: rect.width, height: rect.height},
                                        text: text.substring(0, 300),
                                        aria: aria,
                                        alt: alt,
                                        data_title: dataTitle,
                                        author: author,
                                        hashtags: hashtagMatches,
                                        title_source: title === dataTitle ? 'data_title' : title === aria ? 'aria' : title === alt ? 'alt' : 'dom_text',
                                        tagName: el.tagName,
                                        className: el.className || "",
                                        outerHTML: el.outerHTML ? el.outerHTML.substring(0, 1000) : ""
                                    });
                                }
                            }
                        }
                    });
                    
                    let final_candidates = [];
                    for (let c of candidates) {
                        let isDup = final_candidates.some(fc => Math.abs(fc.rect.cx - c.rect.cx) < 50 && Math.abs(fc.rect.cy - c.rect.cy) < 50);
                        if (!isDup) final_candidates.push(c);
                    }

                    return {results: results.slice(0, 10), candidates: final_candidates.slice(0, 20)};
                }'''

                async def scroll_and_extract():
                    update_task(status="SCROLLING", step="SCROLL_DOWN")
                    for _ in range(3):
                        await page.mouse.wheel(0, random.randint(2000, 4000))
                        await random_delay(4.0, 8.0)
                    log("📝 Đang extract kết quả bằng Javascript (Tầng A & B)...")
                    update_task(status="EXTRACTING_CARDS", step="EVALUATE_JS")
                    return await page.evaluate(JS_EXTRACT_A_B, json.dumps(list(seen_ids)))

                data = await scroll_and_extract()
                results = data['results']
                candidates = data['candidates']
                
                update_task(cards_found=len(candidates), links_found=len(results), videos_extracted=len(results))

                total_a = await page.evaluate("document.querySelectorAll('a').length")
                log(f"Thống kê DOM: Total <a>: {total_a} | Direct: {len(results)} | Candidates: {len(candidates)}")

                if len(results) < 5 and len(candidates) > 0:
                    promoted = 0
                    current_ids = {extract_video_id(r.get('link', '')) for r in results}
                    for c in candidates:
                        link = c.get('link') if isinstance(c, dict) else None
                        if not link:
                            continue
                        if c.get('linkSource') in ('dataset-regex', 'html-regex'):
                            continue
                        if not (('modal_id=' in link) or ('/share/' in link) or ('/discover' in link) or ('/video/' in link and c.get('video_id'))):
                            continue
                        vid_id = extract_video_id(link)
                        if vid_id not in current_ids:
                            results.append({"title": c.get('title', '[Không tiêu đề]'), "link": link, "type": "candidate_link", "video_id": c.get('video_id', ''), "text": c.get('text', ''), "aria": c.get('aria', ''), "alt": c.get('alt', ''), "data_title": c.get('data_title', ''), "author": c.get('author', ''), "hashtags": c.get('hashtags', ''), "outerHTML": c.get('outerHTML', ''), "title_source": c.get('title_source', 'candidate_same_video_id'), "url_source": c.get('linkSource', '')})
                            current_ids.add(vid_id)
                            promoted += 1
                            update_task(videos_extracted=len(results))
                            if len(results) >= limit:
                                break
                    if promoted:
                        log(f"✅ Tầng B2: lấy được {promoted} link video/card hợp lệ, không cần click modal.")

                if len(results) < limit and len(candidates) > 0:
                    update_task(status="CLICKING_CARDS", step="CLICK_FALLBACK")
                    log(f"🔎 Tầng C: Click search result để lấy URL thật sau khi modal/trang mở. Current links={len(results)}, candidates={len(candidates)}")
                    for idx, c in enumerate(candidates):
                        if len(results) >= limit:
                            break
                        candidate_id = extract_video_id(c.get('link') or c.get('video_id') or '')
                        if candidate_id in {extract_video_id(r.get('link', '')) for r in results}:
                            continue
                        log(f"🖱️ Click card {idx+1}: {c['title'][:20]}...")
                        update_task(cards_clicked=idx+1)
                        try:
                            prev_url = page.url
                            before_pages = set(p.url for p in contexts[0].pages)
                            await page.mouse.click(c['rect']['cx'], c['rect']['cy'])
                            await random_delay(3.0, 6.0)
                            
                            st = await get_douyin_state(page)
                            if st == "CAPTCHA_WAIT":
                                set_captcha_cooldown()
                                log("🚨 Dính CAPTCHA khi click card.")
                                break
                                
                            contexts = browser.contexts
                            pages = contexts[0].pages
                            if len(pages) > 1:
                                new_page = pages[-1]
                                await new_page.wait_for_load_state("domcontentloaded", timeout=15000)
                                await random_delay(2.0, 4.0)
                                curr_url = new_page.url
                                if '/video/' in curr_url or 'modal_id=' in curr_url or 'aweme_id=' in curr_url or 'note/' in curr_url:
                                    vid_id = extract_video_id(curr_url)
                                    if vid_id not in {extract_video_id(r.get('link', '')) for r in results}:
                                        results.append({"title": c['title'], "link": curr_url, "type": "new_tab", "video_id": vid_id, "text": c.get('text', ''), "aria": c.get('aria', ''), "alt": c.get('alt', ''), "data_title": c.get('data_title', ''), "author": c.get('author', ''), "hashtags": c.get('hashtags', ''), "outerHTML": c.get('outerHTML', ''), "title_source": c.get('title_source', 'candidate_same_video_id'), "url_source": "clicked_new_tab"})
                                        update_task(videos_extracted=len(results))
                                await new_page.close()
                                await random_delay(1.0, 2.0)
                            else:
                                curr_url = page.url
                                modal_url = curr_url
                                if not is_real_douyin_result_link(modal_url):
                                    try:
                                        modal_url = await page.evaluate('''(wantedId) => {
                                            const href = location.href;
                                            if (href.includes('modal_id=') || href.includes('/video/') || href.includes('/note/') || href.includes('aweme_id=')) return href;
                                            const anchors = Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(h => h && (h.includes('modal_id=') || h.includes('/video/') || h.includes('/note/') || h.includes('aweme_id=')));
                                            const preferred = anchors.find(h => wantedId && (h.includes('modal_id=' + wantedId) || h.includes('/video/' + wantedId) || h.includes('aweme_id=' + wantedId)));
                                            if (preferred) return preferred;
                                            const html = document.documentElement.outerHTML || '';
                                            const modalMatch = wantedId ? html.match(new RegExp('https://www\\\\.douyin\\\\.com[^\"\\'\\s>]+modal_id=' + wantedId + '[^\"\\'\\s>]*')) : null;
                                            if (modalMatch && modalMatch[0]) return modalMatch[0];
                                            return anchors[0] || href;
                                        }''', candidate_id)
                                    except Exception:
                                        modal_url = curr_url
                                if modal_url != prev_url or is_real_douyin_result_link(modal_url):
                                    if '/video/' in modal_url or 'modal_id=' in modal_url or 'aweme_id=' in modal_url or 'note/' in modal_url:
                                        curr_url = modal_url
                                        vid_id = extract_video_id(curr_url)
                                        if vid_id not in {extract_video_id(r.get('link', '')) for r in results}:
                                            results.append({"title": c['title'], "link": curr_url, "type": "clicked", "video_id": vid_id, "text": c.get('text', ''), "aria": c.get('aria', ''), "alt": c.get('alt', ''), "data_title": c.get('data_title', ''), "author": c.get('author', ''), "hashtags": c.get('hashtags', ''), "outerHTML": c.get('outerHTML', ''), "title_source": c.get('title_source', 'candidate_same_video_id'), "url_source": "clicked_modal_or_page"})
                                            update_task(videos_extracted=len(results))
                                    if page.url != prev_url:
                                        await page.go_back(wait_until="domcontentloaded", timeout=15000)
                                        await random_delay(3.0, 6.0)
                                    else:
                                        await page.keyboard.press("Escape")
                                        await random_delay(1.0, 2.0)
                                else:
                                    if 'modal_id=' in curr_url:
                                        vid_id = extract_video_id(curr_url)
                                        if vid_id not in {extract_video_id(r.get('link', '')) for r in results}:
                                            results.append({"title": c['title'], "link": curr_url, "type": "modal", "video_id": vid_id, "text": c.get('text', ''), "aria": c.get('aria', ''), "alt": c.get('alt', ''), "data_title": c.get('data_title', ''), "author": c.get('author', ''), "hashtags": c.get('hashtags', ''), "outerHTML": c.get('outerHTML', ''), "title_source": c.get('title_source', 'candidate_same_video_id'), "url_source": "clicked_modal"})
                                            update_task(videos_extracted=len(results))
                                    
                                    close_btn = await page.query_selector("div.xgplayer-close, div.close-icon, svg.close, div[data-e2e='video-close']")
                                    if close_btn:
                                        await close_btn.click()
                                    else:
                                        await page.keyboard.press("Escape")
                                    await random_delay(2.0, 4.0)
                        except Exception as e:
                            log(f"Lỗi khi click card: {e}")

                if not results:
                    log("🔴 Không extract được kết quả, tiến hành lưu debug...")
                    if len(candidates) > 0:
                        print("STATUS: EXTRACTOR_CARD_FOUND_URL_FAILED")
                        print("Tìm thấy candidate card nhưng không extract được URL.")
                        update_task(status="EXTRACTOR_FAILED", last_error="CARD_FOUND_URL_FAILED")
                    else:
                        print("STATUS: EXTRACTOR_FAILED")
                        print("Không extract được kết quả, đã lưu screenshot và HTML debug để kiểm tra selector.")
                        update_task(status="EXTRACTOR_FAILED", last_error="EXTRACTOR_FAILED")
                    
                    debug_png = os.path.join(SKILL_DIR, "session", "search_debug.png")
                    debug_html = os.path.join(SKILL_DIR, "session", "search_debug.html")
                    debug_json = os.path.join(SKILL_DIR, "session", "search_candidates.json")
                    
                    await page.screenshot(path=debug_png)
                    html_content = await page.evaluate('''() => {
                        let clone = document.documentElement.cloneNode(true);
                        clone.querySelectorAll('script').forEach(s => s.remove());
                        return clone.outerHTML;
                    }''')
                    with open(debug_html, "w", encoding="utf-8") as f: f.write(html_content)
                    with open(debug_json, "w", encoding="utf-8") as f: json.dump(candidates, f, ensure_ascii=False, indent=2)
                    
                    update_task(debug_files=["search_debug.png", "search_debug.html", "search_candidates.json"])
                    sys.exit(1)

                results_out, fresh_count, seen_fill_count = merge_results_prefer_new(results, seen_ids, limit if include_seen else 10_000)
                if not include_seen:
                    results_out = [v for v in results_out if v.get("video_id") not in seen_ids][:limit]
                    seen_fill_count = 0
                results_out = results_out[:limit]
                new_count = len(results_out)

                for video in results_out:
                    seen_ids.add(video.get('video_id') or extract_video_id(video['link']))
                save_seen(seen_ids)

                save_search_cache(param, results_out)

                update_task(status="COMPLETED", step="DONE", videos_extracted=new_count)

                print("STATUS: LOGGED_IN")
                if seen_fill_count > 0:
                    print(f"Ghi chú: chỉ có {fresh_count} video mới, đã bổ sung {seen_fill_count} video đã seen để đủ tối đa {limit}.")
                elif new_count < limit:
                    print(f"Ghi chú: chỉ tìm được {new_count}/{limit} video phù hợp trên trang hiện tại.")
                print_search_results(results_out)
        
    except (TimeoutError, PlaywrightTimeoutError, asyncio.CancelledError) as e:
        log("🔴 Tiến trình bị hủy hoặc timeout.")
        print(f"STATUS: SEARCH_TIMEOUT")
        print(f"Lỗi: {e}. Tiến trình tốn quá nhiều thời gian và đã bị dừng an toàn.")
        try:
            debug_png = os.path.join(SKILL_DIR, "session", "search_debug.png")
            debug_html = os.path.join(SKILL_DIR, "session", "search_debug.html")
            if page:
                await page.screenshot(path=debug_png)
                html_content = await page.evaluate('''() => document.documentElement.outerHTML''')
                with open(debug_html, "w", encoding="utf-8") as f: f.write(html_content)
            update_task(status="SEARCH_TIMEOUT", debug_files=["search_debug.png", "search_debug.html"], last_error=str(e))
            elapsed = int(time.time() - task_data["started_at"])
            send_telegram(f"Douyin: SEARCH_TIMEOUT | {elapsed}s | debug saved")
        except:
            pass
        sys.exit(1)
    except Exception as e:
        log(f"🔴 LỖI: {e}")
        print(f"LỖI: {e}")
        update_task(status="ERROR", last_error=str(e))
        sys.exit(1)
    finally:
        if browser:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

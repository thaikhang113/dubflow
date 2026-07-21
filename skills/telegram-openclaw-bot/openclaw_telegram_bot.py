#!/usr/bin/env python3
"""
Telegram -> OpenClaw chat bridge.

This is intentionally separate from the existing one-way Telegram senders.
It long-polls Telegram updates, allowlists chats/topics, sends user text to the
local OpenAI-compatible OpenClaw/9Router endpoint, and replies in the same chat.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_TELEGRAM_CONFIG = "~/.openclaw/config/channels/telegram.json"
DEFAULT_STATE_FILE = "~/.openclaw/state/telegram-openclaw-bot.json"
DEFAULT_AI_BASE = "http://127.0.0.1:20128/v1"
DEFAULT_AI_MODEL = "ollama/minimax-m3:cloud"
TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_MAX_TEXT = 3900


class BotError(Exception):
    """Expected runtime error that is safe to show in logs without secrets."""


class TelegramApiError(BotError):
    def __init__(self, method: str, status: int | None, description: str):
        super().__init__(f"{method} failed")
        self.method = method
        self.status = status
        self.description = description


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        return int(raw)
    except Exception:
        return default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        return float(raw)
    except Exception:
        return default


def expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def stable_mask(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    return f"sha256:{digest}"


def log_event(event: str, level: str = "info", **fields: Any) -> None:
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "level": level,
        "event": event,
    }
    record.update(fields)
    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise BotError(f"cannot_read_json:{path}") from exc


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_id_list(raw: str) -> list[str]:
    values: list[str] = []
    for item in re.split(r"[,;\s]+", raw or ""):
        item = item.strip()
        if item:
            values.append(item)
    return values


def normalize_ai_model(raw: str | None) -> str:
    model = str(raw or "").strip()
    if not model:
        return DEFAULT_AI_MODEL
    aliases = {
        "api deepseek": DEFAULT_AI_MODEL,
        "deepseek": DEFAULT_AI_MODEL,
        "minimax": DEFAULT_AI_MODEL,
    }
    alias = aliases.get(model.lower())
    if alias:
        return alias
    if re.search(r"\s", model):
        return DEFAULT_AI_MODEL
    return model


def load_telegram_file(path: Path) -> dict[str, str]:
    data = read_json(path)
    telegram = data.get("telegram", data) if isinstance(data, dict) else {}
    bots = telegram.get("bots") or []
    token = ""
    if bots and isinstance(bots[0], dict):
        token = str(bots[0].get("token") or "")
    chat_id = str(telegram.get("chatId") or telegram.get("chat_id") or "")
    thread_id = str(telegram.get("messageThreadId") or telegram.get("message_thread_id") or "")
    return {"token": token, "chat_id": chat_id, "thread_id": thread_id}


def load_config(args: argparse.Namespace) -> dict[str, Any]:
    config_path = expand_path(args.telegram_config)
    file_cfg = load_telegram_file(config_path)

    token = (
        os.environ.get("TELEGRAM_BOT_TOKEN")
        or os.environ.get("OPENCLAW_TELEGRAM_BOT_TOKEN")
        or file_cfg.get("token")
        or ""
    )
    chat_id = (
        os.environ.get("TELEGRAM_CHAT_ID")
        or os.environ.get("OPENCLAW_TELEGRAM_CHAT_ID")
        or file_cfg.get("chat_id")
        or ""
    )
    thread_id = (
        os.environ.get("TELEGRAM_MESSAGE_THREAD_ID")
        or os.environ.get("OPENCLAW_TELEGRAM_MESSAGE_THREAD_ID")
        or file_cfg.get("thread_id")
        or ""
    )

    allowed_chats = set(parse_id_list(os.environ.get("OPENCLAW_TELEGRAM_ALLOWED_CHAT_IDS", "")))
    if chat_id:
        allowed_chats.add(str(chat_id))

    return {
        "telegram_config": str(config_path),
        "token": token,
        "chat_id": str(chat_id),
        "thread_id": str(thread_id),
        "allowed_chats": allowed_chats,
        "allow_any_chat": env_bool("OPENCLAW_TELEGRAM_ALLOW_ANY_CHAT", False),
        "allow_all_threads": env_bool("OPENCLAW_TELEGRAM_ALLOW_ALL_THREADS", False),
        "group_reply_mode": os.environ.get("OPENCLAW_TELEGRAM_GROUP_REPLY_MODE", "all").strip().lower(),
        "state_file": expand_path(os.environ.get("OPENCLAW_TELEGRAM_STATE_FILE", DEFAULT_STATE_FILE)),
        "skip_backlog": env_bool("OPENCLAW_TELEGRAM_SKIP_BACKLOG", True),
        "poll_timeout": env_int("OPENCLAW_TELEGRAM_POLL_TIMEOUT_SECONDS", 25),
        "ai_base": os.environ.get("OPENCLAW_TELEGRAM_AI_BASE")
        or os.environ.get("NINEROUTER_API_BASE")
        or DEFAULT_AI_BASE,
        "ai_model": normalize_ai_model(
            os.environ.get("OPENCLAW_TELEGRAM_AI_MODEL")
            or os.environ.get("NINEROUTER_MODEL")
            or DEFAULT_AI_MODEL
        ),
        "ai_key": os.environ.get("OPENCLAW_TELEGRAM_AI_KEY")
        or os.environ.get("NINEROUTER_API_KEY")
        or "",
        "ai_timeout": env_int("OPENCLAW_TELEGRAM_AI_TIMEOUT_SECONDS", 60),
        "max_input_chars": env_int("OPENCLAW_TELEGRAM_MAX_INPUT_CHARS", 4000),
        "max_output_tokens": env_int("OPENCLAW_TELEGRAM_MAX_OUTPUT_TOKENS", 700),
        "temperature": env_float("OPENCLAW_TELEGRAM_TEMPERATURE", 0.3),
    }


def require_config(config: dict[str, Any]) -> None:
    if not config["token"]:
        raise BotError("missing_telegram_token")
    if not config["allow_any_chat"] and not config["allowed_chats"]:
        raise BotError("missing_allowed_chat")


def telegram_call(token: str, method: str, body: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        description = f"http_{exc.code}"
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
            description = str(payload.get("description") or description)[:200]
        except Exception:
            pass
        raise TelegramApiError(method, exc.code, description) from exc
    except urllib.error.URLError as exc:
        raise TelegramApiError(method, None, exc.reason.__class__.__name__) from exc
    except Exception as exc:
        raise TelegramApiError(method, None, exc.__class__.__name__) from exc

    if not payload.get("ok"):
        raise TelegramApiError(method, None, str(payload.get("description") or "not_ok")[:200])
    return payload


def ai_chat(config: dict[str, Any], messages: list[dict[str, str]]) -> str:
    payload = {
        "model": config["ai_model"],
        "messages": messages,
        "temperature": config["temperature"],
        "stream": False,
        "think": False,
        "max_tokens": config["max_output_tokens"],
    }
    headers = {"Content-Type": "application/json"}
    if config.get("ai_key"):
        headers["Authorization"] = "Bearer " + str(config["ai_key"])
    req = urllib.request.Request(
        str(config["ai_base"]).rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config["ai_timeout"]) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as exc:
        raise BotError(f"ai_request_failed:{exc.__class__.__name__}") from exc

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
        if content:
            return str(content).strip()
    raise BotError("ai_empty_response")


def get_message(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    sender = message.get("from") or {}
    if isinstance(sender, dict) and sender.get("is_bot"):
        return None
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    if not chat_id:
        return None
    thread_id = message.get("message_thread_id")
    sender_name = " ".join(
        part
        for part in [
            str(sender.get("first_name") or "").strip(),
            str(sender.get("last_name") or "").strip(),
        ]
        if part
    )
    return {
        "update_id": update.get("update_id"),
        "message_id": message.get("message_id"),
        "chat_id": chat_id,
        "chat_type": str(chat.get("type") or ""),
        "thread_id": str(thread_id) if thread_id is not None else "",
        "text": text.strip(),
        "sender_name": sender_name or str(sender.get("username") or "Telegram user"),
    }


def strip_bot_mention(text: str, bot_username: str = "") -> tuple[str, bool]:
    if not bot_username:
        return text.strip(), False
    pattern = re.compile(rf"@{re.escape(bot_username)}\b", re.IGNORECASE)
    matched = bool(pattern.search(text))
    return pattern.sub("", text).strip(), matched


def command_name(text: str, bot_username: str = "") -> str:
    raw = text.strip().split(maxsplit=1)[0] if text.strip().startswith("/") else ""
    if not raw:
        return ""
    if "@" in raw:
        name, username = raw[1:].split("@", 1)
        if bot_username and username.lower() != bot_username.lower():
            return ""
        return name.lower()
    return raw[1:].lower()


def is_allowed_message(message: dict[str, Any], config: dict[str, Any], bot_username: str = "") -> tuple[bool, str]:
    chat_id = str(message.get("chat_id") or "")
    if not config.get("allow_any_chat") and chat_id not in config.get("allowed_chats", set()):
        return False, "chat_not_allowlisted"

    expected_thread = str(config.get("thread_id") or "")
    chat_type = str(message.get("chat_type") or "")
    actual_thread = str(message.get("thread_id") or "")
    if expected_thread and not config.get("allow_all_threads") and chat_type in {"group", "supergroup"}:
        if actual_thread != expected_thread:
            return False, "thread_not_allowlisted"

    mode = str(config.get("group_reply_mode") or "all").lower()
    text = str(message.get("text") or "")
    cmd = command_name(text, bot_username)
    _, mentioned = strip_bot_mention(text, bot_username)
    if chat_type in {"group", "supergroup"}:
        if mode == "command" and not cmd:
            return False, "group_command_required"
        if mode == "mention" and not (cmd or mentioned):
            return False, "group_mention_required"
    return True, "ok"


def build_ai_messages(user_text: str, sender_name: str, max_input_chars: int) -> list[dict[str, str]]:
    clean_text = user_text.strip()
    if len(clean_text) > max_input_chars:
        clean_text = clean_text[:max_input_chars].rstrip() + "\n[message truncated]"
    system = os.environ.get("OPENCLAW_TELEGRAM_SYSTEM_PROMPT") or (
        "Ban la tro ly OpenClaw tong trong Telegram. Tra loi bang tieng Viet tu nhien, "
        "ngan gon, huu ich. Neu nguoi dung hoi ve video/dubbing/dashboard thi giai thich "
        "theo ngu canh OpenClaw, nhung khong tu nhan da chay lenh hay sua file. "
        "Khong tiet lo token, duong dan bi mat, API key, cookie, proxy, hay noi dung cau hinh nhay cam."
    )
    user = f"Tin nhan Telegram tu {sender_name}:\n{clean_text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def chunk_message(text: str, limit: int = TELEGRAM_MAX_TEXT) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return ["Mình chưa nhận được nội dung phản hồi từ OpenClaw."]
    chunks: list[str] = []
    remaining = clean
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit * 0.5:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit * 0.5:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def send_reply(config: dict[str, Any], message: dict[str, Any], text: str) -> None:
    for chunk in chunk_message(text):
        body: dict[str, Any] = {
            "chat_id": message["chat_id"],
            "text": chunk,
            "reply_to_message_id": message.get("message_id"),
            "disable_web_page_preview": True,
        }
        if message.get("thread_id"):
            body["message_thread_id"] = message["thread_id"]
        telegram_call(config["token"], "sendMessage", body, timeout=30)


def command_reply(command: str) -> str | None:
    if command in {"start", "help"}:
        return (
            "OpenClaw bot đang nghe tin nhắn trong chat/topic đã cho phép.\n"
            "Lệnh nhanh: /ping, /help.\n"
            "Nếu trong group bot chỉ trả lời command/mention mà không thấy tin thường, hãy tắt privacy mode trong BotFather."
        )
    if command == "ping":
        return "pong - OpenClaw Telegram bot đang hoạt động."
    if command == "privacy":
        return "Bot chỉ xử lý chat/topic allowlist, không log token/API key/raw message text."
    return None


def handle_update(config: dict[str, Any], update: dict[str, Any], bot_username: str) -> None:
    message = get_message(update)
    if not message:
        return
    allowed, reason = is_allowed_message(message, config, bot_username)
    if not allowed:
        log_event(
            "telegram_message_ignored",
            chat=stable_mask(message.get("chat_id")),
            thread=stable_mask(message.get("thread_id")),
            reason=reason,
        )
        return

    text, mentioned = strip_bot_mention(str(message["text"]), bot_username)
    command = command_name(text or str(message["text"]), bot_username)
    reply = command_reply(command) if command else None
    if reply is None:
        prompt_text = re.sub(r"^/\w+(?:@\w+)?\s*", "", text).strip() if command else text
        if not prompt_text:
            prompt_text = str(message["text"]).strip()
        messages = build_ai_messages(prompt_text, str(message.get("sender_name") or "Telegram user"), config["max_input_chars"])
        try:
            reply = ai_chat(config, messages)
        except BotError as exc:
            log_event(
                "openclaw_ai_failed",
                "warn",
                chat=stable_mask(message.get("chat_id")),
                thread=stable_mask(message.get("thread_id")),
                error=str(exc),
            )
            reply = "Mình nhận được tin nhắn rồi, nhưng OpenClaw AI hiện chưa trả lời được. Bạn thử lại sau ít phút nha."

    send_reply(config, message, reply)
    log_event(
        "telegram_message_replied",
        chat=stable_mask(message.get("chat_id")),
        thread=stable_mask(message.get("thread_id")),
        text_len=len(str(message.get("text") or "")),
        mentioned=mentioned,
        command=command,
    )


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    except BotError:
        return {}


def prime_offset(config: dict[str, Any]) -> int | None:
    payload = telegram_call(
        config["token"],
        "getUpdates",
        {"timeout": 0, "limit": 100, "allowed_updates": ["message"]},
        timeout=15,
    )
    updates = payload.get("result") or []
    ids = [int(item.get("update_id")) for item in updates if isinstance(item, dict) and item.get("update_id") is not None]
    return max(ids) + 1 if ids else None


def run_loop(config: dict[str, Any]) -> None:
    require_config(config)
    me = telegram_call(config["token"], "getMe", {}, timeout=15).get("result") or {}
    bot_username = str(me.get("username") or "")
    state = load_state(config["state_file"])
    offset = state.get("offset")
    if offset is None and config.get("skip_backlog"):
        offset = prime_offset(config)
        if offset is not None:
            state["offset"] = offset
            write_json(config["state_file"], state)
    log_event(
        "telegram_openclaw_bot_started",
        bot=bot_username,
        allowed_chats=len(config.get("allowed_chats") or []),
        thread_configured=bool(config.get("thread_id")),
        reply_mode=config.get("group_reply_mode"),
        ai_model=config.get("ai_model"),
    )

    stop = {"value": False}

    def on_stop(_sig: int, _frame: Any) -> None:
        stop["value"] = True

    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)

    while not stop["value"]:
        body: dict[str, Any] = {
            "timeout": config["poll_timeout"],
            "limit": 25,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            body["offset"] = int(offset)
        try:
            payload = telegram_call(config["token"], "getUpdates", body, timeout=config["poll_timeout"] + 10)
        except TelegramApiError as exc:
            log_event("telegram_poll_failed", "warn", method=exc.method, status=exc.status, error=exc.description)
            time.sleep(5)
            continue

        for update in payload.get("result") or []:
            try:
                handle_update(config, update, bot_username)
            except TelegramApiError as exc:
                log_event("telegram_reply_failed", "warn", method=exc.method, status=exc.status, error=exc.description)
            except Exception as exc:
                log_event("telegram_update_failed", "error", error=exc.__class__.__name__)
            if isinstance(update, dict) and update.get("update_id") is not None:
                offset = int(update["update_id"]) + 1
                state["offset"] = offset
                write_json(config["state_file"], state)

    log_event("telegram_openclaw_bot_stopped")


def print_health(config: dict[str, Any]) -> int:
    ok = bool(config.get("token")) and (config.get("allow_any_chat") or bool(config.get("allowed_chats")))
    print(json.dumps({
        "ok": ok,
        "token_configured": bool(config.get("token")),
        "allowed_chat_count": len(config.get("allowed_chats") or []),
        "thread_configured": bool(config.get("thread_id")),
        "group_reply_mode": config.get("group_reply_mode"),
        "ai_base": config.get("ai_base"),
        "ai_model": config.get("ai_model"),
        "state_file": str(config.get("state_file")),
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenClaw Telegram reply bot")
    parser.add_argument("--telegram-config", default=os.environ.get("TELEGRAM_CONFIG", DEFAULT_TELEGRAM_CONFIG))
    parser.add_argument("--run", action="store_true", help="Run long-polling loop")
    parser.add_argument("--health", action="store_true", help="Check config without network calls")
    parser.add_argument("--no-skip-backlog", action="store_true", help="Process queued Telegram updates on first start")
    args = parser.parse_args(argv)
    if args.no_skip_backlog:
        os.environ["OPENCLAW_TELEGRAM_SKIP_BACKLOG"] = "0"
    config = load_config(args)
    if args.health:
        return print_health(config)
    if args.run:
        try:
            run_loop(config)
            return 0
        except BotError as exc:
            log_event("telegram_openclaw_bot_failed", "error", error=str(exc))
            return 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

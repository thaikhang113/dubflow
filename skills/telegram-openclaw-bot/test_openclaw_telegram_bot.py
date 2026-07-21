#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("openclaw_telegram_bot.py")
spec = importlib.util.spec_from_file_location("openclaw_telegram_bot", MODULE_PATH)
bot = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bot)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def base_config(**overrides):
    data = {
        "allowed_chats": {"-1001"},
        "allow_any_chat": False,
        "thread_id": "26",
        "allow_all_threads": False,
        "group_reply_mode": "all",
        "max_input_chars": 40,
    }
    data.update(overrides)
    return data


def test_allowlisted_group_topic_accepts_plain_text():
    message = {"chat_id": "-1001", "chat_type": "supergroup", "thread_id": "26", "text": "Xin chao"}
    ok, reason = bot.is_allowed_message(message, base_config(), "openclaw_bot")
    assert_equal((ok, reason), (True, "ok"), "plain text in allowed topic")


def test_wrong_thread_rejected_by_default():
    message = {"chat_id": "-1001", "chat_type": "supergroup", "thread_id": "99", "text": "Xin chao"}
    ok, reason = bot.is_allowed_message(message, base_config(), "openclaw_bot")
    assert_equal((ok, reason), (False, "thread_not_allowlisted"), "wrong topic")


def test_group_mention_mode_rejects_unmentioned_plain_text():
    message = {"chat_id": "-1001", "chat_type": "supergroup", "thread_id": "26", "text": "Xin chao"}
    ok, reason = bot.is_allowed_message(message, base_config(group_reply_mode="mention"), "openclaw_bot")
    assert_equal((ok, reason), (False, "group_mention_required"), "mention mode")
    message["text"] = "Xin chao @openclaw_bot"
    ok, reason = bot.is_allowed_message(message, base_config(group_reply_mode="mention"), "openclaw_bot")
    assert_equal((ok, reason), (True, "ok"), "mention mode with bot mention")


def test_command_mentions_other_bot_are_ignored():
    assert_equal(bot.command_name("/ping@other_bot", "openclaw_bot"), "", "other bot command")
    assert_equal(bot.command_name("/ping@openclaw_bot", "openclaw_bot"), "ping", "own bot command")


def test_chunk_message_keeps_telegram_limit():
    chunks = bot.chunk_message("x" * 9000, limit=3900)
    if not chunks or any(len(chunk) > 3900 for chunk in chunks):
        raise AssertionError("chunk_message produced invalid Telegram chunks")


def test_prompt_truncates_long_user_text():
    messages = bot.build_ai_messages("a" * 100, "Sep", max_input_chars=40)
    user = messages[-1]["content"]
    if "[message truncated]" not in user:
        raise AssertionError("long Telegram prompt was not truncated")
    if "token" not in messages[0]["content"].lower():
        raise AssertionError("system prompt should mention secret safety")


def test_model_display_label_normalizes_to_default_model():
    assert_equal(bot.normalize_ai_model("API deepseek"), "ollama/minimax-m3:cloud", "display model label")
    assert_equal(bot.normalize_ai_model("ollama/glm-5.2:cloud"), "ollama/glm-5.2:cloud", "real model id")


def run_all():
    tests = [
        test_allowlisted_group_topic_accepts_plain_text,
        test_wrong_thread_rejected_by_default,
        test_group_mention_mode_rejects_unmentioned_plain_text,
        test_command_mentions_other_bot_are_ignored,
        test_chunk_message_keeps_telegram_limit,
        test_prompt_truncates_long_user_text,
        test_model_display_label_normalizes_to_default_model,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")


if __name__ == "__main__":
    run_all()

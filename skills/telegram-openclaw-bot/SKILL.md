---
name: telegram-openclaw-bot
description: Telegram long-polling bridge that lets the OpenClaw bot reply to normal messages in an allowlisted chat or forum topic.
---

# Telegram OpenClaw Bot

This skill adds a host-side Telegram listener for normal chat messages. It is separate from the existing one-way Telegram senders used by dashboard alerts, content-monitor, and video result delivery.

## What It Does

- Reads the existing Telegram config from `$HOME/.openclaw/config/channels/telegram.json` or env.
- Allows only configured chat IDs by default.
- In forum supergroups, replies only in the configured `messageThreadId` unless explicitly allowed.
- Calls the local OpenAI-compatible OpenClaw/9Router endpoint to generate a short Vietnamese reply.
- Does not log Telegram tokens, API keys, or raw message text.

## Run Manually

```bash
python3 /home/haonguyen/.openclaw/workspace/skills/telegram-openclaw-bot/openclaw_telegram_bot.py --health
python3 /home/haonguyen/.openclaw/workspace/skills/telegram-openclaw-bot/openclaw_telegram_bot.py --run
```

## Important Telegram Group Note

Telegram BotFather privacy mode can hide normal group messages from bots. If the bot replies to `/ping` or direct mentions but not plain messages, disable privacy mode in BotFather for this bot.

## Useful Env

- `OPENCLAW_TELEGRAM_ALLOWED_CHAT_IDS`: comma-separated extra chat IDs.
- `OPENCLAW_TELEGRAM_GROUP_REPLY_MODE`: `all` (default), `mention`, or `command`.
- `OPENCLAW_TELEGRAM_ALLOW_ALL_THREADS`: set `1` to respond in every topic in the allowed group.
- `OPENCLAW_TELEGRAM_AI_BASE`: default `http://127.0.0.1:20128/v1`.
- `OPENCLAW_TELEGRAM_AI_MODEL`: default `ollama/minimax-m3:cloud`.
- `OPENCLAW_TELEGRAM_STATE_FILE`: default `$HOME/.openclaw/state/telegram-openclaw-bot.json`.
- `OPENCLAW_TELEGRAM_SKIP_BACKLOG`: default `1`, so startup does not reply to old queued messages.

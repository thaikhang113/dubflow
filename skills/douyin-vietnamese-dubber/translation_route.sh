#!/usr/bin/env bash
# Resolve the text translation route without inheriting host-wide OpenClaw routes.
# This file is sourced by run.sh and by the focused route regression test.

TRANSLATION_DEFAULT_OLLAMA_MODEL="ollama/translategemma:4b"
TRANSLATION_REQUESTED_MODEL="${NINEROUTER_MODEL:-}"
TRANSLATION_PROVIDER="${OPENCLAW_AI_PROVIDER:-}"
TRANSLATION_PROVIDER="${TRANSLATION_PROVIDER,,}"

# Host runners used display labels such as "API deepseek".  They are not model
# identifiers and must never select a provider.  A model that contains
# whitespace is treated the same way.
if [[ "$TRANSLATION_REQUESTED_MODEL" == *[[:space:]]* ]]; then
  TRANSLATION_REQUESTED_MODEL=""
fi

if [[ "$TRANSLATION_REQUESTED_MODEL" == ollama/* ]]; then
  OPENCLAW_AI_PROVIDER="ollama"
  MODEL="$TRANSLATION_REQUESTED_MODEL"
elif [[ "$TRANSLATION_PROVIDER" == "ollama" ]]; then
  OPENCLAW_AI_PROVIDER="ollama"
  MODEL="${OLLAMA_MODEL:-${TRANSLATION_REQUESTED_MODEL:-$TRANSLATION_DEFAULT_OLLAMA_MODEL}}"
elif [[ "$TRANSLATION_PROVIDER" == "ninerouter" && -n "$TRANSLATION_REQUESTED_MODEL" ]]; then
  # 9Router is opt-in: both its provider and a real model identifier are needed.
  OPENCLAW_AI_PROVIDER="ninerouter"
  MODEL="$TRANSLATION_REQUESTED_MODEL"
else
  # Ignore inherited providers (for example, OpenClaw's global "openai").
  OPENCLAW_AI_PROVIDER="ollama"
  MODEL="${OLLAMA_MODEL:-$TRANSLATION_DEFAULT_OLLAMA_MODEL}"
fi

if [[ "$OPENCLAW_AI_PROVIDER" == "ollama" ]]; then
  # Ollama's /api/chat expects its installed model name, not OpenClaw's
  # provider-qualified display identifier (for example, minimax-m3:cloud).
  MODEL="${MODEL#ollama/}"
  API_BASE="${OLLAMA_API_BASE:-http://127.0.0.1:11434}"
else
  if [[ -z "${NINEROUTER_API_BASE:-}" ]]; then
    if [[ -f /.dockerenv ]]; then
      API_BASE="http://172.19.0.1:20128/v1"
    else
      API_BASE="http://127.0.0.1:20128/v1"
    fi
  else
    API_BASE="$NINEROUTER_API_BASE"
  fi
fi

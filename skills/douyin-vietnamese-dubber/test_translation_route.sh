#!/usr/bin/env bash
set -Eeuo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

assert_route() {
  local name="$1" provider="$2" ninerouter_model="$3" ollama_model="$4" expected_provider="$5" expected_model="$6"
  local actual_provider actual_model
  actual_provider="$(OPENCLAW_AI_PROVIDER="$provider" NINEROUTER_MODEL="$ninerouter_model" OLLAMA_MODEL="$ollama_model" \
    bash -c 'source "$1/translation_route.sh"; printf "%s|%s" "$OPENCLAW_AI_PROVIDER" "$MODEL"' _ "$SKILL_DIR")"
  IFS='|' read -r provider actual_model <<<"$actual_provider"
  if [[ "$provider" != "$expected_provider" || "$actual_model" != "$expected_model" ]]; then
    printf 'FAIL: %s: got provider=%q model=%q; expected provider=%q model=%q\n' \
      "$name" "$provider" "$actual_model" "$expected_provider" "$expected_model" >&2
    return 1
  fi
  printf 'OK: %s\n' "$name"
}

assert_route "provider-prefixed Ollama model is normalized" "openai" "ollama/minimax-m3:cloud" "" "ollama" "minimax-m3:cloud"
assert_route "plain Ollama model is unchanged" "ollama" "minimax-m3:cloud" "" "ollama" "minimax-m3:cloud"
assert_route "legacy API display label falls back to Ollama" "openai" "API deepseek" "" "ollama" "minimax-m3:cloud"
assert_route "explicit ninerouter remains available" "ninerouter" "deepseek-chat" "" "ninerouter" "deepseek-chat"
assert_route "configured Ollama model selects Ollama" "ninerouter" "ollama/glm-5.2:cloud" "" "ollama" "glm-5.2:cloud"

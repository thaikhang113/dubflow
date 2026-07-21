#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$ROOT/run_scheduled_report.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

run_case() {
  local already_sent="$1"
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  local runner="$tmp/runner"
  local openclaw="$tmp/openclaw"
  local log="$tmp/log"
  cat > "$runner" <<'RUNNER'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'runner:%s\n' "$*" >> "$TEST_LOG"
case "$1" in
  trend-report-prepare)
    printf '{"ok":true,"returncode":0,"stdout":"{\\"ok\\":true,\\"ledger\\":{\\"kind\\":\\"digest\\",\\"dedupe_key\\":\\"%s\\",\\"status\\":\\"prepared\\"},\\"package\\":{},\\"telegram_text\\":\\"Scout report\\",\\"already_sent\\":%s}\\n","stderr":""}\n' "$3" "$ALREADY_SENT"
    ;;
  trend-report-ack)
    printf '{"ok":true,"returncode":0,"stdout":"{\\"ok\\":true,\\"status\\":\\"sent\\"}\\n","stderr":""}\n'
    ;;
  *) exit 9 ;;
esac
RUNNER
  cat > "$openclaw" <<'OPENCLAW'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'openclaw:%s\n' "$*" >> "$TEST_LOG"
printf '{"ok":true}\n'
OPENCLAW
  chmod +x "$runner" "$openclaw"

  TEST_LOG="$log" ALREADY_SENT="$already_sent" \
    TREND_SCOUT_HOST_RUNNER="$runner" OPENCLAW_BIN="$openclaw" \
    bash "$SCRIPT"

  if [[ "$already_sent" == "true" ]]; then
    ! grep -q '^openclaw:' "$log" || fail "already-sent report must not send again"
    ! grep -q '^runner:trend-report-ack' "$log" || fail "already-sent report must not ack again"
  else
    grep -q '^openclaw:message send --channel telegram --account boss -t -1003906053440 --thread-id 1097 -m Scout report --json$' "$log" || fail "message send missing"
    grep -q '^runner:trend-report-ack digest digest-' "$log" || fail "success ack missing"
  fi
}

run_case false
run_case true
echo "SCHEDULED_REPORT_CONTRACT_OK"

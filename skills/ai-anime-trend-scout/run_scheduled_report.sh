#!/usr/bin/env bash
# Fixed 4-hour Trend Scout delivery: prepare -> Telegram -> ack.
# It accepts no user input and never reads a Telegram token.
set -Eeuo pipefail

HOST_RUNNER="${TREND_SCOUT_HOST_RUNNER:-/home/node/host-bin/openclaw-call-host-runner.sh}"
OPENCLAW_BIN="${OPENCLAW_BIN:-openclaw}"
TELEGRAM_TARGET="-1003906053440"
TELEGRAM_ACCOUNT="${TREND_SCOUT_TELEGRAM_ACCOUNT:-boss}"
TELEGRAM_THREAD_ID="${TREND_SCOUT_TELEGRAM_THREAD_ID:-1097}"
DEDUPLICATION_KEY="$(TZ=Asia/Ho_Chi_Minh date '+digest-%Y%m%d-%H')"

fail() {
  echo "TREND_REPORT_FAILED: $*" >&2
  exit 1
}

[[ "$TELEGRAM_THREAD_ID" =~ ^[1-9][0-9]*$ ]] || fail "invalid_telegram_thread"

parse_prepare() {
  node -e '
const fs = require("fs");
let envelope;
try { envelope = JSON.parse(fs.readFileSync(0, "utf8")); } catch { process.exit(2); }
if (envelope.ok !== true || envelope.returncode !== 0 || typeof envelope.stdout !== "string") process.exit(3);
let result;
try { result = JSON.parse(envelope.stdout); } catch { process.exit(4); }
if (result.ok !== true || !result.ledger || !result.package || typeof result.telegram_text !== "string") process.exit(5);
const kind = result.ledger.kind;
const dedupe = result.ledger.dedupe_key;
if (!["alert", "digest", "health"].includes(kind) || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(dedupe)) process.exit(6);
process.stdout.write(JSON.stringify({kind, dedupe, already_sent: result.already_sent === true, text: result.telegram_text}));
'
}

prepared_envelope="$($HOST_RUNNER trend-report-prepare digest "$DEDUPLICATION_KEY")" || fail "prepare"
prepared="$(printf '%s' "$prepared_envelope" | parse_prepare)" || fail "invalid_prepare_payload"

already_sent="$(printf '%s' "$prepared" | node -e 'const fs=require("fs"); console.log(JSON.parse(fs.readFileSync(0,"utf8")).already_sent ? "true" : "false")')"
if [[ "$already_sent" == "true" ]]; then
  echo "TREND_REPORT_ALREADY_SENT"
  exit 0
fi

report_kind="$(printf '%s' "$prepared" | node -e 'const fs=require("fs"); process.stdout.write(JSON.parse(fs.readFileSync(0,"utf8")).kind)')"
ledger_dedupe="$(printf '%s' "$prepared" | node -e 'const fs=require("fs"); process.stdout.write(JSON.parse(fs.readFileSync(0,"utf8")).dedupe)')"
telegram_text="$(printf '%s' "$prepared" | node -e 'const fs=require("fs"); process.stdout.write(JSON.parse(fs.readFileSync(0,"utf8")).text)')"
[[ -n "$telegram_text" ]] || fail "empty_telegram_text"

"$OPENCLAW_BIN" message send --channel telegram --account "$TELEGRAM_ACCOUNT" -t "$TELEGRAM_TARGET" --thread-id "$TELEGRAM_THREAD_ID" -m "$telegram_text" --json >/dev/null || fail "telegram_send"
ack_envelope="$($HOST_RUNNER trend-report-ack "$report_kind" "$ledger_dedupe" 1)" || fail "ack"

printf '%s' "$ack_envelope" | node -e '
const fs = require("fs");
const envelope = JSON.parse(fs.readFileSync(0, "utf8"));
if (envelope.ok !== true || envelope.returncode !== 0 || typeof envelope.stdout !== "string") process.exit(2);
const result = JSON.parse(envelope.stdout);
if (result.ok !== true || result.status !== "sent") process.exit(3);
' || fail "invalid_ack_payload"

echo "TREND_REPORT_SENT"

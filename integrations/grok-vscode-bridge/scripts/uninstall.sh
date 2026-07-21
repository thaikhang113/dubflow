#!/usr/bin/env bash
# Uninstall the Grok VS Code extension on macOS / Linux / WSL.
# Usage:  ./scripts/uninstall.sh [cli]
#   [cli] — a code-compatible CLI name or path to uninstall from (e.g. code-insiders,
#           cursor, antigravity-ide, /path/to/code); also settable via CODE_CLI=…
#           Default: auto-detect code → code-insiders → cursor → antigravity-ide → antigravity.

set -euo pipefail

known_clis="code code-insiders cursor antigravity-ide antigravity"
cli_override="${1:-${CODE_CLI:-}}"

find_code_cli() {
    if [ -n "$cli_override" ]; then
        if command -v "$cli_override" >/dev/null 2>&1; then
            echo "$cli_override"; return 0
        fi
        echo "Requested CLI not found: $cli_override" >&2
        return 1
    fi
    for name in $known_clis; do
        if command -v "$name" >/dev/null 2>&1; then
            echo "$name"; return 0
        fi
    done
    for path in \
        "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" \
        "/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin/code-insiders" \
        "/Applications/Cursor.app/Contents/Resources/app/bin/cursor" \
        "/Applications/Antigravity IDE.app/Contents/Resources/app/bin/antigravity-ide" \
    ; do
        [ -x "$path" ] && { echo "$path"; return 0; }
    done
    echo "Could not find a code-compatible CLI. Pass one: ./scripts/uninstall.sh <cli-name-or-path>" >&2
    return 1
}

code=$(find_code_cli)
echo "Uninstalling PawelHuryn.grok-vscode-phuryn via $code"
"$code" --uninstall-extension PawelHuryn.grok-vscode-phuryn
echo
echo "Done. Reload the IDE window to drop the sidebar."

#!/usr/bin/env bash
# One-command release for grok-build-vscode — the macOS/Linux/WSL twin of
# scripts/release.ps1. Encodes the standing "release push to main" procedure
# from CLAUDE.md so it isn't orchestrated by hand each time.
#
# Bump package.json + write the changelog section FIRST (those stay
# user-initiated), then run:
#   ./scripts/release.sh                 # full release (incl. real-grok test:live)
#   ./scripts/release.sh --no-test       # skip ALL gating (tsc + npm test + test:live)
#   ./scripts/release.sh --skip-live     # keep tsc + npm test, skip only real-grok test:live
#   ./scripts/release.sh --dry-run       # print what it would do
#   ./scripts/release.sh -F .git/MSG     # commit with a message file
#
# Steps: assert main -> tsc+test -> assert tag free -> npm run package ->
#        commit -> push main -> annotated tag -> push tag ->
#        gh release create (changelog section as notes, .vsix attached).
# Marketplace publish (vsce) is deliberately separate: npm run publish.
set -euo pipefail

cd "$(dirname "$0")/.."

NO_TEST=0; SKIP_LIVE=0; DRY_RUN=0; MSG=""; MSG_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-test) NO_TEST=1 ;;
    --skip-live) SKIP_LIVE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -m|--message) MSG="$2"; shift ;;
    -F|--message-file) MSG_FILE="$2"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }

version="$(node -p "require('./package.json').version")"
tag="v$version"
vsix="grok-vscode-phuryn-$version.vsix"
[ -n "$MSG" ] || MSG="Release $tag"
printf '\033[32mReleasing %s\033[0m\n' "$tag"

branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = "main" ] || { echo "Not on main (on '$branch'). Releases are direct-to-main." >&2; exit 1; }

if [ "$NO_TEST" -eq 0 ]; then
  step "tsc --noEmit"; npx tsc -p . --noEmit
  step "npm test";     npm test
  # The real-grok suite is a mandatory part of the release gate (CLAUDE.md § Publishing).
  # It spawns the actual CLI, so it only runs where grok is logged in — hence --skip-live,
  # but the DEFAULT runs it so it can't be silently forgotten under release pressure. A live
  # FAIL aborts (set -e); an in-suite SKIP (no subscription / grok declined) is exit 0.
  if [ "$SKIP_LIVE" -eq 0 ]; then
    step "npm run test:live (real grok)"; npm run test:live
  else
    step "SKIPPING real-grok tests (--skip-live) - gate is WEAKER; run 'npm run test:live' by hand first"
  fi
fi

if git tag --list "$tag" | grep -q .; then
  echo "Tag $tag already exists - bump package.json/changelog first." >&2; exit 1
fi

step "npm run package"; npm run package
[ -f "$vsix" ] || { echo "Expected $vsix but it wasn't produced." >&2; exit 1; }

# Extract this version's changelog section for the release notes.
notes_file="$(mktemp -t grok-release-notes.XXXXXX)"
awk -v ver="$version" '
  /^## / { if (started) exit; if (index($0, "## " ver) == 1) started=1 }
  started { print }
' CHANGELOG.md > "$notes_file"
[ -s "$notes_file" ] || { echo "No '## $version' section in CHANGELOG.md." >&2; exit 1; }

if [ "$DRY_RUN" -eq 1 ]; then
  printf '\033[33m[dry-run] would commit, tag %s, push main + tag, then:\033[0m\n' "$tag"
  echo "  gh release create $tag --title \"Release $tag\" --notes-file <notes> $vsix"
  echo "--- release notes ---"; cat "$notes_file"
  exit 0
fi

# backlog.md is excluded via .git/info/exclude, so -A won't sweep it.
if [ -n "$(git status --porcelain)" ]; then
  step "git commit"; git add -A
  if [ -n "$MSG_FILE" ]; then git commit -F "$MSG_FILE"; else git commit -m "$MSG"; fi
else
  step "working tree clean - nothing to commit"
fi

step "git push origin main"; git push origin main
step "git tag $tag";         git tag -a "$tag" -m "Release $tag"
step "git push origin $tag"; git push origin "$tag"
step "gh release create $tag (vsix attached)"
gh release create "$tag" --title "Release $tag" --notes-file "$notes_file" "$vsix"

printf '\033[32mReleased %s with %s attached.\033[0m\n' "$tag" "$vsix"
echo "Marketplace publish is separate: npm run publish"

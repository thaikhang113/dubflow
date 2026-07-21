<#
.SYNOPSIS
  One-command release for grok-build-vscode — encodes the standing
  "release push to main" procedure from CLAUDE.md so it doesn't have to be
  orchestrated by hand each time.

.DESCRIPTION
  Reads the version from package.json (bump it + write the changelog section
  FIRST — those stay user-initiated), then runs the gate and ships:

    1. assert on `main`
    2. tsc --noEmit + npm test       (skip all gating with -NoTest)
       + npm run test:live           (real grok — mandatory gate; skip with -SkipLive)
    3. assert tag vX.Y.Z is free     (bump the version if it isn't)
    4. npm run package               -> grok-vscode-phuryn-X.Y.Z.vsix
    5. commit the working tree        (message from -MessageFile / -Message / default)
    6. push main
    7. annotated tag vX.Y.Z + push
    8. gh release create vX.Y.Z       with the changelog section as notes
                                       AND the .vsix attached as a release asset

  Marketplace publish (vsce) is deliberately NOT here — that's a separate,
  explicit step (`npm run publish`).

.EXAMPLE
  pwsh scripts\release.ps1
.EXAMPLE
  powershell -File scripts\release.ps1 -MessageFile .git\RELEASE_MSG
.EXAMPLE
  pwsh scripts\release.ps1 -DryRun
#>
[CmdletBinding()]
param(
  [string]$Message,
  [string]$MessageFile,
  [switch]$NoTest,
  [switch]$SkipLive,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($t) { Write-Host "==> $t" -ForegroundColor Cyan }
function Run($label, [scriptblock]$cmd) {
  Step $label
  # The success signal for an external tool is its EXIT CODE, not whether it wrote
  # to stderr. Under the script-level $ErrorActionPreference="Stop", PowerShell 5.1
  # turns ANY native-command stderr into a terminating error — so a clean exit-0
  # `npm test` aborted the gate just for printing Vite's CJS deprecation warning.
  # Make stderr non-fatal for the command (function-local; reverts on return) and
  # judge it solely on $LASTEXITCODE.
  $ErrorActionPreference = "Continue"
  & $cmd
  if ($LASTEXITCODE) { throw "$label failed (exit $LASTEXITCODE)" }
}

$pkg     = Get-Content package.json -Raw -Encoding UTF8 | ConvertFrom-Json
$version = $pkg.version
$tag     = "v$version"
if (-not $Message) { $Message = "Release $tag" }
Write-Host "Releasing $tag" -ForegroundColor Green

# 1. branch
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "main") { throw "Not on main (on '$branch'). Releases are direct-to-main." }

# 2. gate
if (-not $NoTest) {
  Run "tsc --noEmit"  { npx tsc -p . --noEmit }
  Run "npm test"      { npm test }
  # The real-grok suite is a mandatory part of the release gate (CLAUDE.md § Publishing).
  # It spawns the actual CLI, so it can only run where grok is logged in — hence the
  # explicit -SkipLive escape hatch, but the DEFAULT is to run it so it can't be
  # silently forgotten under release pressure. A live FAIL (non-zero exit) aborts the
  # release; a SKIP inside the suite (no subscription, grok declined to delegate) is exit 0.
  if (-not $SkipLive) {
    Run "npm run test:live (real grok)" { npm run test:live }
  } else {
    Step "SKIPPING real-grok tests (-SkipLive) - the release gate is WEAKER; run 'npm run test:live' by hand first"
  }
}

# 3. tag must be free (a collision means the version wasn't bumped)
if (git tag --list $tag) { throw "Tag $tag already exists - bump package.json/changelog first." }

# 4. build the vsix that will be attached to the release
$vsix = "grok-vscode-phuryn-$version.vsix"
Run "npm run package" { npm run package }
if (-not (Test-Path $vsix)) { throw "Expected $vsix but it wasn't produced." }

# 5. extract this version's changelog section for the release notes
$lines = Get-Content CHANGELOG.md -Encoding UTF8
$start = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -match ('^##\s+' + [regex]::Escape($version) + '(\D|$)')) { $start = $i; break }
}
if ($start -lt 0) { throw "No '## $version' section in CHANGELOG.md." }
$end = $lines.Count
for ($i = $start + 1; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -match '^##\s+\d') { $end = $i; break }
}
$notes     = ($lines[$start..($end - 1)] -join "`n").TrimEnd()
$notesFile = Join-Path ([System.IO.Path]::GetTempPath()) "grok-release-notes-$version.md"
[System.IO.File]::WriteAllText($notesFile, $notes, (New-Object System.Text.UTF8Encoding($false)))

if ($DryRun) {
  Write-Host "`n[dry-run] would commit, tag $tag, push main + tag, and run:" -ForegroundColor Yellow
  Write-Host "  gh release create $tag --title `"Release $tag`" --notes-file <notes> $vsix"
  Write-Host "`n--- release notes ---`n$notes"
  return
}

# 6. commit whatever is staged/dirty (backlog.md is excluded via .git/info/exclude)
if (git status --porcelain) {
  Run "git add -A" { git add -A }
  if ($MessageFile) { Run "git commit" { git commit -F $MessageFile } }
  else              { Run "git commit" { git commit -m $Message } }
} else {
  Step "working tree clean - nothing to commit"
}

# 7. push, tag, push tag
Run "git push origin main" { git push origin main }
Run "git tag -a $tag"      { git tag -a $tag -m "Release $tag" }
Run "git push origin $tag" { git push origin $tag }

# 8. GitHub Release with the vsix attached (always attach - update procedure)
Run "gh release create $tag" { gh release create $tag --title "Release $tag" --notes-file $notesFile $vsix }

Write-Host "`nReleased $tag with $vsix attached." -ForegroundColor Green
Write-Host "Marketplace publish is separate: npm run publish" -ForegroundColor DarkGray

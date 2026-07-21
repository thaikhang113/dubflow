# Install the Grok VS Code extension on Windows.
# Usage:  pwsh scripts\install.ps1 [-VsixPath path\to.vsix] [-Cli name-or-path] [-All]
#   -Cli - a code-compatible CLI to install into (e.g. code-insiders, cursor,
#          antigravity, C:\path\to\code.cmd); also settable via $env:CODE_CLI.
#          Default: auto-detect code -> code-insiders -> cursor -> antigravity-ide -> antigravity.
#   -All - install into EVERY detected known CLI in one run (build once, install N times).
# Always builds a FRESH .vsix from the current source (npm run package clears the
# stale one first) unless an explicit -VsixPath is given - so an install never
# silently ships a leftover build. Uses --force so a same-version reinstall overwrites.

param(
    [string]$VsixPath,
    [string]$Cli,
    [switch]$All
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$knownClis = @("code", "code-insiders", "cursor", "antigravity-ide", "antigravity")
if (-not $Cli -and $env:CODE_CLI) { $Cli = $env:CODE_CLI }
if ($All -and $Cli) { throw "-All and -Cli are mutually exclusive." }

function Find-KnownClis {
    $found = @()
    foreach ($name in $knownClis) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $found += $cmd.Source }
    }
    return $found
}

function Find-CodeCli {
    if ($Cli) {
        $cmd = Get-Command $Cli -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
        if (Test-Path $Cli) { return $Cli }
        throw "Requested CLI not found: $Cli"
    }
    foreach ($name in $knownClis) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    foreach ($fallback in @(
        "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd",
        "$env:LOCALAPPDATA\Programs\Microsoft VS Code Insiders\bin\code-insiders.cmd",
        "$env:LOCALAPPDATA\Programs\cursor\resources\app\bin\cursor.cmd"
    )) {
        if (Test-Path $fallback) { return $fallback }
    }
    throw "Could not find a code-compatible CLI. Install VS Code, or pass one: pwsh scripts\install.ps1 -Cli <name-or-path>"
}

if (-not $VsixPath) {
    Write-Host "Building a fresh .vsix from current source..."
    Push-Location $repoRoot
    try {
        if (-not (Test-Path "node_modules")) { npm install }
        npm run package   # clears stale grok-vscode-phuryn-*.vsix first, then builds
        $vsix = Get-ChildItem -Path $repoRoot -Filter "*.vsix" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    } finally { Pop-Location }
    if (-not $vsix) { throw "Build did not produce a .vsix." }
    $VsixPath = $vsix.FullName
}

if ($All) {
    $targets = Find-KnownClis
    if (-not $targets) { throw "No known code-compatible CLI detected ($($knownClis -join ', '))." }
} else {
    $targets = @(Find-CodeCli)
}

foreach ($code in $targets) {
    Write-Host "Installing $VsixPath via $code"
    & $code --install-extension $VsixPath --force
}
Write-Host ""
Write-Host "Done. Reload the IDE window (Ctrl+Shift+P -> 'Developer: Reload Window') and click the Grok icon."

if (-not $Cli -and -not $All) {
    $chosen = [System.IO.Path]::GetFileNameWithoutExtension($targets[0])
    $others = $knownClis | Where-Object { $_ -ne $chosen -and (Get-Command $_ -ErrorAction SilentlyContinue) }
    if ($others) {
        Write-Host "Also detected: $($others -join ', ') - to install there instead: pwsh scripts\install.ps1 -Cli <name> (or -All for every detected IDE)"
    }
}

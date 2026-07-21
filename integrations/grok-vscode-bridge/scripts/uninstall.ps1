# Uninstall the Grok VS Code extension on Windows.
# Usage:  pwsh scripts\uninstall.ps1 [-Cli name-or-path]
#   -Cli - a code-compatible CLI to uninstall from (e.g. code-insiders, cursor,
#          antigravity, C:\path\to\code.cmd); also settable via $env:CODE_CLI.
#          Default: auto-detect code -> code-insiders -> cursor -> antigravity-ide -> antigravity.

param(
    [string]$Cli
)

$ErrorActionPreference = "Stop"
$knownClis = @("code", "code-insiders", "cursor", "antigravity-ide", "antigravity")
if (-not $Cli -and $env:CODE_CLI) { $Cli = $env:CODE_CLI }

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
    $fallback = "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd"
    if (Test-Path $fallback) { return $fallback }
    $fallback = "$env:LOCALAPPDATA\Programs\Microsoft VS Code Insiders\bin\code-insiders.cmd"
    if (Test-Path $fallback) { return $fallback }
    $fallback = "$env:LOCALAPPDATA\Programs\cursor\resources\app\bin\cursor.cmd"
    if (Test-Path $fallback) { return $fallback }
    throw "Could not find a code-compatible CLI. Pass one: pwsh scripts\uninstall.ps1 -Cli <name-or-path>"
}

$code = Find-CodeCli
Write-Host "Uninstalling PawelHuryn.grok-vscode-phuryn via $code"
& $code --uninstall-extension PawelHuryn.grok-vscode-phuryn
Write-Host ""
Write-Host "Done. Reload the IDE window to drop the sidebar."

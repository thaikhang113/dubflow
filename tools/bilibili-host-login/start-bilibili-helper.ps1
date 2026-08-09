$ErrorActionPreference = "Stop"
$python = Get-Command python -ErrorAction Stop
& $python.Source (Join-Path $PSScriptRoot "helper.py")

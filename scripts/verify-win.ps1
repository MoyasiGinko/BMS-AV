# Windows wrapper for the quality gate (see ADR 0002). Runs scripts/verify.sh unchanged via Git Bash with .venv first on PATH.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:PATH = (Join-Path $root ".venv\Scripts") + ";" + $env:PATH
$env:PYTHONUTF8 = "1"
$bash = "C:\Program Files\Git\bin\bash.exe"
& $bash (Join-Path $root "scripts/verify.sh")
exit $LASTEXITCODE

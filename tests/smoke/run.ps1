# Build the smoke image and run the harness. Prints PASS/FAIL and exits
# with the harness's exit code so CI (or a human) can gate on it.
#
# Usage (from repo root):
#   pwsh tests/smoke/run.ps1
#
# Docker CLI isn't on PATH in some Windows installs; fall back to the
# default Docker Desktop install path before giving up.

[CmdletBinding()]
param(
    [string]$ImageTag = "engram-mcp-smoke:latest"
)

$ErrorActionPreference = "Stop"

$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $docker) {
    $fallback = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path $fallback) {
        Set-Alias -Name docker -Value $fallback -Scope Script
    } else {
        Write-Error "docker not on PATH and not found at $fallback"
        exit 127
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $repoRoot
try {
    Write-Host "==> docker build -f tests/smoke/Dockerfile -t $ImageTag ."
    docker build -f tests/smoke/Dockerfile -t $ImageTag .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host ""
    Write-Host "==> docker run --rm $ImageTag"
    docker run --rm $ImageTag
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

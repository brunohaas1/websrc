<#
  update.ps1 — pull, rebuild and restart app services via Docker Compose (Windows).
  Usage: .\scripts\update.ps1 [-SkipPull] [-NoBuild]
#>
Param(
    [switch]$SkipPull,
    [switch]$NoBuild
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$appServices = @("api", "worker", "scheduler")

# 1. Pull latest code
if (-not $SkipPull) {
    Write-Output "==> Pulling latest code from git..."
    git pull
    if ($LASTEXITCODE -ne 0) { Write-Output "git pull failed."; exit 1 }
}

# 2. Build images for app services
if (-not $NoBuild) {
    Write-Output "==> Building Docker images for: $($appServices -join ', ')"
    docker compose build @$appServices
    if ($LASTEXITCODE -ne 0) { Write-Output "docker compose build failed."; exit 1 }
}

# 3. Restart only app services (postgres, redis, caddy stay up)
Write-Output "==> Restarting app services..."
docker compose up -d --no-deps @$appServices
if ($LASTEXITCODE -ne 0) { Write-Output "docker compose up failed."; exit 1 }

# 4. Show status
Write-Output ""
Write-Output "==> Current service status:"
docker compose ps

Write-Output ""
Write-Output "Update complete."

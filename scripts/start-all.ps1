$ErrorActionPreference = 'Stop'

Set-Location (Split-Path -Parent $PSScriptRoot)

function Test-DockerDaemon {
  docker version *> $null
  if ($LASTEXITCODE -eq 0) {
    return $true
  }
  return $false
}

Write-Host "[1/3] Verificando Docker daemon..."
if (Test-DockerDaemon) {
  Write-Host "[2/3] Subindo stack avançado via Docker Compose..."
  if (!(Test-Path .env.advanced)) {
    Copy-Item .env.advanced.example .env.advanced
  }
  docker compose -f docker-compose.advanced.yml up -d --build
  if ($LASTEXITCODE -eq 0) {
    Write-Host "[3/3] Stack iniciado. Acesse http://localhost"
    exit 0
  }

  Write-Host "Compose falhou. Executando fallback local..."
}

Write-Host "Docker daemon indisponível. Iniciando fallback local (modo all)."
$pythonExe = ".\.venv\Scripts\python.exe"
if (!(Test-Path $pythonExe)) {
  throw "Python virtualenv não encontrado em .venv"
}

$env:APP_ROLE = "all"
$env:QUEUE_ENABLED = "0"
Start-Process -FilePath $pythonExe -ArgumentList "run.py" -WorkingDirectory "." | Out-Null
Write-Host "Fallback local iniciado. Acesse http://127.0.0.1:8000"

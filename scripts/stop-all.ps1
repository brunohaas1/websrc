$ErrorActionPreference = 'SilentlyContinue'

Set-Location (Split-Path -Parent $PSScriptRoot)

# Para stack docker (se existir)
docker compose -f docker-compose.advanced.yml down

# Para fallback local
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'run.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Write-Host "Serviços encerrados."

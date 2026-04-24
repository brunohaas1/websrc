<#
  Update script for Windows (PowerShell).
  - Pull latest from git
  - Activate virtualenv and install requirements
  - Run tests (pytest)
  - Restart the app (background) if tests pass
#>

Write-Output "Starting update..."

# Go to repository root (assumes script run from repo root)

# Stop existing process if running
$pidFile = "run.pid"
if (Test-Path $pidFile) {
    try {
        $pid = Get-Content $pidFile | Out-String | Trim
        if ($pid -and (Get-Process -Id $pid -ErrorAction SilentlyContinue)) {
            Write-Output "Stopping process $pid..."
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Output "Warning stopping process: $_"
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

# Git pull
Write-Output "Pulling latest code from git..."
git pull

# Activate venv
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
} else {
    Write-Output "Virtualenv not found at .venv. Create one with: python -m venv .venv";
}

# Install requirements
if (Test-Path "requirements.txt") {
    Write-Output "Installing requirements..."
    & .venv\Scripts\python.exe -m pip install -r requirements.txt
}

# Run tests
Write-Output "Running tests..."
$res = & .venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Output "Tests failed. Aborting restart."
    Write-Output $res
    exit $LASTEXITCODE
}

# Start app in background
Write-Output "Starting app in background..."
& powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\serve.ps1 -background

Write-Output "Update complete."

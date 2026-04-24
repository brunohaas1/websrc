Param(
    [switch]$background
)

# Activate virtualenv
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}

$pidFile = "run.pid"
$python = Join-Path ".venv\Scripts" "python.exe"

if ($background) {
    if (Test-Path $pidFile) {
        Write-Output "PID file exists at $pidFile. Stop existing process first or remove the file."
        exit 1
    }
    $proc = Start-Process -FilePath $python -ArgumentList "run.py" -WindowStyle Hidden -PassThru
    $proc.Id | Out-File $pidFile
    Write-Output "Started app in background (PID $($proc.Id)). PID written to $pidFile"
} else {
    & $python run.py
}

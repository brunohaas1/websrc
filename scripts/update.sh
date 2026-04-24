#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Pulling latest code..."
git pull

if [ -f ".venv/bin/activate" ]; then
  . .venv/bin/activate
fi

if [ -f requirements.txt ]; then
  pip install -r requirements.txt || true
fi

echo "Running tests..."
pytest -q

PID_FILE="run.pid"
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "Stopping process $PID"
    kill -TERM "$PID"
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

echo "Starting app in background..."
nohup .venv/bin/python run.py >/dev/null 2>&1 &
echo $! > "$PID_FILE"
echo "Started with PID $(cat $PID_FILE)"

#!/usr/bin/env bash
# update.sh — pull, rebuild and restart app services on Docker Compose
# Usage: ./scripts/update.sh [--no-build] [--skip-pull]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_PULL=0
SKIP_BUILD=0
for arg in "$@"; do
  case $arg in
    --skip-pull)  SKIP_PULL=1 ;;
    --no-build)   SKIP_BUILD=1 ;;
    *) echo "Unknown flag: $arg"; exit 1 ;;
  esac
done

# App-level services (rebuilt from source)
APP_SERVICES="api worker scheduler"

# 1. Pull latest code
if [ "$SKIP_PULL" -eq 0 ]; then
  echo "==> Pulling latest code from git..."
  git pull
fi

# 2. Build images for app services
if [ "$SKIP_BUILD" -eq 0 ]; then
  echo "==> Building Docker images for: $APP_SERVICES"
  docker compose build $APP_SERVICES
fi

# 3. Restart only app services (postgres, redis, caddy stay up)
echo "==> Restarting app services..."
docker compose up -d --no-deps $APP_SERVICES

# 4. Show running containers
echo ""
echo "==> Current service status:"
docker compose ps

echo ""
echo "Update complete."

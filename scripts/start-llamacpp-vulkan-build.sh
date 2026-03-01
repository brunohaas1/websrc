#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env.advanced ]]; then
  cp .env.llamacpp.example .env.advanced
  echo "[ok] .env.advanced criado a partir de .env.llamacpp.example"
fi

echo "[1/2] Buildando imagem local do llama.cpp com Vulkan..."
docker compose \
  -f docker-compose.advanced.yml \
  -f docker-compose.llamacpp.yml \
  -f docker-compose.llamacpp.vulkan-build.yml \
  build llamacpp

echo "[2/2] Subindo stack com imagem Vulkan local..."
docker compose \
  -f docker-compose.advanced.yml \
  -f docker-compose.llamacpp.yml \
  -f docker-compose.llamacpp.vulkan-build.yml \
  up -d --build api worker scheduler redis postgres caddy llamacpp

docker compose -f docker-compose.advanced.yml stop ollama >/dev/null 2>&1 || true

echo "[ok] Stack iniciado. Verifique backend:" 
docker logs ws-llamacpp 2>&1 | egrep -i "load_backend|vulkan|offload|gpu" | tail -n 40 || true
echo "[info] Nós DRM no host:"
ls -l /dev/dri 2>/dev/null || true
echo "[info] Nós DRM dentro do container:"
docker exec ws-llamacpp ls -l /dev/dri 2>/dev/null || true
echo "[info] Vulkan runtime dentro do container:"
docker exec ws-llamacpp vulkaninfo --summary 2>/dev/null | head -n 40 || true
echo "[info] Dispositivos listados pelo llama-server:"
docker exec ws-llamacpp /app/llama-server --list-devices || true

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODEL_FILE="models/llama-3.2-3b-instruct-q4_k_m.gguf"

if [[ ! -f "$MODEL_FILE" ]]; then
  echo "[erro] Modelo GGUF não encontrado: $MODEL_FILE"
  echo "Coloque o arquivo em ./models/ antes de subir o stack."
  exit 1
fi

if [[ ! -f .env.advanced ]]; then
  cp .env.llamacpp.example .env.advanced
  echo "[ok] .env.advanced criado a partir de .env.llamacpp.example"
fi

LLAMACPP_HOST_PORT="$(grep -E '^LLAMACPP_HOST_PORT=' .env.advanced 2>/dev/null | tail -n1 | cut -d'=' -f2- | tr -d '"' | tr -d '\r' | xargs || true)"
LLAMACPP_HOST_PORT="${LLAMACPP_HOST_PORT:-8081}"

check_url() {
  local url="$1"
  local label="$2"
  local attempts="${3:-20}"
  local sleep_seconds="${4:-2}"

  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "$url" >/dev/null; then
      echo "[ok] ${label}: ${url}"
      return 0
    fi
    echo "[aguardando] ${label} (${i}/${attempts})..."
    sleep "$sleep_seconds"
  done

  echo "[warn] ${label} indisponível após ${attempts} tentativas: ${url}"
  return 1
}

echo "[1/3] Subindo stack com backend llama.cpp..."
docker compose \
  -f docker-compose.advanced.yml \
  -f docker-compose.llamacpp.yml \
  up -d --build api worker scheduler redis postgres caddy llamacpp

# Em modo llama.cpp, ollama não é necessário (economia de RAM/CPU)
docker compose -f docker-compose.advanced.yml stop ollama >/dev/null 2>&1 || true

echo "[2/3] Status dos serviços:"
docker compose ps

echo "[3/3] Health checks:"

check_url "http://127.0.0.1:${LLAMACPP_HOST_PORT}/health" "llama.cpp" || true
check_url "http://127.0.0.1/health" "api via caddy (80)" || true
check_url "http://127.0.0.1:8000/api/ai-observability" "ai-observability via caddy (8000)" || true

curl -fsS "http://127.0.0.1:${LLAMACPP_HOST_PORT}/health" && echo
curl -fsS http://127.0.0.1/health && echo
curl -fsS http://127.0.0.1:8000/api/ai-observability && echo

echo "[info] Diagnóstico de backend llama.cpp (últimas linhas relevantes):"
docker logs ws-llamacpp 2>&1 | egrep -i "load_backend|vulkan|offload|gpu" | tail -n 20 || true

echo "[ok] Stack pronto para uso com llama.cpp"

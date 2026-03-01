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

echo "[1/3] Subindo stack com backend llama.cpp..."
docker compose \
  -f docker-compose.advanced.yml \
  -f docker-compose.llamacpp.yml \
  up -d --build api worker scheduler redis postgres caddy llamacpp

echo "[2/3] Status dos serviços:"
docker compose ps

echo "[3/3] Health checks:"
curl -fsS http://127.0.0.1/health && echo
curl -fsS http://127.0.0.1:8000/api/ai-observability && echo

echo "[ok] Stack pronto para uso com llama.cpp"

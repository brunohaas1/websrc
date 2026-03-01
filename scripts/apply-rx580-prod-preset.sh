#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE=".env.advanced"

if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.llamacpp.example "$ENV_FILE"
  echo "[ok] $ENV_FILE criado a partir de .env.llamacpp.example"
fi

detect_first_render() {
  find /dev/dri -maxdepth 1 -type c -name 'renderD*' 2>/dev/null | sort | head -n1 || true
}

detect_first_card() {
  find /dev/dri -maxdepth 1 -type c -name 'card*' 2>/dev/null | sort | head -n1 || true
}

upsert_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

DRI_RENDER="$(detect_first_render)"
DRI_CARD="$(detect_first_card)"

upsert_env "AI_LOCAL_BACKEND" "llama_cpp"
upsert_env "AI_LOCAL_URL" "http://llamacpp:8080"
upsert_env "AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT" "/v1/chat/completions"
upsert_env "AI_LOCAL_MODEL" "llama-3.2-3b-instruct-q4_k_m"

upsert_env "LLAMACPP_IMAGE" "websrc-llamacpp:vulkan"
upsert_env "LLAMACPP_HOST_PORT" "8081"
upsert_env "LLAMACPP_GPU_LAYERS" "28"

if [[ -n "$DRI_RENDER" ]]; then
  upsert_env "LLAMACPP_DRI_RENDER" "$DRI_RENDER"
fi

if [[ -n "$DRI_CARD" ]]; then
  upsert_env "LLAMACPP_DRI_CARD" "$DRI_CARD"
fi

upsert_env "VK_ICD_FILENAMES" "/usr/share/vulkan/icd.d/radeon_icd.json"

upsert_env "AI_LOCAL_TIMEOUT_SECONDS" "18"
upsert_env "AI_LOCAL_RETRIES" "1"
upsert_env "AI_LOCAL_BACKOFF_MS" "250"
upsert_env "AI_LOCAL_CIRCUIT_FAIL_THRESHOLD" "3"
upsert_env "AI_LOCAL_CIRCUIT_OPEN_SECONDS" "90"
upsert_env "AI_LOCAL_ADAPTIVE_MIN_PER_RUN" "2"
upsert_env "AI_LOCAL_MAX_ENRICH_PER_RUN" "8"

echo "[ok] Preset RX580 produção aplicado em $ENV_FILE"
echo "[info] LLAMACPP_DRI_CARD=$(grep '^LLAMACPP_DRI_CARD=' "$ENV_FILE" | cut -d'=' -f2-)"
echo "[info] LLAMACPP_DRI_RENDER=$(grep '^LLAMACPP_DRI_RENDER=' "$ENV_FILE" | cut -d'=' -f2-)"
echo "[next] Rode: bash ./scripts/start-llamacpp-vulkan-build.sh"

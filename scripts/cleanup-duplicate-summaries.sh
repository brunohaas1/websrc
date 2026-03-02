#!/usr/bin/env bash
set -euo pipefail

API_BASE="${1:-http://127.0.0.1:8000}"

echo "[1/2] Disparando limpeza de resumos duplicados..."
curl -fsS -X POST "${API_BASE}/api/maintenance/cleanup-summaries" && echo

echo "[2/2] Observabilidade atual:"
curl -fsS "${API_BASE}/api/ai-observability" && echo

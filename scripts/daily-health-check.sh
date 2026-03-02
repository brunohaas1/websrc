#!/usr/bin/env bash
set -euo pipefail

echo "=== SERVICES ==="
docker compose ps

echo
echo "=== LLAMACPP DEVICE ==="
docker exec ws-llamacpp /app/llama-server --list-devices || true

echo
echo "=== HEALTH ==="
curl -fsS http://127.0.0.1/health && echo
curl -fsS http://127.0.0.1:8000/api/ai-observability && echo

echo
echo "=== LATENCY TEST (10 req) ==="
for i in {1..10}; do
  curl -s -o /dev/null -w "%{time_total}\n" \
    http://127.0.0.1:8081/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"llama-3.2-3b-instruct-q4_k_m","messages":[{"role":"user","content":"resuma em uma frase o cenário de tecnologia hoje"}]}'
done | awk '{sum+=$1; n++} END {printf("avg_request_seconds=%.3f (n=%d)\n", sum/n, n)}'

echo
echo "=== WORKER WARNINGS (60m) ==="
docker logs ws-worker --since 60m 2>&1 | grep -Ei "fallback|error|timeout|source=|type=" | tail -n 120 || true

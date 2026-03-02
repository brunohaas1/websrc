# Deploy no servidor (Ubuntu/CasaOS) — guia direto

Este guia é o caminho curto para publicar o projeto no servidor e validar tudo.

## 1) Pré-requisitos no servidor

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER
# relogue no servidor após esse comando
```

Opcional (se usar firewall):

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8000/tcp
```

## 2) Copiar projeto para o servidor

### Opção A: via Git (recomendado)

```bash
git clone <URL_DO_SEU_REPO> websrc
cd websrc
```

### Opção B: via SCP (Windows PowerShell)

No seu PC (dentro da pasta pai):

```powershell
scp -r .\websrc usuario@IP_DO_SERVIDOR:/home/usuario/
```

No servidor:

```bash
cd /home/usuario/websrc
```

## 3) Configurar ambiente

```bash
cp .env.advanced.example .env.advanced
```

Ajuste no `.env.advanced` (mínimo):

- `SECRET_KEY`
- `CORS_ALLOWED_ORIGINS`
- `AI_LOCAL_MODEL=llama-3.2-3b-instruct-q4_k_m`
- (Opcional economia) `FEED_ENTRY_LIMIT=25`

## 4) Subir stack avançado

```bash
docker compose up -d --build
```

### Alternativa: `llama.cpp` (servidor próprio)

Modo pronto para uso:

```bash
cp .env.llamacpp.example .env.advanced
bash ./scripts/start-llamacpp-server.sh
```

Isso já sobe os serviços corretos (`api`, `worker`, `scheduler`, `redis`,
`postgres`, `caddy`, `llamacpp`) sem depender do `ollama`.

Por padrão, o `llama.cpp` é publicado na porta `8081` do host para não
conflitar com o CasaOS em `8080`.

Se ocorrer `manifest unknown` no pull da imagem, ajuste no `.env.advanced`:

```dotenv
LLAMACPP_IMAGE=ghcr.io/ggml-org/llama.cpp:server
```

Se subir mas continuar em CPU-only, use o fallback de build local Vulkan:

```bash
bash ./scripts/start-llamacpp-vulkan-build.sh
```

Esse script compila `llama.cpp` com `GGML_VULKAN=ON` e sobe o stack usando
imagem local `websrc-llamacpp:vulkan`.

Se o host usar `card1` (e não `card0`), você pode forçar no comando:

```bash
LLAMACPP_DRI_CARD=/dev/dri/card1 LLAMACPP_DRI_RENDER=/dev/dri/renderD128 \
bash ./scripts/start-llamacpp-vulkan-build.sh
```

1. Coloque o modelo GGUF em `./models` com nome:

- `llama-3.2-3b-instruct-q4_k_m.gguf`

2. Suba stack (o `llama.cpp` já está integrado):

```bash
docker compose up -d --build
```

3. Verifique se o serviço subiu:

```bash
docker compose ps
docker logs ws-llamacpp --tail 120
```

## 5) Preparar modelo local (`llama.cpp`)

Coloque o GGUF em `./models` com o nome esperado pelo projeto:

```bash
ls -lh ./models/llama-3.2-3b-instruct-q4_k_m.gguf
```

## 6) Validar aplicação e pipeline de IA

Saúde dos serviços:

```bash
curl http://127.0.0.1/health
curl http://127.0.0.1/metrics
```

Disparar coleta manual:

```bash
curl -X POST http://127.0.0.1:8000/api/run-now
```

Checar observabilidade da IA:

```bash
curl http://127.0.0.1:8000/api/ai-observability
```

Logs úteis:

```bash
docker logs ws-worker --tail 120
docker logs ws-api --tail 120
```

Manutenção (resumos antigos duplicados):

```bash
curl -X POST http://127.0.0.1:8000/api/maintenance/cleanup-summaries
```

Check diário de saúde/performance:

```bash
bash ./scripts/daily-health-check.sh
```

## 7) CasaOS (se preferir interface)

- Crie app custom com `docker-compose.yml`
- Monte volume persistente para `./data:/app/data`
- Deixe restart policy `unless-stopped`
- Garanta que o arquivo GGUF esteja em `./models`

## 8) Rollback rápido

Se precisar voltar configuração:

```bash
git checkout -- .env.advanced docker-compose.yml app/config.py
```

Reiniciar stack:

```bash
docker compose up -d --build
```

## 9) Comandos de operação diária

Atualizar código e subir novamente:

```bash
git pull
docker compose up -d --build
```

Parar tudo:

```bash
docker compose down
```

## 10) Dica para RX580 (8GB)

A latência só melhora se o container usar GPU de fato. No servidor, valide se `llama.cpp` está usando Vulkan e monitore latência com:

```bash
curl http://127.0.0.1:8000/api/ai-observability
```

Se quiser, no próximo passo eu te passo o checklist ROCm/AMD específico para RX580 (host + Docker + validação).
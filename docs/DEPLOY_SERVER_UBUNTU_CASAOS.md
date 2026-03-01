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
- `AI_LOCAL_MODEL=llama3.2:3b`
- (Opcional economia) `FEED_ENTRY_LIMIT=25`

## 4) Subir stack avançado

```bash
docker compose -f docker-compose.advanced.yml up -d --build
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

1. Coloque o modelo GGUF em `./models` com nome:

- `llama-3.2-3b-instruct-q4_k_m.gguf`

2. Suba com override do `llama.cpp`:

```bash
docker compose \
	-f docker-compose.advanced.yml \
	-f docker-compose.llamacpp.yml \
	up -d --build
```

3. Verifique se o serviço subiu:

```bash
docker compose ps
docker logs ws-llamacpp --tail 120
```

### Se usar AMD (RX580) para acelerar Ollama

Use o override AMD para mapear dispositivos da GPU no container:

```bash
docker compose \
	-f docker-compose.advanced.yml \
	-f docker-compose.amd.yml \
	up -d --build
```

Antes de subir, confirme que o host enxerga os devices:

```bash
ls -l /dev/kfd /dev/dri
```

Verificar status:

```bash
docker compose -f docker-compose.advanced.yml ps
```

## 5) Baixar modelo local no Ollama

```bash
docker exec -it ws-ollama ollama pull llama3.2:3b
docker exec -it ws-ollama ollama list
```

> Se estiver usando `llama.cpp`, este passo não é necessário.

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

### Validar uso de GPU no Ollama (AMD)

1. Confirme que o container recebeu os devices:

```bash
docker exec ws-ollama sh -lc 'ls -l /dev/kfd /dev/dri'
```

2. Rode uma inferência curta e veja se o modelo entra em execução:

```bash
docker exec ws-ollama ollama run llama3.2:3b "responda apenas ok"
docker exec ws-ollama ollama ps
```

3. Se ainda parecer CPU-only, reinicie só o Ollama e confira logs:

```bash
docker compose -f docker-compose.advanced.yml -f docker-compose.amd.yml restart ollama
docker logs ws-ollama --tail 200
```

Observação para RX580: em alguns hosts AMD Polaris, `HSA_OVERRIDE_GFX_VERSION=8.0.3`
e `ROC_ENABLE_PRE_VEGA=1` podem ser necessários (já incluídos em
`docker-compose.amd.yml`).

O override também força `OLLAMA_LLM_LIBRARY=rocm` para tentar priorizar backend
AMD/ROCm no Ollama.

Se aparecer erro `Unable to find group render`, mantenha o override sem `group_add`
(configuração atual do projeto) e suba novamente.

## 7) CasaOS (se preferir interface)

- Crie app custom com `docker-compose.advanced.yml`
- Monte volume persistente para `./data:/app/data`
- Deixe restart policy `unless-stopped`
- Depois execute o pull do modelo no container `ws-ollama`

## 8) Rollback rápido

Se precisar voltar configuração:

```bash
git checkout -- .env.advanced docker-compose.advanced.yml app/config.py
```

Reiniciar stack:

```bash
docker compose -f docker-compose.advanced.yml up -d --build
```

## 9) Comandos de operação diária

Atualizar código e subir novamente:

```bash
git pull
docker compose -f docker-compose.advanced.yml up -d --build
```

Parar tudo:

```bash
docker compose -f docker-compose.advanced.yml down
```

## 10) Dica para RX580 (8GB)

A latência só melhora se o container usar GPU de fato. No servidor, valide se Ollama está usando aceleração e monitore latência com:

```bash
curl http://127.0.0.1:8000/api/ai-observability
```

Se quiser, no próximo passo eu te passo o checklist ROCm/AMD específico para RX580 (host + Docker + validação).
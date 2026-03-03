# Personal Web Scraper Dashboard (Python + Flask + SQLite + Docker)

Projeto completo de **agregador pessoal inteligente** para rodar 24/7 em servidor Linux doméstico (Ubuntu/CasaOS), coletando metadados da internet e exibindo tudo em um dashboard web único.

Inclui também um **Dashboard Financeiro** com carteira, transações, dividendos, watchlist, relatório de IR, análise por IA, importação de dados e configurações próprias.

## 1) O que este projeto já entrega

- Agregador de notícias via RSS (multi-fontes)
- Monitor de preços com preço alvo + alertas + histórico
- Monitor de promoções/jogos grátis (Epic)
- Monitor de tecnologia/IA (feeds + tendências do GitHub)
- Monitor de releases de repositórios GitHub
- Monitor de vagas (RSS)
- Tracker de vídeos YouTube por feed cronológico (sem algoritmo)
- Clima atual (Open-Meteo)
- Dashboard web responsivo, com busca e filtros
- Dashboard financeiro completo (`/finance`) com:
  - ativos, transações, metas, dividendos, rebalanceamento e relatório IR
  - importação CSV/Excel, nota de corretagem e movimentação B3/CEI
  - configuração in-app (token BRAPI, chave finance, IA local e câmbio)
- Execução automática com scheduler interno (APScheduler)
- Persistência em SQLite
- Dockerfile + docker-compose para rodar no servidor

## 2) Arquitetura

```text
app/
  __init__.py              # create_app + init DB + rotas + scheduler
  config.py                # variáveis de ambiente
  db.py                    # schema SQLite e conexão
  repository.py            # acesso a dados (upsert, consultas, alertas)
  routes.py                # APIs e página principal
  scheduler.py             # jobs periódicos
  sources.py               # lista de feeds e fontes monitoradas
  utils.py                 # logging, robots.txt, helpers HTTP/preço
  services/
    base.py                # contrato base dos coletores
    orchestrator.py        # coordena jobs frequentes e diários
    rss_service.py         # coletor RSS genérico (news, youtube, jobs, AI)
    price_service.py       # scraping leve de preço (com robots.txt)
    promotions_service.py  # promoções/jogos grátis
    weather_service.py     # clima
    github_service.py      # tendências GitHub
    releases_service.py    # últimas releases
templates/
  index.html               # dashboard single-page
static/
  style.css                # UI simples e responsiva
  app.js                   # consumo das APIs, busca, filtros e renderização
run.py                     # entrypoint do app
```

## 3) Fluxo de dados

1. Scheduler dispara coletores:
   - Frequentes (15–60 min): notícias, tech/IA, YouTube, preços, clima
   - Diários: promoções, GitHub trends, releases, vagas
2. Cada coletor transforma o resultado em metadados padronizados.
3. `Repository` faz `upsert` com chave de deduplicação.
4. Dashboard consulta `/api/dashboard` e renderiza tudo em uma única tela.

## 4) Boas práticas e segurança implementadas

- Uso de RSS/API sempre que possível
- Scraping HTML somente no monitor de preços
- Verificação de `robots.txt` antes de scraping de preço
- Armazenamento apenas de metadados + links originais
- Intervalos configuráveis para baixa carga
- Logs e tratamento de exceções por coletor
- Rate limiting em rotas críticas (`/api/run-now`, `/api/price-watch`)
- Sanitização de payload no cadastro de monitor de preços
- `X-Request-Id` por requisição para rastreabilidade
- Logs estruturados em JSON (configurável por `LOG_JSON`)
- Endpoint de métricas Prometheus (`/metrics`)
- Cache com TTL para leitura de dashboard/listagens

## 5) Como rodar localmente (sem Docker)

```bash
python -m venv .venv
source .venv/bin/activate  # no Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python run.py
```

Acesse: http://localhost:8000

## 6) Como rodar com Docker (recomendado)

```bash
docker compose --env-file .env.advanced up -d --build
```

Acesse: http://IP_DO_SERVIDOR:8000

Parar:

```bash
docker compose down
```

## 7) Deploy no Ubuntu + CasaOS (24/7)

Guia direto (copiar → subir → validar): `docs/DEPLOY_SERVER_UBUNTU_CASAOS.md`

### Opção A: CasaOS

1. Suba este diretório no servidor.
2. No CasaOS, crie um app custom usando o `docker-compose.yml`.
3. Configure volume persistente para `./data:/app/data`.
4. Defina restart policy como `unless-stopped`.

### Opção B: Ubuntu CLI

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# relogar
cd /caminho/do/projeto
docker compose up -d --build
```

## 8) Personalização rápida

- Fontes RSS/YouTube/jobs: editar `app/sources.py`
- Intervalos de coleta: `SCRAPE_INTERVAL_MINUTES`, `DAILY_INTERVAL_HOURS`
- Cap de parsing por feed RSS: `FEED_ENTRY_LIMIT` (recomendado 25-35)
- Localização do clima: `WEATHER_LAT`, `WEATHER_LON`
- Produtos monitorados: via formulário do dashboard
- Cache da API: `CACHE_TTL_SECONDS`
- Limites de API: `API_RATE_LIMIT_DEFAULT`, `API_RATE_LIMIT_RUN_NOW`
- Formato de logs: `LOG_JSON=1` (JSON) ou `LOG_JSON=0` (texto)
- Banco: `DATABASE_URL` (Postgres) ou `DATABASE_PATH` (SQLite fallback)
- Health diário: `bash ./scripts/daily-health-check.sh`
- Limpeza de resumos duplicados: `bash ./scripts/cleanup-duplicate-summaries.sh`
- Cotações de ações no financeiro: `BRAPI_TOKEN` (com fallback automático)

## 9) Próximos passos sugeridos

- Adicionar autenticação (login simples)
- Enviar alertas para Telegram/Discord/Email
- Criar testes automatizados dos coletores

## 10) Evolução profissional (roadmap executável)

Para evoluir este projeto em nível portfólio/profissional, use:

- Plano de 14 dias com checklist diário: `docs/EVOLUTION_14_DAYS.md`
- Compose único (api + worker + postgres + redis + caddy + llama.cpp): `docker-compose.yml`
- Exemplo de variáveis para arquitetura avançada: `.env.advanced.example`
- Exemplo pronto para `llama.cpp`: `.env.llamacpp.example`

### Como testar o compose único

1. Copie `.env.advanced.example` para `.env.advanced`.
2. Suba o stack:

```bash
docker compose up -d --build
```

O `llama.cpp` já está integrado no `docker-compose.yml`.

> Requer modelo GGUF em `./models` (ex.: `llama-3.2-3b-instruct-q4_k_m.gguf`).

Fluxo turnkey no servidor (sem ajustes manuais):

```bash
cp .env.llamacpp.example .env.advanced
bash ./scripts/start-llamacpp-server.sh
```

> O `llama.cpp` fica exposto em `8081` por padrão (host), evitando conflito
> com CasaOS em `8080`.
> Se houver erro de pull de imagem, ajuste `LLAMACPP_IMAGE` no `.env.advanced`.

Fallback robusto (build local com Vulkan habilitado):

```bash
bash ./scripts/start-llamacpp-vulkan-build.sh
```

Esse fluxo compila uma imagem local (`websrc-llamacpp:vulkan`) com
`GGML_VULKAN=ON` para evitar binários sem suporte GPU.

Preset produção para RX580 (latência menor e menos fallback):

```bash
bash ./scripts/apply-rx580-prod-preset.sh
bash ./scripts/start-llamacpp-vulkan-build.sh
```

3. Acesse via proxy: `http://IP_DO_SERVIDOR`

> Nota: este compose avançado já organiza serviços por responsabilidade e infraestrutura,
> mas a migração completa para fila assíncrona dedicada deve seguir a sequência em
> `docs/EVOLUTION_14_DAYS.md` para evitar regressão.

### Executar Fase 1 agora (separação API/worker/scheduler)

1. Instale dependências atualizadas:

```bash
pip install -r requirements.txt
```

2. Local (sem Docker) em 3 terminais:

```bash
# terminal 1
set APP_ROLE=api && set QUEUE_ENABLED=1 && python run.py

# terminal 2
set APP_ROLE=worker && set QUEUE_ENABLED=1 && python -m app.worker_main

# terminal 3
set APP_ROLE=scheduler && set QUEUE_ENABLED=1 && python -m app.scheduler_main
```

3. Com Docker (recomendado para servidor):

```bash
cp .env.advanced.example .env.advanced
docker compose up -d --build
```

### Executar Fase 2 e 3 já implementadas

Essas etapas já estão aplicadas no código atual:

- **Performance**: cache TTL para `/api/dashboard` e `/api/items`
- **Segurança**: rate limiting + validação/sanitização de entrada
- **Observabilidade**: logs JSON + request id + `/metrics`

Validação rápida:

```bash
curl http://127.0.0.1/health
curl http://127.0.0.1/metrics
curl -X POST http://127.0.0.1/api/run-now
```

### Atalho para "fazer tudo" (auto Docker ou fallback local)

No PowerShell:

```powershell
./scripts/start-all.ps1
```

- Se Docker daemon estiver ativo: sobe `api + worker + scheduler + redis + postgres + caddy + llamacpp`.
- Se Docker daemon não estiver ativo: inicia fallback local com `APP_ROLE=all`.

Para parar tudo:

```powershell
./scripts/stop-all.ps1
```

## 11) IA local para resumo/categoria/relevância (llama.cpp)

O projeto suporta enriquecimento local dos itens com:

- `ai_summary` (resumo em uma linha)
- `ai_category` (categoria)
- `ai_score` (relevância 0-100)

### Variáveis

No `.env.advanced`:

```dotenv
AI_LOCAL_ENABLED=1
AI_LOCAL_BACKEND=llama_cpp
AI_LOCAL_URL=http://llamacpp:8080
AI_LOCAL_LLAMA_CPP_CHAT_ENDPOINT=/v1/chat/completions
AI_LOCAL_MODEL=llama-3.2-3b-instruct-q4_k_m
LLAMACPP_IMAGE=ghcr.io/ggml-org/llama.cpp:full
LLAMACPP_HOST_PORT=8081
LLAMACPP_GPU_LAYERS=60
LLAMACPP_MEM_LIMIT=3g
LLAMACPP_CTX_SIZE=2048
LLAMACPP_DRI_RENDER=/dev/dri/renderD128
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.json
AI_LOCAL_TIMEOUT_SECONDS=25
AI_LOCAL_RETRIES=2
AI_LOCAL_BACKOFF_MS=400
AI_LOCAL_CIRCUIT_FAIL_THRESHOLD=3
AI_LOCAL_CIRCUIT_OPEN_SECONDS=120
AI_LOCAL_ADAPTIVE_MIN_PER_RUN=5
AI_LOCAL_MAX_ENRICH_PER_RUN=16
BRAPI_TOKEN=seu_token_brapi
```

### Financeiro: importação e configurações

- Endpoint principal: `/finance`
- Importações disponíveis no modal de importação:
  - Importação geral (`/api/finance/import`)
  - Nota de corretagem (`/api/finance/import-nota`)
  - Movimentação B3/CEI (`/api/finance/import-b3`)
- Configurações no botão `⚙️` do topo do financeiro:
  - BRAPI Token
  - Finance API Key
  - URL/modelo/timeout da IA local
  - API e intervalo de atualização de câmbio

### Preparar modelo

Para `llama.cpp`, coloque o GGUF em `./models` antes de subir o
`docker-compose.yml`.

Se o log mostrar `loaded CPU backend` e `compiled without GPU support`, use
`LLAMACPP_IMAGE=ghcr.io/ggml-org/llama.cpp:full` no `.env.advanced` e recrie o
serviço `llamacpp`.

### Como funciona

- A IA roda no fluxo de coleta para itens novos (com limite por execução).
- Se o modelo/local endpoint falhar, o sistema aplica fallback por palavras-chave.
- No dashboard, os cards mostram categoria e score quando disponíveis.
- O frontend reduz polling em background (60s visível, 5min em segundo plano).

### Backfill único de IA (itens já no banco)

Para enriquecer tudo que já existe no banco agora (uma vez), sem mudar a rotina
normal depois:

```bash
curl -X POST "http://127.0.0.1:8000/api/maintenance/ai-backfill?batch_size=80&max_cycles=120"
```

- Com fila (`QUEUE_ENABLED=1`), o endpoint enfileira job e retorna `job`.
- Sem fila, executa síncrono e retorna `scanned/updated/model/fallback`.

---

Projeto focado em aprendizado prático, modular e escalável.

# Plano de Evolução (14 dias) — Web Scraper Dashboard

Objetivo: evoluir de MVP funcional para arquitetura profissional, modular e escalável sem interromper o serviço atual.

## Meta de arquitetura alvo

- `api` (FastAPI ou Flask com camada de serviço)
- `worker` (scrapers assíncronos)
- `scheduler` (apenas agenda jobs)
- `redis` (fila + cache)
- `postgres` (persistência principal)
- `caddy` (TLS reverso para acesso externo seguro)

## Princípios de execução

1. **Sem downtime**: sempre manter o stack atual disponível.
2. **Mudança incremental**: introduzir novos componentes em paralelo.
3. **Idempotência**: jobs podem rodar mais de uma vez sem duplicar dados.
4. **Métricas antes de otimizar**: medir para decidir.

---

## Fase 1 — Fundação (Dias 1–4)

### Dia 1 — Baseline técnico

Checklist:
- [ ] Medir tempo médio de cada coletor (news, jobs, youtube etc.)
- [ ] Medir tamanho atual do SQLite e número de registros por tipo
- [ ] Definir SLO inicial (ex.: sucesso de coleta >= 95%)
- [ ] Criar pasta `docs/adr` com decisões arquiteturais

Justificativa:
- Sem baseline, otimização vira tentativa e erro.

### Dia 2 — Separação de responsabilidades

Checklist:
- [ ] Criar entrypoint dedicado para API
- [ ] Criar entrypoint dedicado para worker
- [ ] Criar entrypoint dedicado para scheduler
- [ ] Garantir que API não execute scraping diretamente

Justificativa:
- Isola falhas e melhora manutenção.

### Dia 3 — Redis para fila/cache

Checklist:
- [ ] Subir Redis no compose
- [ ] Definir padrão de chaves de cache (`feed:{hash_url}`)
- [ ] Enfileirar jobs via fila (RQ/Celery)
- [ ] Implementar TTL de cache (15–60 min)

Justificativa:
- Reduz chamadas externas e desacopla execução pesada da API.

### Dia 4 — Jobs idempotentes e deduplicação forte

Checklist:
- [ ] Adicionar `external_id` quando existir (RSS guid/videoId)
- [ ] Criar hash de URL canônica
- [ ] Definir `UNIQUE` por origem + identificador
- [ ] Registrar tentativas/falhas por job

Justificativa:
- Evita lixo de dados e duplicatas em cenários reais.

---

## Fase 2 — Dados e performance (Dias 5–8)

### Dia 5 — Preparação SQLite → PostgreSQL

Checklist:
- [ ] Introduzir SQLAlchemy + Alembic
- [ ] Versionar schema com migrations
- [ ] Padronizar tipos (`TIMESTAMPTZ`, `JSONB` no PG)
- [ ] Criar script de migração inicial

Justificativa:
- Crescimento e consultas analíticas exigem banco robusto.

### Dia 6 — Índices e consultas

Checklist:
- [ ] Índice `(item_type, published_at DESC)`
- [ ] Índice `(source, published_at DESC)`
- [ ] Índice parcial para alertas não lidos
- [ ] Paginação cursor-based para endpoints de lista

Justificativa:
- Dashboard e API mantêm resposta rápida com volume maior.

### Dia 7 — HTTP eficiente e assíncrono

Checklist:
- [ ] Migrar clientes para `httpx.AsyncClient` com pooling
- [ ] Adicionar `If-None-Match`/`If-Modified-Since`
- [ ] Retry com backoff exponencial + jitter
- [ ] Timeout por categoria de fonte

Justificativa:
- Menos latência, menor consumo e maior resiliência.

### Dia 8 — Caching de leitura da API

Checklist:
- [ ] Cachear snapshot do dashboard por 30–120s
- [ ] Invalidar cache quando job finalizar
- [ ] Incluir chave de busca/filtro nos endpoints
- [ ] Definir hit-rate mínimo (meta 60%+)

Justificativa:
- API fica estável mesmo com picos de atualização da UI.

---

## Fase 3 — Segurança e observabilidade (Dias 9–11)

### Dia 9 — Segurança de aplicação

Checklist:
- [ ] Rate limit por IP/rota
- [ ] Validação rigorosa de payloads (Pydantic/Marshmallow)
- [ ] Sanitização de HTML/resumos
- [ ] Bloqueio SSRF (deny IP interno/localhost)

Justificativa:
- Reduz superfície de abuso e entrada maliciosa.

### Dia 10 — Segurança Docker/infra

Checklist:
- [ ] Rodar containers como usuário não-root
- [ ] `read_only: true` onde possível
- [ ] Limites de CPU/RAM por serviço
- [ ] Segregar rede interna (db/redis sem porta pública)

Justificativa:
- Melhora isolamento e previsibilidade em servidor doméstico.

### Dia 11 — Logs, métricas, alertas

Checklist:
- [ ] Logs JSON com `trace_id` e `job_id`
- [ ] Métricas Prometheus (tempo, erro, itens novos)
- [ ] Dashboard básico (Grafana opcional)
- [ ] Alertas para falha consecutiva por fonte

Justificativa:
- Você passa a operar o sistema com dados, não sensação.

---

## Fase 4 — Portfólio avançado (Dias 12–14)

### Dia 12 — UX e filtros inteligentes

Checklist:
- [ ] Busca rápida com paginação e ordenação
- [ ] Filtros por fonte/tópico/período
- [ ] Preferências por usuário (tema, widgets, fontes)
- [ ] Melhorar acessibilidade (teclado/contraste)

### Dia 13 — IA opcional pragmática

Checklist:
- [ ] Resumo diário por categoria
- [ ] Classificação de relevância (score)
- [ ] Deduplicação semântica (embeddings leves)
- [ ] Limite de custo/tempo por execução

### Dia 14 — Hardening final e showcase

Checklist:
- [ ] CI com lint/test/build
- [ ] Backup automático de Postgres
- [ ] Documento de arquitetura + ADRs
- [ ] Vídeo/demo + README de portfólio

Resultado esperado:
- Projeto pronto para apresentar como caso real de engenharia.

---

## Backlog pós-14 dias (futuro)

- Multiusuário com autenticação robusta (JWT + refresh)
- API pública com plano de versionamento (`/v1`)
- App mobile consumindo API
- Multi-tenant por workspace de usuário

## Definição de pronto por fase

- Fase concluída = checklist completo + evidência (log, métrica, screenshot, benchmark).

---

## Progresso aplicado nesta execução

Status real do projeto após implementação sequencial:

- ✅ Fase 1 (parcial alta): separação `api/worker/scheduler` + fila Redis/RQ + jobs enfileirados
- ✅ Fase 2 (parcial): cache de leitura com TTL em endpoints principais
- ✅ Fase 3 (parcial alta):
	- rate limiting em rotas críticas
	- sanitização/validação de payload de entrada
	- logs estruturados JSON com `request_id`
	- endpoint `/metrics` para Prometheus

Itens ainda pendentes para concluir 100% do roadmap:

- migração completa de SQLite para PostgreSQL em runtime da aplicação
- Alembic/migrations versionadas
- SLO/alertas externos (ex.: Telegram/Discord) automatizados
- autenticação/multiusuário

# Finance Routes Modularization Plan (Item 4)

## Objetivo
Decomposição de `app/finance_routes.py` (7855 linhas) em blueprints de domínio mantendo compatibilidade de API.

## Status Atual
- **Arquivo**: `app/finance_routes.py` (7855 linhas)
- **Domínios Identificados**:
  1. **Cashflow** (~3700 linhas) - FASE 1
  2. **Watchlist** (~400 linhas) - FASE 2
  3. **Assets/Transactions** (~500 linhas) - FASE 3
  4. **Security/2FA** (~300 linhas) - FASE 4

- **Shared Infrastructure** (todas as fases):
  - Cache invalidation helpers
  - Audit logging (`_audit()`)
  - Input sanitization
  - OCR/ML helpers
  - Constants (FINANCE_CACHE_TTLS, etc.)

## Fases de Execução

### FASE 1: Cashflow Blueprint (Atual)

**Objetivo**: Extrair domínio de cashflow para módulo separado.

**Arquivos a Criar**:
1. `app/finance_blueprints/cashflow.py` - Rotas de cashflow
2. `app/finance_blueprints/cashflow_helpers.py` - Funções auxiliares

**Rotas Incluídas** (~20+ endpoints):
- `/api/finance/cashflow` (GET/POST/PUT/DELETE)
- `/api/finance/cashflow/installments`
- `/api/finance/cashflow/budget`
- `/api/finance/cashflow/saved-filters`
- `/api/finance/cashflow/ocr`
- `/api/finance/cashflow/import`
- `/api/finance/cashflow/recurring`
- `/api/finance/cashflow/analytics`
- `/api/finance/cashflow/kpis`
- E 10+ rotas adicionais

**Funções Auxiliares**:
- OCR: `_extract_text_from_receipt_image()`, `_extract_receipt_date/amount/merchant()`
- Classification: `_infer_cashflow_category_from_text()`, `_infer_cashflow_entry_type_from_text()`
- CNPJ: `_extract_cnpj()`, `_lookup_cnpj_data()`, `_lookup_cnpj_name()`
- Validation: `_is_finite_number()`, `_as_float()`
- Dedup: Integração com `SmartDedupeCache`

**Estratégia de Implementação**:
1. Copiar helpers para novo módulo
2. Copiar funções registradoras de rota
3. Criar função `register_cashflow_routes(app, limiter, repo, cache, logger)`
4. Importar em `register_finance_routes()` e chamar
5. Remover código copiado do arquivo original
6. Rodar testes: `pytest tests/test_finance.py -xvs`

**Resultado Esperado**:
- ✅ Todos os 170 testes passando
- ✅ URLs de API idênticas (compatibilidade 100%)
- ✅ 3700 linhas movidas, arquivo reduzido de 7855 → ~4100

---

### FASE 2: Watchlist Blueprint

**Objetivo**: Extrair domínio de watchlist.

**Arquivos**:
- `app/finance_blueprints/watchlist.py`
- `app/finance_blueprints/watchlist_helpers.py`

**Rotas** (~8 endpoints):
- `/api/finance/watchlist` (GET/POST/DELETE)
- `/api/finance/watchlist/<id>/price-alerts`
- `/api/finance/watchlist/sync`

**Resultado Esperado**:
- Arquivo reduzido para ~3700 linhas
- 170 testes passando

---

### FASE 3: Assets/Transactions Blueprint

**Objetivo**: Extrair domínio de ativos e transações.

**Arquivos**:
- `app/finance_blueprints/assets.py`
- `app/finance_blueprints/transactions.py`

**Rotas** (~15 endpoints):
- `/api/finance/assets`
- `/api/finance/assets/<id>/transactions`
- `/api/finance/transactions`

**Resultado Esperado**:
- Arquivo reduzido para ~3200 linhas
- 170 testes passando

---

### FASE 4: Security/2FA Blueprint

**Objetivo**: Extrair segurança e autenticação 2FA.

**Arquivos**:
- `app/finance_blueprints/security.py`

**Rotas** (~6 endpoints):
- `/api/finance/settings`
- `/api/finance/2fa`

**Resultado Esperado**:
- Arquivo reduzido para ~2900 linhas (principalmente helpers compartilhados)
- 170 testes passando

---

## Critério de Sucesso por Fase

- ✅ Nenhuma alteração em URLs de API
- ✅ Todos os 170 testes continuam passando
- ✅ Redução de linhas por arquivo
- ✅ Sem mudança em comportamento ou performance
- ✅ Código bem documentado

## Validação Pós-Modularização

```bash
# Fase 1 validação
pytest tests/test_finance.py -k cashflow -v
pytest tests/test_finance.py --tb=short

# Verificar compatibilidade de API
curl http://localhost:5000/api/finance/cashflow?limit=10
```

## Notas Técnicas

- **Helpers Compartilhados**: Permanecem em `finance_routes.py` ou movem para `finance_common.py`
- **Cache/Repo/Limiter**: Injetados como parâmetros para cada função registradora
- **Constantes**: Definidas no módulo principal, importadas conforme necessário
- **Backward Compatibility**: URL paths não mudam; apenas estrutura interna é reorganizada

## Timeline

- **Fase 1**: 2-3 horas (maior, mais complexa)
- **Fase 2**: 1 hora
- **Fase 3**: 1-2 horas
- **Fase 4**: 30-45 min
- **Validação Total**: 15 min

**Total Estimado**: 5-8 horas de trabalho incremental

---

**Status Atual**: Iniciando FASE 1 - Cashflow Blueprint


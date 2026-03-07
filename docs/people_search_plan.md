# Plano de etapas para a nova aba "Busca de Pessoas"

## 1. UI
- Campo de texto para nome
- Botão "Buscar"
- Indicador de carregamento
- Área de resultados por categoria

## 2. Backend
- Endpoint Flask: /api/people_search
- Recebe nome, inicia scraping
- Busca em mecanismo (Google/Bing/DuckDuckGo)
- Coleta links, visita páginas, extrai dados
- Limite de páginas, deduplicação, tratamento de erros

## 3. Classificação
- NLP/regras para separar em categorias
- Informações Gerais, Profissional, Redes Sociais, Notícias, Links Relevantes

## 4. Integração
- AJAX frontend/backend
- Exibição dos resultados
- Expandir detalhes, exportar JSON

## 5. Extras
- Cache de buscas
- Sistema de pontuação de relevância
- Exportação

## Modularidade
- Separar scraping, classificação, cache, exportação em módulos

---

### Próximos passos:
1. Criar UI protótipo (HTML)
2. Implementar endpoint Flask
3. Desenvolver módulo de scraping
4. Implementar classificação
5. Integrar frontend/backend
6. Adicionar extras

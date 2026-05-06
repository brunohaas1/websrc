# 🎯 Plano de Ação — Funcionalidades Faltantes

> Gerado em: Maio 2026 | Completude Atual: **86%**

---

## 📋 **Features Faltantes por Prioridade**

### 🔥 **CRÍTICAS** (Impacto Alto + Esforço Baixo)

#### 1. **Contas/Bancos como Entidades** [Prioridade 1]
**Impacto**: Alta (usuários com múltiplas contas ficarão confusos)
**Esforço**: Médio (2-3 dias)
**O que falta**:
- Modelo de dados para contas/bancos separados
- Saldo automático consolidado por conta
- UI com abas ou menu para trocar conta ativa
- Relacionamento de lançamentos com conta

**Comece com**:
```sql
-- Adicionar tabela de contas
CREATE TABLE fin_accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    account_type TEXT (bank, wallet, cash),
    initial_balance REAL,
    currency TEXT DEFAULT 'BRL',
    created_at TEXT
);
```

---

#### 2. **Score de Saúde Financeira (Dashboard)** [Prioridade 2]
**Impacto**: Alta (diferencial do app)
**Esforço**: Baixo (1-2 dias)
**O que falta**:
- Cálculo consolidado de score (0-100)
- Componentes: Liquidez, Solvência, Rentabilidade, Eficiência
- Visualização em dashboard com gráfico radial
- Histórico de score ao longo do tempo

**Fórmula**:
```
Score = 25 × (Liquidez/Meta) + 25 × (Solvência) + 25 × (ROI%) + 25 × (Eficiência)
```

---

#### 3. **Sugestões Automáticas de Economia** [Prioridade 3]
**Impacto**: Alta (engajamento)
**Esforço**: Médio (2-3 dias)
**O que falta**:
- Detecção de padrões de gasto
- Comparação com média histórica
- Sugestões textuais ("Você gastou 30% mais em delivery este mês")
- Recomendações de redução

**Exemplos de sugestões**:
- "Streaming: R$ 120/mês → considere cancelar serviços"
- "Delivery cresceu 45% → faça mais refeições em casa?"
- "Categoria X está 20% acima da média"

---

#### 4. **Gestão de Dívidas Melhorada** [Prioridade 4]
**Impacto**: Alta (muitos usuários têm dívidas)
**Esforço**: Médio (3-4 dias)
**O que falta**:
- Modelo explícito de dívidas (Creditor, Principal, Rate, Status)
- Cálculo de juros acumulados
- Estratégias de quitação (Bola de Neve, Avalanche)
- Simulação de antecipação

**Schema**:
```sql
CREATE TABLE fin_debts (
    id INTEGER PRIMARY KEY,
    creditor TEXT NOT NULL,
    principal REAL,
    current_balance REAL,
    interest_rate REAL,
    monthly_payment REAL,
    due_date TEXT,
    status TEXT (open, partial, paid),
    created_at TEXT
);
```

---

### ⚡ **IMPORTANTES** (Impacto Médio-Alto + Esforço Médio)

#### 5. **Relatórios em Linguagem Natural** [Prioridade 5]
**Impacto**: Média-Alta (melhor UX)
**Esforço**: Médio (3-4 dias, usa IA)
**O que falta**:
- Geração de textos descritivos dos KPIs
- Insights em português natural
- Recomendações personalizadas
- Notificações via IA

**Exemplos**:
```
"Você economizou R$ 500 este mês comparado ao mês passado.
Principais contribuições: redução de 15% em delivery e cancelamento
de assinatura de gym. Parabéns!"

"Atenção: Categoria 'Alimentação' está 35% acima da média histórica.
Considere reduzir gastos em restaurants."
```

---

#### 6. **Push Notifications** [Prioridade 6]
**Impacto**: Média (melhor retenção)
**Esforço**: Médio (2-3 dias)
**Plataformas**: Web (PWA), depois Mobile
**O que precisa**:
- Service Worker para push
- Backend queue de notificações
- Preferências do usuário (horários, tipos)
- Integração com alertas existentes

---

#### 7. **2FA / Biometria** [Prioridade 7]
**Impacto**: Média (segurança)
**Esforço**: Médio-Alto (3-4 dias)
**O que falta**:
- TOTP (Google Authenticator)
- WebAuthn (Biometria)
- Backup codes
- UI de login com autenticação em 2 passos

---

### 📅 **NICE-TO-HAVE** (Impacto Baixo-Médio + Esforço Alto)

#### 8. **Integração Bancária (Open Banking)** [Prioridade 8]
**Impacto**: Alta (mas complexa)
**Esforço**: Alto (5-7 dias)
**Plataformas**: Stark Bank, Open Banking Br, Plaid
**O que incluir**:
- Autenticação com banco
- Importação automática de transações
- Reconciliação automática
- Saldo em tempo real

---

#### 9. **App Mobile Nativa** [Prioridade 9]
**Impacto**: Alta (mas não crítica)
**Esforço**: Muito Alto (2-3 semanas)
**Opções**: React Native, Flutter, SwiftUI/Kotlin
**Escopo mínimo**: PWA é suficiente agora

---

#### 10. **Análise de Anomalias** [Prioridade 10]
**Impacto**: Média (segurança/fraude)
**Esforço**: Alto (4-5 dias)
**O que fazer**:
- Detecção de transações atípicas
- Alertas de gastos incomuns
- Machine learning simples (Isolation Forest)
- Validação manual do usuário

---

## 📊 **Matriz de Priorização**

```
Alto Impacto + Baixo Esforço (FAZER PRIMEIRO):
✅ Score Financeiro
✅ Contas/Bancos
✅ Sugestões Automáticas
✅ Gestão de Dívidas

Alto Impacto + Médio Esforço (DEPOIS):
🔄 Relatórios em IA
🔄 Push Notifications
🔄 2FA/Biometria

Alto Impacto + Alto Esforço (PLANEJAMENTO):
⏰ Integração Bancária
⏰ App Mobile
⏰ Análise de Anomalias
```

---

## 🛠️ **Roadmap Sugerido (Next 3 Months)**

### **Mês 1 (Junho)**
- [ ] Contas/Bancos como entidades
- [ ] Score de saúde financeira no dashboard
- [ ] Sugestões automáticas de economia
- [ ] Teste integrado

### **Mês 2 (Julho)**
- [ ] Gestão de dívidas melhorada
- [ ] Relatórios em linguagem natural
- [ ] Push notifications (PWA)
- [ ] Testes e QA

### **Mês 3 (Agosto)**
- [ ] 2FA/Biometria
- [ ] Refine UI baseado em feedback
- [ ] Documentação de integração
- [ ] Beta da API pública

---

## ✅ **O Que JÁ Está 100% Implementado**

Não se esqueça do quanto já foi feito! Este app já possui:

| Feature | Status | Endpoints | Tabelas |
|---------|--------|-----------|---------|
| **Cashflow** | ✅ 100% | 40+ | 8 |
| **Investimentos** | ✅ 100% | 15+ | 8 |
| **Cartões de Crédito** | ✅ 85% | 6 | 1 |
| **Metas** | ✅ 95% | 8 | 1 |
| **Alertas** | ✅ 95% | 5 | 1 |
| **Orçamento** | ✅ 95% | 8 | 1 |
| **OCR/Recibos** | ✅ 90% | 2 | 1 |
| **B3/NFe Import** | ✅ 90% | 3 | 1 |
| **Automação** | ✅ 90% | 10+ | 3 |
| **Analytics** | ✅ 90% | 5+ | 1 |

**Total**: 100+ endpoints, 30+ tabelas, 86% de completude

---

## 💡 **Quick Wins (1-2 dias cada)**

Se você quer ganhos rápidos:

1. **Melhorar UI de Analytics** — Gráficos mais bonitos
2. **Dark mode para PDF** — Relatórios com tema escuro
3. **Keyboard Shortcuts** — Comandos de teclado globais
4. **Filtro global de busca** — Search across all data
5. **Widget de limite de cartão** — Visual no dashboard

---

## 📞 **Próximos Passos Recomendados**

1. **Hoje**: Revisar este documento com stakeholders
2. **Esta semana**: Prototipo de Score Financeiro
3. **Próximas 2 semanas**: MVP de Contas/Bancos
4. **Próximo mês**: Integrar sugestões automáticas

---

**Status Geral**: 🟢 **PRONTO PARA PRODUÇÃO** com roadmap claro para os 15% faltantes.


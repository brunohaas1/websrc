/* ══════════════════════════════════════════════════════════
  Finance Gestor Financeiro Domain
  ══════════════════════════════════════════════════════════ */

function currentMonthKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function parseTagsInput(raw) {
  const src = String(raw || "").trim();
  if (!src) return [];
  const seen = new Set();
  return src
    .split(",")
    .map((x) => x.trim().toLowerCase())
    .filter((x) => x)
    .filter((x) => {
      if (seen.has(x)) return false;
      seen.add(x);
      return true;
    })
    .slice(0, 12);
}

function prevMonthKey(monthKey) {
  const match = String(monthKey || "").match(/^(\d{4})-(\d{2})$/);
  if (!match) return currentMonthKey();
  const year = Number(match[1]);
  const month = Number(match[2]);
  const d = new Date(Date.UTC(year, month - 1, 1));
  d.setUTCMonth(d.getUTCMonth() - 1);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function getSelectedCashflowMonth() {
  const selected = String(byId("finCashflowMonth")?.value || "").trim();
  return selected || currentMonthKey();
}

function syncCashflowMonthFilter(summary) {
  const sel = byId("finCashflowMonth");
  if (!sel) return;
  const prev = String(sel.value || "");

  const months = Array.isArray(summary?.monthly)
    ? summary.monthly.map((m) => String(m.month || "").slice(0, 7)).filter((m) => /^\d{4}-\d{2}$/.test(m))
    : [];
  const merged = [...new Set([currentMonthKey(), ...months])].sort().reverse();

  const opts = ['<option value="">Todos os meses</option>'];
  merged.forEach((m) => {
    opts.push(`<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`);
  });
  sel.innerHTML = opts.join("");

  const next = merged.includes(prev) ? prev : (prev || currentMonthKey());
  sel.value = next;
}

function renderCashflowSummary(summary) {
  const el = byId("finCashflowSummary");
  if (!el) return;
  const s = summary || {};
  const totals = FIN.cashflowAnalytics?.totals || {};
  const projection = FIN.cashflowAnalytics?.projection || {};
  const balanceCls = Number(s.current_balance || 0) >= 0 ? "fin-up" : "fin-down";
  el.innerHTML = `
    <div class="fin-cashflow-kpis">
      <div class="fin-cashflow-kpi">
        <span>Mês atual • Ganhos</span>
        <strong>${formatBRL(s.current_income || 0)}</strong>
      </div>
      <div class="fin-cashflow-kpi">
        <span>Mês atual • Gastos</span>
        <strong>${formatBRL(s.current_expense || 0)}</strong>
      </div>
      <div class="fin-cashflow-kpi">
        <span>Mês atual • Saldo</span>
        <strong class="${balanceCls}">${formatBRL(s.current_balance || 0)}</strong>
      </div>
      <div class="fin-cashflow-kpi">
        <span>Saldo total</span>
        <strong class="${Number(s.total_balance || 0) >= 0 ? "fin-up" : "fin-down"}">${formatBRL(s.total_balance || 0)}</strong>
      </div>
      <div class="fin-cashflow-kpi">
        <span>Taxa de poupança</span>
        <strong class="${Number(totals.savings_rate_pct || 0) >= 0 ? "fin-up" : "fin-down"}">${formatNumber(totals.savings_rate_pct || 0, 2)}%</strong>
      </div>
      <div class="fin-cashflow-kpi">
        <span>Saldo projetado no mês</span>
        <strong class="${Number(projection.projected_balance || 0) >= 0 ? "fin-up" : "fin-down"}">${formatBRL(projection.projected_balance || 0)}</strong>
      </div>
    </div>
  `;
}

function renderCashflowKpis(kpis) {
  const el = byId("finCashflowKpis");
  if (!el) return;
  if (!kpis) { el.innerHTML = ""; return; }
  const burnRate = Number(kpis.burn_rate || 0);
  const runway = kpis.runway_months;
  const runwayTxt = runway !== null && runway !== undefined
    ? `${formatNumber(runway, 1)} meses`
    : "—";
  const runwayCls = (runway === null || runway === undefined || runway < 3) ? "fin-down" : runway < 6 ? "fin-warn" : "fin-up";
  el.innerHTML = `
    <div class="fin-cashflow-kpis">
      <div class="fin-cashflow-kpi">
        <span>Burn rate (3m)</span>
        <strong class="fin-down">${formatBRL(burnRate)}/mês</strong>
      </div>
      <div class="fin-cashflow-kpi">
        <span>Runway</span>
        <strong class="${runwayCls}">${runwayTxt}</strong>
      </div>
      <div class="fin-cashflow-kpi">
        <span>Taxa de poupança</span>
        <strong class="${Number(kpis.savings_rate_pct || 0) >= 0 ? "fin-up" : "fin-down"}">${formatNumber(kpis.savings_rate_pct || 0, 1)}%</strong>
      </div>
    </div>
  `;
}

function renderCashflowCategoryChart(analytics) {
  const canvas = byId("cashflowCategoryChart");
  if (!canvas || typeof Chart === "undefined") return;

  const expenseRows = Array.isArray(analytics?.categories?.expense)
    ? analytics.categories.expense
    : [];

  if (!expenseRows.length) {
    if (FIN.charts.cashflowCategory) {
      FIN.charts.cashflowCategory.destroy();
      FIN.charts.cashflowCategory = null;
    }
    return;
  }

  const labels = expenseRows.map((r) => r.category || "Sem categoria");
  const values = expenseRows.map((r) => Number(r.amount || 0));
  const colors = chartColors(values.length);

  if (FIN.charts.cashflowCategory) FIN.charts.cashflowCategory.destroy();

  FIN.charts.cashflowCategory = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: colors,
          borderWidth: 0,
          hoverOffset: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "right",
          labels: {
            color: getComputedStyle(document.body).getPropertyValue("--text") || "#e2e8f0",
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = total > 0 ? ((Number(ctx.raw || 0) / total) * 100) : 0;
              return ` ${ctx.label}: ${formatBRL(ctx.raw)} (${pct.toFixed(1)}%)`;
            },
          },
        },
      },
    },
  });
}

function renderCashflowAnalytics(analytics) {
  const el = byId("finCashflowAnalytics");
  if (!el) return;
  const projection = analytics?.projection || {};
  const topExpenses = Array.isArray(analytics?.top_expenses) ? analytics.top_expenses : [];

  const topHtml = topExpenses.length
    ? topExpenses.slice(0, 3).map((row) => `
      <div class="fin-cashflow-chip">
        <span>${escapeHtml(row.category || "Sem categoria")}</span>
        <strong class="fin-down">${formatBRL(row.amount || 0)}</strong>
      </div>
    `).join("")
    : '<div class="fin-cashflow-chip"><span>Top gastos</span><strong>Sem dados</strong></div>';

  el.innerHTML = `
    <div class="fin-cashflow-analytics-grid">
      <div class="fin-cashflow-chip">
        <span>Dias considerados</span>
        <strong>${formatNumber(projection.elapsed_days || 0, 0)} / ${formatNumber(projection.days_in_month || 0, 0)}</strong>
      </div>
      <div class="fin-cashflow-chip">
        <span>Receita projetada</span>
        <strong class="fin-up">${formatBRL(projection.projected_income || 0)}</strong>
      </div>
      <div class="fin-cashflow-chip">
        <span>Despesa projetada</span>
        <strong class="fin-down">${formatBRL(projection.projected_expense || 0)}</strong>
      </div>
      ${topHtml}
    </div>
  `;

  renderCashflowCategoryChart(analytics);
}

function renderCashflowBudgetStatus(analytics) {
  const el = byId("finCashflowBudgetStatus");
  if (!el) return;
  const budget = analytics?.budget || { items: [] };
  const items = Array.isArray(budget.items) ? budget.items : [];
  if (!items.length) {
    el.innerHTML = '<p class="fin-empty">Nenhum orçamento configurado para o mês. Use o botão Orçamento.</p>';
    return;
  }

  const cards = items.map((item) => {
    const over = !!item.over_budget;
    return `
      <div class="fin-cashflow-budget-item ${over ? "fin-over-budget" : ""}">
        <div class="fin-cashflow-budget-item-head">
          <strong>${escapeHtml(item.category || "Sem categoria")}</strong>
          <small>${formatNumber(item.usage_pct || 0, 1)}%</small>
        </div>
        <small>Gasto: ${formatBRL(item.spent || 0)} / Limite: ${formatBRL(item.limit || 0)}</small>
        <div class="fin-goal-bar" style="margin-top:6px;">
          <div class="fin-goal-fill ${over ? "" : "complete"}" style="width:${Math.min(100, Number(item.usage_pct || 0)).toFixed(1)}%"></div>
        </div>
      </div>
    `;
  }).join("");

  el.innerHTML = `
    <div class="fin-cashflow-budget-grid">${cards}</div>
    <div class="fin-cashflow-chip">
      <span>Orçamento total</span>
      <strong>${formatBRL(budget.total_spent || 0)} / ${formatBRL(budget.total_limit || 0)}</strong>
    </div>
  `;
}

function renderCashflowBudgetAlerts(items) {
  // items from /api/finance/cashflow/budget/alerts
  const el = byId("finCashflowBudgetAlerts");
  if (!el) return;
  const alerts = Array.isArray(items) ? items.filter((a) => a.status !== "ok") : [];
  if (!alerts.length) { el.innerHTML = ""; return; }
  el.innerHTML = alerts.map((a) => {
    const cls = a.status === "over" ? "fin-alert-over" : "fin-alert-warn";
    const icon = a.status === "over" ? "🔴" : "🟡";
    return `<span class="fin-budget-alert-badge ${cls}">${icon} ${escapeHtml(a.category)}: ${formatNumber(a.usage_pct, 1)}% (${formatBRL(a.spent)}/${formatBRL(a.limit)})</span>`;
  }).join("");
}

function renderCashflowChart(summary) {
  const canvas = byId("cashflowChart");
  if (!canvas || typeof Chart === "undefined") return;

  const monthly = Array.isArray(summary?.monthly)
    ? summary.monthly
    : [];

  if (!monthly.length) {
    if (FIN.charts.cashflow) {
      FIN.charts.cashflow.destroy();
      FIN.charts.cashflow = null;
    }
    return;
  }

  const ordered = [...monthly].sort((a, b) => String(a.month || "").localeCompare(String(b.month || "")));
  const labels = ordered.map((m) => String(m.month || "").slice(2));
  const incomes = ordered.map((m) => Number(m.income || 0));
  const expenses = ordered.map((m) => Number(m.expense || 0));

  let running = 0;
  const cumulative = ordered.map((m) => {
    running += Number(m.balance || 0);
    return running;
  });

  if (FIN.charts.cashflow) FIN.charts.cashflow.destroy();

  FIN.charts.cashflow = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          type: "bar",
          label: "Ganhos",
          data: incomes,
          backgroundColor: "rgba(34, 197, 94, 0.55)",
          borderColor: "#22c55e",
          borderWidth: 1,
          borderRadius: 5,
        },
        {
          type: "bar",
          label: "Gastos",
          data: expenses,
          backgroundColor: "rgba(239, 68, 68, 0.45)",
          borderColor: "#ef4444",
          borderWidth: 1,
          borderRadius: 5,
        },
        {
          type: "line",
          label: "Saldo acumulado",
          data: cumulative,
          yAxisID: "y1",
          borderColor: "#60a5fa",
          backgroundColor: "rgba(96, 165, 250, 0.2)",
          pointBackgroundColor: "#60a5fa",
          pointRadius: 2,
          pointHoverRadius: 4,
          borderWidth: 2,
          tension: 0.28,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          labels: {
            color: getComputedStyle(document.body).getPropertyValue("--text") || "#e2e8f0",
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${ctx.dataset.label}: ${formatBRL(ctx.raw)}`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: "rgba(255,255,255,0.04)" },
          ticks: { color: "#94a3b8" },
        },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "#94a3b8",
            callback: (v) => formatBRL(v),
          },
        },
        y1: {
          position: "right",
          grid: { drawOnChartArea: false },
          ticks: {
            color: "#93c5fd",
            callback: (v) => formatBRL(v),
          },
        },
      },
    },
  });
}

function renderCashflow(entries) {
  const el = byId("finCashflowContent");
  if (!el) return;
  renderCashflowChart(FIN.cashflowSummary);
  const rows = Array.isArray(entries) ? entries : [];
    _syncDescriptionDatalist();
  if (!rows.length) {
    el.innerHTML = renderEmptyState(
      "Nenhum lançamento no Gestor Financeiro para este mês.",
      "",
      [
        { label: "Adicionar lançamento", action: "addCashflow" },
        { label: "Importar extrato", action: "openCashflowImport" },
        { label: "Configurar orçamento", action: "openCashflowBudget" },
      ],
    );
    return;
  }

  const statusMeta = (entry) => {
    const raw = String(entry.payment_status || "").trim().toLowerCase();
    if (raw === "paid") {
      return {
        label: "PAGO",
        badge: "fin-badge-buy",
        nextStatus: "pending",
        actionLabel: "Marcar pendente",
      };
    }
    return {
      label: "PENDENTE",
      badge: "fin-badge-sell",
      nextStatus: "paid",
      actionLabel: "Marcar pago",
    };
  };

  const html = rows.map((entry) => {
    const type = String(entry.entry_type || "");
    const isIncome = type === "income";
    const badge = isIncome ? "fin-badge-buy" : "fin-badge-sell";
    const label = isIncome ? "GANHO" : "GASTO";
    const amountCls = isIncome ? "fin-up" : "fin-down";
    const status = statusMeta(entry);
    return `
      <tr>
        <td>${escapeHtml(String(entry.entry_date || "").slice(0, 10))}</td>
        <td><span class="fin-badge ${badge}">${label}</span></td>
        <td><span class="fin-badge ${status.badge}">${status.label}</span></td>
        <td>${escapeHtml(entry.category || "—")}</td>
        <td>${escapeHtml(entry.subcategory || "—")}</td>
        <td>${escapeHtml(entry.cost_center || "—")}</td>
        <td>${escapeHtml(Array.isArray(entry.tags) ? entry.tags.join(", ") : "")}</td>
        <td>${escapeHtml(entry.description || "—")}${entry.installment_index && entry.installment_total ? ` <span class="fin-badge" style="font-size:.7em;opacity:.75;vertical-align:middle;">${entry.installment_index}/${entry.installment_total}</span>` : ""}</td>
        <td class="text-right mono ${amountCls}">${formatBRL(entry.amount || 0)}</td>
        <td>${escapeHtml(entry.notes || "")}</td>
        <td class="text-center">
          <button class="fin-del-btn" data-action="toggleCashflowStatus" data-id="${entry.id}" data-status="${status.nextStatus}" title="${status.actionLabel}">✓</button>
          <button class="fin-del-btn" data-action="openCashflowAttachmentModal" data-id="${entry.id}" title="Anexos">📎</button>
          <button class="fin-del-btn" data-action="openEditCashflowModal" data-id="${entry.id}" title="Editar">✎</button>
          <button class="fin-del-btn" data-action="openSplitCashflowModal" data-id="${entry.id}" title="Dividir em partes">↕</button>
          <button class="fin-del-btn" data-action="deleteCashflowEntry" data-id="${entry.id}" title="Excluir">✕</button>
        </td>
      </tr>
    `;
  }).join("");

  el.innerHTML = `
    <div class="fin-table-wrap">
      <table class="fin-table">
        <thead>
          <tr>
            <th>Data</th>
            <th>Tipo</th>
            <th>Status</th>
            <th>Categoria</th>
            <th>Subcategoria</th>
            <th>Centro de custo</th>
            <th>Tags</th>
            <th>Descrição</th>
            <th class="text-right">Valor</th>
            <th>Notas</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${html}</tbody>
      </table>
    </div>
  `;
}

function openBudgetMethodologyModal() {
  const month = getSelectedCashflowMonth();
  const methods = [
    { value: "50_30_20", label: "50/30/20 — Necessidades / Desejos / Poupança", hint: "50% moradia+alimentação+saúde, 30% lazer+compras, 20% investimentos" },
    { value: "envelope", label: "Envelopes — Alocação por categorias fixas", hint: "Distribua valores fixos entre envelopes até esgotar a renda" },
    { value: "zero_based", label: "Base Zero — Cada real é alocado", hint: "Receita − todas as despesas e investimentos = R$ 0" },
  ];
  const opts = methods.map((m, i) => `
    <label class="fin-method-option" style="display:flex;align-items:flex-start;gap:10px;padding:10px;border:1px solid rgba(255,255,255,.12);border-radius:6px;cursor:pointer;margin-bottom:6px;">
      <input type="radio" name="budgetMethod" value="${m.value}" ${i === 0 ? "checked" : ""} style="margin-top:3px;flex-shrink:0;" />
      <span>
        <strong>${escapeHtml(m.label)}</strong>
        <small style="display:block;opacity:.65;margin-top:2px;">${escapeHtml(m.hint)}</small>
      </span>
    </label>
  `).join("");

  openFinModal("📐 Metodologia de Orçamento", `
    <div style="margin-bottom:10px;opacity:.75;font-size:.85em;">
      Escolha uma metodologia e informe sua renda líquida mensal para gerar sugestões de limites por categoria.
    </div>
    <div class="fin-form-group">
      <label>Mês alvo</label>
      <input id="fmMethMonth" type="month" value="${escapeHtml(month)}" required />
    </div>
    <div class="fin-form-group">
      <label>Renda líquida mensal (R$)</label>
      <input id="fmMethIncome" type="number" min="0.01" step="0.01" placeholder="Ex.: 5000" required />
    </div>
    <div class="fin-form-group">
      <label>Metodologia</label>
      <div id="fmMethOptions">${opts}</div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">
      <button id="btnMethPreview" class="btn-text" type="button" style="padding:6px 14px;">👁 Pré-visualizar</button>
      <button id="btnMethApply" class="fin-form-submit" type="button" style="flex:1;">✅ Aplicar ao orçamento</button>
    </div>
    <div id="fmMethResult" style="margin-top:14px;"></div>
  `);

  const doPreviewOrApply = async (apply) => {
    const income = Number(byId("fmMethIncome")?.value || 0);
    const methMonth = String(byId("fmMethMonth")?.value || "").trim();
    const method = document.querySelector("input[name=budgetMethod]:checked")?.value || "50_30_20";
    if (!income || income <= 0) { showToast("Informe a renda mensal"); return; }
    try {
      const resp = await finFetch("/api/finance/cashflow/budget/template", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ method, income, month: methMonth, apply }),
      });
      const data = await resp.json();
      if (!resp.ok) { showToast(data.error || "Erro"); return; }
      const resultEl = byId("fmMethResult");
      if (!resultEl) return;

      const groupsHtml = Object.entries(data.groups || {}).map(([g, v]) =>
        `<span style="margin-right:12px;"><strong>${escapeHtml(g)}</strong>: ${formatBRL(v)}</span>`
      ).join("");

      const budgetRows = Object.entries(data.budget || {}).map(([cat, v]) =>
        `<tr><td>${escapeHtml(cat)}</td><td class="text-right mono">${formatBRL(v)}</td></tr>`
      ).join("");

      resultEl.innerHTML = `
        <div style="padding:8px;background:rgba(255,255,255,.04);border-radius:6px;">
          <div style="font-size:.82em;opacity:.7;margin-bottom:6px;">${escapeHtml(data.description || "")}</div>
          <div style="margin-bottom:8px;font-size:.85em;">${groupsHtml}</div>
          <div class="fin-table-wrap" style="max-height:220px;overflow-y:auto;">
            <table class="fin-table">
              <thead><tr><th>Categoria</th><th class="text-right">Limite sugerido</th></tr></thead>
              <tbody>${budgetRows}</tbody>
            </table>
          </div>
          ${apply ? '<div class="fin-up" style="margin-top:8px;font-size:.85em;">✓ Orçamento aplicado com sucesso.</div>' : ""}
        </div>
      `;
      if (apply) {
        showToast("Metodologia de orçamento aplicada!", "success");
        await refreshByDomains(["cashflow"]);
      }
    } catch {
      showToast("Erro de rede");
    }
  };

  byId("btnMethPreview")?.addEventListener("click", () => doPreviewOrApply(false));
  byId("btnMethApply")?.addEventListener("click", () => doPreviewOrApply(true));
}

function openAddCashflowModal(prefill = {}) {
  const today = new Date().toISOString().slice(0, 10);
  const _pdate = String(prefill.entry_date || today);
  const _pamount = String(prefill.amount || "");
  const _pdesc = String(prefill.description || "");
  const _pcat = String(prefill.category || "");
  const _ptype = String(prefill.entry_type || "expense");
  const _pcard = Number(prefill.credit_card_id || 0);
  const _paccount = Number(prefill.account_id || 0);
  const _accountOptions = ['<option value="">Sem conta</option>']
    .concat((Array.isArray(FIN.accounts) ? FIN.accounts : []).map((a) => {
      const aid = Number(a.id || 0);
      const sel = aid === _paccount ? " selected" : "";
      const label = `${a.name || `Conta ${aid}`}${a.account_type ? ` (${a.account_type})` : ""}`;
      return `<option value="${aid}"${sel}>${escapeHtml(label)}</option>`;
    }))
    .join("");
  const _cardOptions = ['<option value="">Sem cartão</option>']
    .concat((Array.isArray(FIN.creditCards) ? FIN.creditCards : []).map((c) => {
      const cid = Number(c.id || 0);
      const sel = cid === _pcard ? " selected" : "";
      return `<option value="${cid}"${sel}>${escapeHtml(c.name || `Cartão ${cid}`)}</option>`;
    }))
    .join("");
  openFinModal("Novo Lançamento (Gestor Financeiro)", `
    <form data-form-action="submitAddCashflow">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmCfType">
            <option value="income" ${_ptype === "income" ? "selected" : ""}>Ganho</option>
            <option value="expense" ${_ptype === "expense" ? "selected" : ""}>Gasto</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Data</label>
          <input id="fmCfDate" type="date" value="${escapeHtml(_pdate)}" required />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Status</label>
          <select id="fmCfStatus">
            <option value="pending">Pendente</option>
            <option value="paid">Pago</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Data da baixa</label>
          <input id="fmCfSettledAt" type="date" value="${today}" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Valor (R$)</label>
          <input id="fmCfAmount" type="number" min="0.01" step="0.01" value="${escapeHtml(_pamount)}" required />
        </div>
        <div class="fin-form-group">
          <label>Categoria</label>
          <input id="fmCfCategory" list="finCfCategoriesDatalist" placeholder="Ex.: Salário, Moradia, Alimentação" value="${escapeHtml(_pcat)}" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Subcategoria</label>
          <input id="fmCfSubcategory" list="finCfSubcategoriesDatalist" placeholder="Ex.: Condomínio" />
        </div>
        <div class="fin-form-group">
          <label>Centro de custo</label>
          <input id="fmCfCostCenter" placeholder="Ex.: Casa" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Descrição</label>
        <input id="fmCfDescription" list="finCfDescriptionsDatalist" placeholder="Resumo do lançamento" value="${escapeHtml(_pdesc)}" required />
      </div>
      <div class="fin-form-group">
        <label>Cartão (opcional)</label>
        <select id="fmCfCreditCard">${_cardOptions}</select>
      </div>
      <div class="fin-form-group">
        <label>Conta (opcional)</label>
        <select id="fmCfAccount">${_accountOptions}</select>
      </div>
      <div class="fin-form-group">
        <label>Tags</label>
        <input id="fmCfTags" placeholder="Ex.: fixo, essencial" />
      </div>
      <div class="fin-form-group">
        <label>Notas</label>
        <textarea id="fmCfNotes" rows="2" placeholder="Opcional"></textarea>
      </div>
      <button type="submit" class="fin-form-submit">💾 Salvar Lançamento</button>
    </form>
  `);

  if (!Array.isArray(FIN.creditCards) || !FIN.creditCards.length) {
    finFetch("/api/finance/credit-cards")
      .then((resp) => resp.ok ? resp.json() : [])
      .then((cards) => {
        FIN.creditCards = Array.isArray(cards) ? cards : [];
        const sel = byId("fmCfCreditCard");
        if (!sel) return;
        const current = Number(prefill.credit_card_id || 0);
        sel.innerHTML = ['<option value="">Sem cartão</option>']
          .concat(FIN.creditCards.map((c) => {
            const cid = Number(c.id || 0);
            const mark = cid === current ? " selected" : "";
            return `<option value="${cid}"${mark}>${escapeHtml(c.name || `Cartão ${cid}`)}</option>`;
          }))
          .join("");
      })
      .catch(() => { /* ignore */ });
  }

  if (!Array.isArray(FIN.accounts) || !FIN.accounts.length) {
    finFetch("/api/finance/accounts")
      .then((resp) => resp.ok ? resp.json() : [])
      .then((accounts) => {
        FIN.accounts = Array.isArray(accounts) ? accounts : [];
        const sel = byId("fmCfAccount");
        if (!sel) return;
        const current = Number(prefill.account_id || 0);
        sel.innerHTML = ['<option value="">Sem conta</option>']
          .concat(FIN.accounts.map((a) => {
            const aid = Number(a.id || 0);
            const mark = aid === current ? " selected" : "";
            const label = `${a.name || `Conta ${aid}`}${a.account_type ? ` (${a.account_type})` : ""}`;
            return `<option value="${aid}"${mark}>${escapeHtml(label)}</option>`;
          }))
          .join("");
      })
      .catch(() => { /* ignore */ });
  }
}

function openCashflowBudgetModal() {
  const month = getSelectedCashflowMonth();
  const analytics = FIN.cashflowAnalytics || {};
  const expenseCategories = Array.isArray(analytics?.categories?.expense)
    ? analytics.categories.expense
    : [];

  const existing = FIN.cashflowBudget || {};
  const mergedCats = [...new Set([
    ...Object.keys(existing),
    ...expenseCategories.map((row) => String(row.category || "").trim()).filter(Boolean),
  ])].sort((a, b) => a.localeCompare(b));

  const rows = mergedCats.map((cat, idx) => {
    const spent = Number(expenseCategories.find((row) => row.category === cat)?.amount || 0);
    const limit = Number(existing[cat] || 0);
    return `
      <div class="fin-form-row" data-budget-row="${idx}">
        <div class="fin-form-group">
          <label>Categoria</label>
          <input data-budget-cat value="${escapeHtml(cat)}" />
        </div>
        <div class="fin-form-group">
          <label>Limite mensal (R$)</label>
          <input data-budget-limit type="number" step="0.01" min="0" value="${Number.isFinite(limit) ? limit : 0}" />
          <small style="display:block;opacity:0.75;margin-top:3px;">Gasto atual: ${formatBRL(spent)}</small>
        </div>
      </div>
    `;
  }).join("");

  openFinModal("Orçamento Mensal (Gestor Financeiro)", `
    <form data-form-action="submitCashflowBudget">
      <div class="fin-form-group">
        <label>Mês</label>
        <input id="fmBudgetMonth" type="month" value="${escapeHtml(month)}" required />
      </div>
      <div id="fmBudgetRows">${rows || ""}</div>
      <button id="btnBudgetAddRow" class="btn-text" type="button">＋ Adicionar categoria</button>
      <button type="submit" class="fin-form-submit">💾 Salvar Orçamento</button>
    </form>
  `);

  const addRowBtn = byId("btnBudgetAddRow");
  const rowsHost = byId("fmBudgetRows");
  if (addRowBtn && rowsHost) {
    addRowBtn.addEventListener("click", () => {
      const idx = rowsHost.querySelectorAll("[data-budget-row]").length;
      const row = document.createElement("div");
      row.className = "fin-form-row";
      row.setAttribute("data-budget-row", String(idx));
      row.innerHTML = `
        <div class="fin-form-group">
          <label>Categoria</label>
          <input data-budget-cat placeholder="Ex.: Moradia" />
        </div>
        <div class="fin-form-group">
          <label>Limite mensal (R$)</label>
          <input data-budget-limit type="number" step="0.01" min="0" value="0" />
        </div>
      `;
      rowsHost.appendChild(row);
    });
  }
}

async function openCashflowRecurringModal() {
  let templates = [];
  try {
    const resp = await finFetch("/api/finance/cashflow/recurring?active_only=0");
    if (resp.ok) templates = await resp.json();
  } catch { /* show empty */ }

  const freqLabel = { monthly: "Mensal", quarterly: "Trimestral", yearly: "Anual" };
  const dayRuleLabel = { exact: "Dia exato", last_day: "Último dia do mês", first_weekday: "1º dia útil", last_weekday: "Último dia útil" };

  const rows = (Array.isArray(templates) ? templates : []).map((t) => `
    <tr>
      <td>${t.active ? "✅" : "⏸"}</td>
      <td>${escapeHtml(t.entry_type === "income" ? "Ganho" : "Gasto")}</td>
      <td>${escapeHtml(t.description || "—")}</td>
      <td>${escapeHtml(t.category || "—")}</td>
      <td class="text-right mono">${formatBRL(t.amount || 0)}</td>
      <td>${escapeHtml(freqLabel[t.frequency] || t.frequency || "Mensal")}</td>
      <td>${escapeHtml(dayRuleLabel[t.day_rule] || "Dia exato")}</td>
      <td class="text-center">
        <button class="fin-del-btn" data-action="editCashflowRecurring" data-id="${t.id}" title="Editar">✎</button>
        <button class="fin-del-btn" data-action="deleteCashflowRecurring" data-id="${t.id}" title="Excluir">✕</button>
      </td>
    </tr>
  `).join("");

  openFinModal("🔁 Lançamentos Recorrentes (Gestor Financeiro)", `
    <div style="margin-bottom:10px;display:flex;gap:8px;">
      <button id="btnAddRecurring" class="fin-form-submit" type="button" style="flex:0 0 auto;">＋ Novo modelo</button>
      <span style="opacity:.65;font-size:.82em;align-self:center;">Modelos são gerados automaticamente ao usar "Virada de mês".</span>
    </div>
    ${rows.length ? `
      <div class="fin-table-wrap" style="max-height:320px;overflow:auto;">
        <table class="fin-table">
          <thead><tr><th>Ativo</th><th>Tipo</th><th>Descrição</th><th>Categoria</th><th class="text-right">Valor</th><th>Freq.</th><th>Regra do dia</th><th></th></tr></thead>
          <tbody id="recurringTableBody">${rows}</tbody>
        </table>
      </div>
    ` : '<p class="fin-empty">Nenhum modelo recorrente cadastrado.</p>'}
    <div id="recurringFormArea" style="margin-top:16px;"></div>
  `);

  const showRecurringForm = (existing = null) => {
    const area = byId("recurringFormArea");
    if (!area) return;
    const today = new Date().toISOString().slice(0, 10);
    const t = existing || {};
    area.innerHTML = `
      <hr style="border-color:rgba(255,255,255,.1);margin:8px 0;" />
      <h4 style="margin-bottom:10px;">${existing ? "Editar modelo" : "Novo modelo recorrente"}</h4>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmRcType">
            <option value="expense" ${t.entry_type === "expense" || !t.entry_type ? "selected" : ""}>Gasto</option>
            <option value="income" ${t.entry_type === "income" ? "selected" : ""}>Ganho</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Valor (R$)</label>
          <input id="fmRcAmount" type="number" min="0.01" step="0.01" value="${t.amount || ""}" required />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Categoria</label>
          <input id="fmRcCategory" value="${escapeHtml(t.category || "")}" placeholder="Ex.: Moradia" />
        </div>
        <div class="fin-form-group">
          <label>Descrição</label>
          <input id="fmRcDescription" value="${escapeHtml(t.description || "")}" placeholder="Ex.: Aluguel" required />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Frequência</label>
          <select id="fmRcFrequency">
            <option value="monthly" ${(t.frequency || "monthly") === "monthly" ? "selected" : ""}>Mensal</option>
            <option value="quarterly" ${t.frequency === "quarterly" ? "selected" : ""}>Trimestral</option>
            <option value="yearly" ${t.frequency === "yearly" ? "selected" : ""}>Anual</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Regra do dia</label>
          <select id="fmRcDayRule">
            <option value="exact" ${(t.day_rule || "exact") === "exact" ? "selected" : ""}>Dia exato do mês</option>
            <option value="last_day" ${t.day_rule === "last_day" ? "selected" : ""}>Último dia do mês</option>
            <option value="first_weekday" ${t.day_rule === "first_weekday" ? "selected" : ""}>1º dia útil</option>
            <option value="last_weekday" ${t.day_rule === "last_weekday" ? "selected" : ""}>Último dia útil</option>
          </select>
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Dia do mês (para "dia exato")</label>
          <input id="fmRcDayOfMonth" type="number" min="1" max="31" value="${t.day_of_month || 1}" />
        </div>
        <div class="fin-form-group">
          <label>Ativo</label>
          <select id="fmRcActive">
            <option value="1" ${t.active !== false ? "selected" : ""}>Sim</option>
            <option value="0" ${t.active === false ? "selected" : ""}>Não</option>
          </select>
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Data início</label>
          <input id="fmRcStartDate" type="date" value="${escapeHtml(String(t.start_date || "").slice(0, 10))}" />
        </div>
        <div class="fin-form-group">
          <label>Data fim</label>
          <input id="fmRcEndDate" type="date" value="${escapeHtml(String(t.end_date || "").slice(0, 10))}" />
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-top:8px;">
        <button id="btnSaveRecurring" class="fin-form-submit" type="button" data-id="${existing?.id || ""}">💾 Salvar modelo</button>
        <button id="btnCancelRecurring" class="btn-text" type="button">Cancelar</button>
      </div>
    `;
    byId("btnCancelRecurring")?.addEventListener("click", () => { area.innerHTML = ""; });
    byId("btnSaveRecurring")?.addEventListener("click", async () => {
      const id = byId("btnSaveRecurring")?.dataset?.id || "";
      const payload = {
        entry_type: String(byId("fmRcType")?.value || "expense"),
        amount: Number(byId("fmRcAmount")?.value || 0),
        category: String(byId("fmRcCategory")?.value || "").trim(),
        description: String(byId("fmRcDescription")?.value || "").trim(),
        frequency: String(byId("fmRcFrequency")?.value || "monthly"),
        day_rule: String(byId("fmRcDayRule")?.value || "exact"),
        day_of_month: Number(byId("fmRcDayOfMonth")?.value || 1),
        active: byId("fmRcActive")?.value === "1",
        start_date: String(byId("fmRcStartDate")?.value || "").trim() || null,
        end_date: String(byId("fmRcEndDate")?.value || "").trim() || null,
      };
      if (!payload.amount || payload.amount <= 0) { showToast("Informe o valor"); return; }
      if (!payload.description) { showToast("Informe a descrição"); return; }
      try {
        const url = id ? `/api/finance/cashflow/recurring/${id}` : "/api/finance/cashflow/recurring";
        const method = id ? "PUT" : "POST";
        const resp = await finFetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json();
        if (!resp.ok) { showToast(data.error || "Erro ao salvar"); return; }
        showToast(id ? "Modelo atualizado!" : "Modelo criado!", "success");
        await openCashflowRecurringModal();
      } catch { showToast("Erro de rede"); }
    });
  };

  byId("btnAddRecurring")?.addEventListener("click", () => showRecurringForm(null));

  const modal = document.querySelector("#finModalBody");
  if (modal) {
    modal.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-action]");
      if (!btn) return;
      const id = Number(btn.dataset.id || 0);
      if (btn.dataset.action === "editCashflowRecurring") {
        const tpl = (Array.isArray(templates) ? templates : []).find((t) => Number(t.id) === id);
        if (tpl) showRecurringForm(tpl);
      } else if (btn.dataset.action === "deleteCashflowRecurring") {
        if (!confirm("Excluir este modelo recorrente?")) return;
        try {
          const resp = await finFetch(`/api/finance/cashflow/recurring/${id}`, { method: "DELETE" });
          if (resp.ok) { showToast("Modelo excluído", "success"); await openCashflowRecurringModal(); }
        } catch { showToast("Erro de rede"); }
      }
    }, { once: true });
  }
}

function openCashflowRolloverModal() {
  const targetMonth = getSelectedCashflowMonth();
  const sourceMonth = prevMonthKey(targetMonth);
  openFinModal("Virada de Mês (Gestor Financeiro)", `
    <form data-form-action="submitCashflowRollover">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Copiar de (mês origem)</label>
          <input id="fmCfRollSourceMonth" type="month" value="${escapeHtml(sourceMonth)}" required />
        </div>
        <div class="fin-form-group">
          <label>Para (mês destino)</label>
          <input id="fmCfRollTargetMonth" type="month" value="${escapeHtml(targetMonth)}" required />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Tipo de lançamento</label>
        <select id="fmCfRollType">
          <option value="all">Ganhos e gastos</option>
          <option value="expense">Somente gastos</option>
          <option value="income">Somente ganhos</option>
        </select>
      </div>
      <div class="fin-inline-info">Registros idênticos já existentes no mês destino serão ignorados automaticamente.</div>
      <button type="submit" class="fin-form-submit">↻ Executar virada de mês</button>
    </form>
  `);
}

async function submitAddCashflow(e) {
  e.preventDefault();
  const paymentStatus = String(byId("fmCfStatus")?.value || "pending").trim();
  const settledAt = String(byId("fmCfSettledAt")?.value || "").trim();
  const body = {
    entry_type: String(byId("fmCfType")?.value || "expense"),
    amount: Number(byId("fmCfAmount")?.value || 0),
    category: String(byId("fmCfCategory")?.value || "").trim(),
    subcategory: String(byId("fmCfSubcategory")?.value || "").trim(),
    cost_center: String(byId("fmCfCostCenter")?.value || "").trim(),
    description: String(byId("fmCfDescription")?.value || "").trim(),
    entry_date: String(byId("fmCfDate")?.value || "").trim(),
    notes: String(byId("fmCfNotes")?.value || "").trim(),
    account_id: Number(byId("fmCfAccount")?.value) || null,
    credit_card_id: Number(byId("fmCfCreditCard")?.value) || null,
    tags: parseTagsInput(byId("fmCfTags")?.value || ""),
    payment_status: paymentStatus,
    settled_at: paymentStatus === "paid" ? settledAt : null,
  };

  // Personal spending guard: warn if category budget would be exceeded
  if (body.entry_type === "expense" && body.category && body.amount > 0) {
    const month = body.entry_date ? body.entry_date.slice(0, 7) : getSelectedCashflowMonth();
    try {
      const chk = await fetch(
        `/api/finance/cashflow/budget/check?category=${encodeURIComponent(body.category)}&amount=${body.amount}&month=${encodeURIComponent(month)}`
      );
      if (chk.ok) {
        const chkData = await chk.json();
        if (chkData.has_budget && chkData.over_budget) {
          const msg = `⚠️ Atenção: este gasto de ${formatBRL(body.amount)} levaria "${body.category}" a ${formatBRL(chkData.would_be_spent)} — acima do limite de ${formatBRL(chkData.limit)} (${chkData.usage_pct.toFixed(0)}% do orçamento). Deseja continuar mesmo assim?`;
          if (!confirm(msg)) return;
        }
      }
    } catch { /* non-blocking */ }
  }

  // Offline queue if no connection
  if (!navigator.onLine && typeof queueOfflineEntry === "function") {
    await queueOfflineEntry(body);
    if (typeof updateOfflineBadge === "function") updateOfflineBadge();
    closeFinModal();
    showToast("Sem conexão — lançamento salvo localmente e sincronizará quando voltar online.");
    return;
  }

  try {
    const resp = await finFetch("/api/finance/cashflow", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const data = await resp.json();
      showToast(data.error || "Erro ao salvar lançamento");
      return;
    }
    closeFinModal();
    await refreshByDomains(["cashflow"]);
    showToast("Lançamento salvo!", "success");
  } catch {
    showToast("Erro de rede");
  }
}

function openReceiptOCRModal() {
  openFinModal("📷 Analisar Comprovante (OCR)", `
    <div style="margin-bottom:8px;opacity:.75;font-size:.85em;">
      Envie uma foto de comprovante ou nota fiscal. O sistema extrairá data, valor e descrição automaticamente.
      Se OCR não estiver disponível, você pode colar o texto manualmente.
    </div>
    <div style="display:flex;gap:6px;margin-bottom:6px;">
      <button id="btnOcrTabScan"    type="button" class="fin-tab-btn fin-tab-active"  style="flex:1;">📷 Digitalizar</button>
      <button id="btnOcrTabHistory" type="button" class="fin-tab-btn"                 style="flex:1;">📋 Histórico</button>
    </div>
    <div id="ocrTabScan">
      <div class="fin-form-group">
        <label>Imagem do comprovante (JPG, PNG, PDF até 5 MB)</label>
        <div id="fmOcrDropZone" style="border:2px dashed #aaa;border-radius:8px;padding:14px 10px;text-align:center;cursor:pointer;transition:background .2s;margin-bottom:6px;">
          <span id="fmOcrDropLabel" style="font-size:.85em;opacity:.7;">Arraste a imagem aqui ou clique para selecionar</span>
        </div>
        <input id="fmOcrFile" type="file" accept="image/*,.pdf" capture="environment" style="display:none;" />
        <button type="button" id="btnOcrCamera" style="font-size:.8em;padding:3px 10px;margin-top:2px;">📸 Usar Câmera</button>
      </div>
      <div id="fmOcrPreview" style="display:none;margin:6px 0 10px;text-align:center;">
        <div style="display:flex;align-items:center;gap:8px;justify-content:center;margin-bottom:4px;">
          <button id="btnRotLeft"  type="button" style="padding:2px 8px;font-size:1.1em;" title="Girar 90° esquerda">↺</button>
          <img id="fmOcrPreviewImg" style="max-height:140px;max-width:100%;border-radius:6px;border:1px solid #ccc;" alt="preview" />
          <button id="btnRotRight" type="button" style="padding:2px 8px;font-size:1.1em;" title="Girar 90° direita">↻</button>
        </div>
        <span id="fmOcrPreviewLabel" style="font-size:.75em;opacity:.6;"></span>
      </div>
      <div class="fin-form-group">
        <label>Texto manual (fallback opcional)</label>
        <textarea id="fmOcrManualText" rows="3" placeholder="Cole aqui o texto do comprovante caso o OCR não esteja disponível."></textarea>
      </div>
      <button id="btnDoOcr" class="fin-form-submit" type="button">🔍 Analisar</button>
      <div id="fmOcrResult" style="margin-top:12px"></div>
    </div>
    <div id="ocrTabHistory" style="display:none;">
      <div id="fmOcrHistoryContent" style="font-size:.85em;">Carregando…</div>
    </div>
  `);

  // ── Tab switching ──────────────────────────────────────────────────────────
  byId("btnOcrTabScan")?.addEventListener("click", () => {
    byId("ocrTabScan").style.display = "";
    byId("ocrTabHistory").style.display = "none";
    byId("btnOcrTabScan").classList.add("fin-tab-active");
    byId("btnOcrTabHistory").classList.remove("fin-tab-active");
  });
  byId("btnOcrTabHistory")?.addEventListener("click", () => {
    byId("ocrTabScan").style.display = "none";
    byId("ocrTabHistory").style.display = "";
    byId("btnOcrTabScan").classList.remove("fin-tab-active");
    byId("btnOcrTabHistory").classList.add("fin-tab-active");
    _loadOcrHistory();
  });

  // ── History tab loader ─────────────────────────────────────────────────────
  async function _loadOcrHistory() {
    const container = byId("fmOcrHistoryContent");
    if (!container) return;
    container.textContent = "Carregando…";
    try {
      const resp = await finFetch("/api/finance/cashflow/ocr/history");
      const rows = await resp.json();
      if (!Array.isArray(rows) || rows.length === 0) {
        container.innerHTML = "<em style='opacity:.6'>Nenhum comprovante analisado ainda.</em>";
        return;
      }
      container.innerHTML = `
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="opacity:.6;font-size:.8em;">
            <th style="text-align:left;padding:3px 4px">Data</th>
            <th style="text-align:left;padding:3px 4px">Estabelecimento</th>
            <th style="text-align:right;padding:3px 4px">Valor</th>
            <th style="text-align:left;padding:3px 4px">Tipo</th>
            <th style="text-align:right;padding:3px 4px">Conf.</th>
          </tr></thead>
          <tbody>${rows.map(r => `
            <tr class="fin-history-row" style="cursor:pointer;border-top:1px solid #eee;" data-hist='${JSON.stringify({date:r.entry_date||r.date,amount:r.amount,merchant:r.merchant,category:r.category,entry_type:r.entry_type})}'>
              <td style="padding:3px 4px;font-size:.82em;">${escapeHtml(String(r.entry_date||r.date||"—"))}</td>
              <td style="padding:3px 4px;font-size:.82em;">${escapeHtml(String(r.merchant||"—"))}</td>
              <td style="text-align:right;padding:3px 4px;font-size:.82em;">${r.amount!=null?formatBRL(r.amount):"—"}</td>
              <td style="padding:3px 4px;font-size:.82em;">${escapeHtml(String(r.receipt_type||"—"))}</td>
              <td style="text-align:right;padding:3px 4px;font-size:.82em;">${r.confidence!=null?Math.round(Number(r.confidence)*100)+"%":"—"}</td>
            </tr>`).join("")}
          </tbody>
        </table>
        <div style="font-size:.75em;opacity:.55;margin-top:4px;">Clique em uma linha para pré-preencher</div>`;
      // Row click: switch to scan tab and prefill fields (if result already shown)
      container.querySelectorAll(".fin-history-row").forEach(row => {
        row.addEventListener("click", () => {
          try {
            const d = JSON.parse(row.dataset.hist || "{}");
            byId("btnOcrTabScan").click();
            // Pre-populate visible form fields if result section is shown
            if (byId("fmOcrDate")) byId("fmOcrDate").value = d.date || "";
            if (byId("fmOcrAmount")) byId("fmOcrAmount").value = d.amount != null ? d.amount : "";
            if (byId("fmOcrMerchant")) byId("fmOcrMerchant").value = d.merchant || "";
            if (byId("fmOcrCat")) byId("fmOcrCat").value = d.category || "";
            if (byId("fmOcrType")) byId("fmOcrType").value = d.entry_type || "expense";
          } catch (_) {}
        });
      });
    } catch (_) {
      if (container) container.innerHTML = "<em style='opacity:.6'>Erro ao carregar histórico.</em>";
    }
  }

  // ── Image preview + rotation ────────────────────────────────────────────────
  let _ocrRotation = 0;
  let _ocrOrigFile = null;

  function _renderPreview(file) {
    if (!file || !file.type.startsWith("image/")) return;
    _ocrOrigFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = byId("fmOcrPreviewImg");
      const preview = byId("fmOcrPreview");
      const label = byId("fmOcrPreviewLabel");
      if (!img || !preview) return;
      img.src = e.target.result;
      img.style.transform = `rotate(${_ocrRotation}deg)`;
      if (preview) preview.style.display = "";
      if (label) label.textContent = `${file.name} (${(file.size/1024).toFixed(0)} KB)`;
    };
    reader.readAsDataURL(file);
  }

  byId("fmOcrFile")?.addEventListener("change", (e) => {
    _ocrRotation = 0;
    const file = e.target.files?.[0];
    if (file) _renderPreview(file);
  });

  // Camera button: trigger file input (capture already set in HTML)
  byId("btnOcrCamera")?.addEventListener("click", () => byId("fmOcrFile")?.click());

  // Drop zone: open file picker on click
  byId("fmOcrDropZone")?.addEventListener("click", () => byId("fmOcrFile")?.click());

  // Drag-and-drop
  byId("fmOcrDropZone")?.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    byId("fmOcrDropZone").style.background = "var(--fin-bg2,#f0f4ff)";
  });
  byId("fmOcrDropZone")?.addEventListener("dragleave", () => {
    byId("fmOcrDropZone").style.background = "";
  });
  byId("fmOcrDropZone")?.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    byId("fmOcrDropZone").style.background = "";
    const file = e.dataTransfer?.files?.[0];
    if (!file) return;
    // Put it in the file input via DataTransfer so _runOcr can read it
    try {
      const dt = new DataTransfer();
      dt.items.add(file);
      byId("fmOcrFile").files = dt.files;
    } catch (_) {}
    _ocrRotation = 0;
    _renderPreview(file);
    const label = byId("fmOcrDropLabel");
    if (label) label.textContent = `${file.name} (${(file.size/1024).toFixed(0)} KB) ✓`;
  });

  byId("btnRotLeft")?.addEventListener("click", () => {
    _ocrRotation = (_ocrRotation - 90 + 360) % 360;
    const img = byId("fmOcrPreviewImg");
    if (img) img.style.transform = `rotate(${_ocrRotation}deg)`;
  });
  byId("btnRotRight")?.addEventListener("click", () => {
    _ocrRotation = (_ocrRotation + 90) % 360;
    const img = byId("fmOcrPreviewImg");
    if (img) img.style.transform = `rotate(${_ocrRotation}deg)`;
  });

  // ── Helper: apply canvas rotation to file before sending ──────────────────
  async function _getRotatedBlob(file, degrees) {
    if (!degrees || degrees % 360 === 0) return file;
    return new Promise((resolve) => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        URL.revokeObjectURL(url);
        const swap = degrees === 90 || degrees === 270;
        const canvas = document.createElement("canvas");
        canvas.width  = swap ? img.height : img.width;
        canvas.height = swap ? img.width  : img.height;
        const ctx = canvas.getContext("2d");
        ctx.translate(canvas.width / 2, canvas.height / 2);
        ctx.rotate((degrees * Math.PI) / 180);
        ctx.drawImage(img, -img.width / 2, -img.height / 2);
        canvas.toBlob((blob) => resolve(blob || file), file.type || "image/jpeg", 0.92);
      };
      img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }

  // ── Confidence badge ───────────────────────────────────────────────────────
  function _confBadge(fc, key) {
    const v = fc?.[key];
    if (v == null) return "";
    if (v >= 0.85) return " <span title='Alta confiança' style='color:var(--fin-up,green);font-size:.8em;'>✓</span>";
    if (v >= 0.5)  return " <span title='Confiança média — verifique' style='color:orange;font-size:.8em;'>⚠️</span>";
    return " <span title='Baixa confiança — preencha manualmente' style='color:var(--fin-down,red);font-size:.8em;'>⚠️</span>";
  }

  // ── Main analyze function (shared between first-run and force re-analyze) ──
  async function _runOcr(force = false) {
    const fileEl = byId("fmOcrFile");
    const manualText = String(byId("fmOcrManualText")?.value || "").trim();
    if (!fileEl?.files?.length && !manualText) {
      showToast("Selecione uma imagem ou preencha o texto manual");
      return;
    }
    const btnDoOcr = byId("btnDoOcr");
    if (btnDoOcr) { btnDoOcr.disabled = true; btnDoOcr.textContent = "Analisando…"; }
    const formData = new FormData();
    if (fileEl?.files?.length) {
      const rotated = await _getRotatedBlob(fileEl.files[0], _ocrRotation);
      formData.append("file", rotated, fileEl.files[0].name);
    }
    if (manualText) formData.append("manual_text", manualText);
    if (force) formData.append("force", "true");
    const _ocrAbort = new AbortController();
    const _ocrTimer = setTimeout(() => _ocrAbort.abort(), 45_000);
    try {
      const resp = await finFetch("/api/finance/cashflow/ocr", { method: "POST", body: formData, signal: _ocrAbort.signal });
      const data = await resp.json();
      const resultEl = byId("fmOcrResult");
      if (!resp.ok || !data.ok) {
        const msg = data.pytesseract_missing
          ? "pytesseract não instalado no servidor. " + (data.error || "")
          : (data.error || "Erro ao processar imagem.");
        if (resultEl) resultEl.innerHTML = `<span class="fin-down">${escapeHtml(msg)}</span>`;
        return;
      }
      const fc = data.field_confidence || {};
      const fromCache = data.from_cache ? ` <span style="opacity:.55;font-size:.75em;">(cache)</span>` : "";
      if (resultEl) resultEl.innerHTML = `
        <div style="margin-bottom:10px;font-size:.82em;opacity:.7;">
          📋 Tipo: <strong>${escapeHtml(data.receipt_type || "—")}</strong>
          ${data.payment_method ? ` &nbsp;·&nbsp; 💳 ${escapeHtml(data.payment_method)}` : ""}
          ${data.cnpj ? ` &nbsp;·&nbsp; CNPJ: <code>${escapeHtml(data.cnpj)}</code>` : ""}
          &nbsp;·&nbsp; Confiança: ${data.confidence != null ? `${Math.round(Number(data.confidence) * 100)}%` : "—"}${fromCache}
        </div>
        ${data.suggestion ? `<div style="font-size:.8em;background:var(--fin-bg2,#f5f5f5);padding:4px 8px;border-radius:4px;margin-bottom:8px;">💡 Histórico: <strong>${escapeHtml(data.suggestion.merchant||"")}</strong> → ${escapeHtml(data.suggestion.category||"")} (sugestão aplicada)</div>` : ""}
        ${data.duplicate_warning ? `<div style="font-size:.82em;background:#fff3cd;color:#856404;padding:5px 8px;border-radius:4px;margin-bottom:8px;border:1px solid #ffc107;">⚠️ Possível duplicata: ${data.duplicate_warning.count} lançamento(s) com mesmo valor e data já existem (IDs: ${data.duplicate_warning.ids.join(", ")}).</div>` : ""}
        ${data.budget_alert ? `<div style="font-size:.82em;background:${data.budget_alert.over?"#f8d7da":"#fff3cd"};color:${data.budget_alert.over?"#721c24":"#856404"};padding:5px 8px;border-radius:4px;margin-bottom:8px;border:1px solid ${data.budget_alert.over?"#f5c6cb":"#ffc107"};">${data.budget_alert.over?"🔴":"🟡"} Orçamento <strong>${escapeHtml(data.budget_alert.category)}</strong>: ${data.budget_alert.pct}% utilizado (${formatBRL(data.budget_alert.would_be)} / ${formatBRL(data.budget_alert.limit)})${data.budget_alert.over?" — LIMITE ULTRAPASSADO":""}</div>` : ""}
        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>Data${_confBadge(fc,"date")}</label>
            <input id="fmOcrDate" type="date" value="${escapeHtml(data.date || "")}" />
          </div>
          <div class="fin-form-group">
            <label>Valor (R$)${_confBadge(fc,"amount")}</label>
            <input id="fmOcrAmount" type="number" step="0.01" min="0" value="${data.amount != null ? data.amount : ""}" placeholder="0,00" />
          </div>
        </div>
        <div class="fin-form-row">
          <div class="fin-form-group" style="flex:2">
            <label>Estabelecimento${_confBadge(fc,"merchant")}</label>
            <input id="fmOcrMerchant" type="text" value="${escapeHtml(data.merchant || "")}" placeholder="Nome do estabelecimento" />
          </div>
        </div>
        <div class="fin-form-row">
          <div class="fin-form-group" style="flex:2">
            <label>Descrição</label>
            <input id="fmOcrDesc" type="text" value="${escapeHtml(data.description || "")}" placeholder="Descrição do lançamento" />
          </div>
          <div class="fin-form-group">
            <label>Categoria${_confBadge(fc,"category")}</label>
            <input id="fmOcrCat" type="text" value="${escapeHtml(data.category || "")}" placeholder="Categoria" />
          </div>
        </div>
        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>Tipo</label>
            <select id="fmOcrType">
              <option value="expense"${(data.entry_type||"expense")==="expense"?" selected":""}>Despesa</option>
              <option value="income"${data.entry_type==="income"?" selected":""}>Receita</option>
            </select>
          </div>
        </div>
        ${data.items && data.items.length ? `
        <details style="margin-top:8px;font-size:.82em;">
          <summary>🛒 Itens (${data.items.length})</summary>
          <table style="width:100%;border-collapse:collapse;margin-top:4px;">
            <thead><tr style="opacity:.6"><th style="text-align:left;padding:2px 4px">Qtd</th><th style="text-align:left;padding:2px 4px">Descrição</th><th style="text-align:right;padding:2px 4px">Total</th></tr></thead>
            <tbody>${data.items.map(it=>`<tr><td style="padding:2px 4px">${it.qty}</td><td style="padding:2px 4px">${escapeHtml(it.description)}</td><td style="text-align:right;padding:2px 4px">${formatBRL(it.total)}</td></tr>`).join("")}</tbody>
          </table>
        </details>` : ""}
        ${data.raw_text ? `<details style="margin-top:6px;font-size:.78em;"><summary>Texto bruto OCR</summary><pre style="white-space:pre-wrap;max-height:120px;overflow:auto;">${escapeHtml(data.raw_text)}</pre></details>` : ""}
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;">
          <button id="btnOcrPrefill" class="fin-form-submit" type="button" style="flex:1;">✚ Criar lançamento</button>
          <button id="btnOcrForce"   class="fin-form-submit" type="button" style="flex:0;background:var(--fin-bg2,#eee);color:inherit;">🔄 Reanalisar</button>
        </div>
      `;
      byId("btnOcrPrefill")?.addEventListener("click", () => {
        openAddCashflowModal({
          entry_date: String(byId("fmOcrDate")?.value || data.date || ""),
          amount: String(byId("fmOcrAmount")?.value ?? (data.amount != null ? data.amount : "")),
          description: String(byId("fmOcrDesc")?.value || data.description || ""),
          category: String(byId("fmOcrCat")?.value || data.category || ""),
          entry_type: String(byId("fmOcrType")?.value || data.entry_type || "expense"),
        });
      });
      byId("btnOcrForce")?.addEventListener("click", () => _runOcr(true));
    } catch (err) {
      if (err && err.name === "AbortError") {
        showToast("Análise demorou demais (>45s). Tente uma imagem menor ou use o texto manual.");
      } else {
        showToast("Erro de rede");
      }
    } finally {
      clearTimeout(_ocrTimer);
      if (btnDoOcr) { btnDoOcr.disabled = false; btnDoOcr.textContent = "🔍 Analisar"; }
    }
  }

  byId("btnDoOcr")?.addEventListener("click", () => _runOcr(false));
}

function openCashflowScenarioModal() {
  const month = getSelectedCashflowMonth();
  const analytics = FIN.cashflowAnalytics || {};
  const expenseCats = Array.isArray(analytics.categories?.expense)
    ? analytics.categories.expense
    : [];

  const rows = expenseCats.map((row, idx) => `
    <div class="fin-form-row" data-scenario-row="${idx}">
      <div class="fin-form-group" style="flex:2">
        <label>Categoria</label>
        <input data-sc-cat value="${escapeHtml(row.category || "")}" readonly />
      </div>
      <div class="fin-form-group">
        <label>Gasto atual</label>
        <input value="${formatBRL(row.amount || 0)}" readonly style="opacity:.6" />
      </div>
      <div class="fin-form-group">
        <label>Redução %</label>
        <input data-sc-pct type="number" min="0" max="100" step="1" value="0" placeholder="0" />
      </div>
    </div>
  `).join("");

  openFinModal("🔮 Simulador de Cenários (Gestor Financeiro)", `
    <div style="margin-bottom:8px;opacity:.75;font-size:.85em;">Simule o impacto de reduzir gastos em cada categoria.</div>
    <div class="fin-form-group">
      <label>Mês base</label>
      <input id="fmScMonth" type="month" value="${escapeHtml(month)}" required />
    </div>
    <div id="fmScRows">${rows || '<p class="fin-empty">Sem gastos no mês selecionado.</p>'}</div>
    <button id="btnRunScenario" class="fin-form-submit" type="button">▶ Simular</button>
    <div id="fmScResult" style="margin-top:12px"></div>
  `);

  byId("btnRunScenario")?.addEventListener("click", async () => {
    const scenarioMonth = String(byId("fmScMonth")?.value || "").trim();
    const scRows = document.querySelectorAll("[data-scenario-row]");
    const adjustments = [];
    scRows.forEach((r) => {
      const cat = r.querySelector("[data-sc-cat]")?.value?.trim();
      const pct = parseFloat(r.querySelector("[data-sc-pct]")?.value || "0");
      if (cat && pct > 0) adjustments.push({ category: cat, reduction_pct: pct });
    });
    try {
      const resp = await finFetch("/api/finance/cashflow/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ month: scenarioMonth, adjustments }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showToast(data.error || "Erro");
        return;
      }
      const resultEl = byId("fmScResult");
      if (resultEl) {
        const impact = data.impact || {};
        const sim = data.simulated || {};
        const cur = data.current || {};
        resultEl.innerHTML = `
          <div class="fin-cashflow-kpis" style="margin-top:0">
            <div class="fin-cashflow-kpi">
              <span>Gasto atual</span><strong class="fin-down">${formatBRL(cur.expense || 0)}</strong>
            </div>
            <div class="fin-cashflow-kpi">
              <span>Gasto simulado</span><strong class="fin-down">${formatBRL(sim.expense || 0)}</strong>
            </div>
            <div class="fin-cashflow-kpi">
              <span>Economia mensal</span><strong class="fin-up">${formatBRL(impact.monthly_saving || 0)}</strong>
            </div>
            <div class="fin-cashflow-kpi">
              <span>Economia anual</span><strong class="fin-up">${formatBRL(impact.yearly_saving || 0)}</strong>
            </div>
          </div>
        `;
      }
    } catch {
      showToast("Erro de rede");
    }
  });
}

function openCashflowImportModal() {
  const month = getSelectedCashflowMonth();
  openFinModal("📥 Importar Extratos (Gestor Financeiro)", `
    <div style="margin-bottom:8px;opacity:.75;font-size:.85em;">
      CSV: colunas <code>date, amount, type, category, description</code>.<br>
      OFX: extrato bancário padrão OFX/QFX.<br>
      Tamanho máximo: 2 MB.
    </div>
    <div class="fin-form-group">
      <label>Mês alvo</label>
      <input id="fmImportMonth" type="month" value="${escapeHtml(month)}" required />
    </div>
    <div class="fin-form-group">
      <label>Arquivo (.csv ou .ofx)</label>
      <input id="fmImportFile" type="file" accept=".csv,.ofx,.qfx" />
    </div>
    <label class="fin-form-group" style="display:flex;gap:8px;align-items:center;">
      <input id="fmImportMergeNotes" type="checkbox" />
      <span>Mesclar duplicatas anexando descrição em notas</span>
    </label>
    <label class="fin-form-group" style="display:flex;gap:8px;align-items:center;">
      <input id="fmImportAsync" type="checkbox" checked />
      <span>Processar em background para arquivos grandes</span>
    </label>
    <div id="fmImportPreview" style="margin:8px 0 10px 0;"></div>
    <button id="btnDoImport" class="fin-form-submit" type="button">📥 Importar</button>
    <div id="fmImportResult" style="margin-top:12px"></div>
  `);

  byId("fmImportFile")?.addEventListener("change", async () => {
    const fileEl = byId("fmImportFile");
    const previewEl = byId("fmImportPreview");
    if (!previewEl) return;
    if (!fileEl?.files?.length) {
      previewEl.innerHTML = "";
      return;
    }
    const file = fileEl.files[0];
    try {
      const text = await file.text();
      const name = String(file.name || "").toLowerCase();
      if (name.endsWith(".csv")) {
        previewEl.innerHTML = _renderCashflowCsvPreview(text);
      } else if (name.endsWith(".ofx") || name.endsWith(".qfx")) {
        previewEl.innerHTML = _renderCashflowOfxPreview(text);
      } else {
        previewEl.innerHTML = `<span class="fin-empty">Formato não suportado para preview.</span>`;
      }
    } catch {
      previewEl.innerHTML = `<span class="fin-down">Não foi possível ler o arquivo para preview.</span>`;
    }
  });

  byId("btnDoImport")?.addEventListener("click", async () => {
    const importMonth = String(byId("fmImportMonth")?.value || "").trim();
    const fileEl = byId("fmImportFile");
    const mergeNotes = byId("fmImportMergeNotes")?.checked === true;
    const asyncMode = byId("fmImportAsync")?.checked === true;
    if (!fileEl?.files?.length) {
      showToast("Selecione um arquivo");
      return;
    }
    const formData = new FormData();
    formData.append("file", fileEl.files[0]);
    try {
      const query = new URLSearchParams({
        month: importMonth,
        merge_strategy: mergeNotes ? "append_notes" : "suggest",
        async: asyncMode ? "1" : "0",
      });
      const resp = await finFetch(`/api/finance/cashflow/import?${query.toString()}`, {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      const resultEl = byId("fmImportResult");
      if (resp.status === 202 && data.async && data.job_id) {
        if (resultEl) {
          resultEl.innerHTML = `<span class="fin-warn">Importação em processamento...</span>`;
        }
        await _pollCashflowImportJob(data.job_id, resultEl);
        return;
      }
      if (!resp.ok) {
        if (resultEl) resultEl.innerHTML = `<span class="fin-down">${escapeHtml(data.error || "Erro")}</span>`;
        return;
      }
      if (resultEl) {
        const errHtml = data.errors?.length
          ? `<ul>${data.errors.map((it) => `<li>Linha ${it.row || it.transaction || "?"}: ${escapeHtml(it.error)}</li>`).join("")}</ul>`
          : "";
        const dupHtml = data.potential_duplicates?.length
          ? `<div style="margin-top:8px;border-left:3px solid #f59e0b;padding:6px 10px;font-size:.82em;opacity:.9;">
              <strong>⚠ ${data.potential_duplicates.length} ignorado(s) como possíveis duplicatas.</strong>
              <br>Detectadas por data, valor e similaridade da descrição.
              <ul style="margin:4px 0 0 16px;">${data.potential_duplicates.map((p) =>
                `<li>${escapeHtml(p.candidate.entry_date)} • R$ ${Number(p.candidate.amount).toFixed(2)} • ${escapeHtml(p.candidate.description || "")} (${escapeHtml(p.matched?.confidence || "")})</li>`
              ).join("")}</ul>
            </div>`
          : "";
        resultEl.innerHTML = `
          <span class="fin-up">✓ ${data.imported} lançamento(s) importado(s).</span>
          ${Number(data.merged || 0) > 0 ? `<br><span class="fin-up">↺ ${Number(data.merged)} duplicata(s) mesclada(s) em notas.</span>` : ""}
          ${dupHtml}
          ${data.errors?.length ? `<span class="fin-down"> ${data.errors.length} erro(s):</span>${errHtml}` : ""}
        `;
      }
      if (Number(data.imported || 0) > 0 || Number(data.merged || 0) > 0) await refreshByDomains(["cashflow"]);
    } catch {
      showToast("Erro de rede");
    }
  });
}

async function _pollCashflowImportJob(jobId, resultEl) {
  let attempts = 0;
  while (attempts < 120) {
    attempts += 1;
    await new Promise((resolve) => setTimeout(resolve, 1500));
    try {
      const resp = await finFetch(`/api/finance/cashflow/import/jobs/${encodeURIComponent(jobId)}`);
      const data = await resp.json();
      if (!resp.ok) {
        if (resultEl) resultEl.innerHTML = `<span class="fin-down">${escapeHtml(data.error || "Erro ao consultar job")}</span>`;
        return;
      }
      const status = String(data.status || "");
      if (status === "queued" || status === "running") {
        if (resultEl) resultEl.innerHTML = `<span class="fin-warn">Processando importação... (${status})</span>`;
        continue;
      }
      if (status === "failed") {
        if (resultEl) resultEl.innerHTML = `<span class="fin-down">${escapeHtml(data.error || "Falha no processamento")}</span>`;
        return;
      }
      const result = data.result || {};
      const errors = Array.isArray(result.errors) ? result.errors : [];
      const duplicates = Array.isArray(result.potential_duplicates) ? result.potential_duplicates : [];
      const errHtml = errors.length
        ? `<ul>${errors.map((it) => `<li>Linha ${it.row || it.transaction || "?"}: ${escapeHtml(it.error || "erro")}</li>`).join("")}</ul>`
        : "";
      const dupHtml = duplicates.length
        ? `<div style="margin-top:8px;border-left:3px solid #f59e0b;padding:6px 10px;font-size:.82em;opacity:.9;"><strong>⚠ ${duplicates.length} possível(is) duplicata(s).</strong></div>`
        : "";
      if (resultEl) {
        resultEl.innerHTML = `
          <span class="fin-up">✓ ${Number(result.imported || 0)} lançamento(s) importado(s).</span>
          ${Number(result.merged || 0) > 0 ? `<br><span class="fin-up">↺ ${Number(result.merged)} duplicata(s) mesclada(s).</span>` : ""}
          ${dupHtml}
          ${errors.length ? `<span class="fin-down"> ${errors.length} erro(s):</span>${errHtml}` : ""}
        `;
      }
      if (Number(result.imported || 0) > 0 || Number(result.merged || 0) > 0) {
        await refreshByDomains(["cashflow"]);
      }
      return;
    } catch {
      // keep polling on transient errors
    }
  }
  if (resultEl) {
    resultEl.innerHTML = '<span class="fin-down">Tempo limite ao aguardar importação assíncrona.</span>';
  }
}

function _parseCsvLine(line, sep) {
  const out = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (ch === sep && !inQuotes) {
      out.push(cur.trim());
      cur = "";
      continue;
    }
    cur += ch;
  }
  out.push(cur.trim());
  return out;
}

function _renderCashflowCsvPreview(text) {
  const lines = String(text || "").split(/\r?\n/).filter((l) => l.trim()).slice(0, 8);
  if (lines.length < 2) return `<p class="fin-empty">Arquivo CSV sem linhas suficientes para preview.</p>`;
  const sep = lines[0].includes(";") ? ";" : ",";
  const header = _parseCsvLine(lines[0], sep).map((h) => h.toLowerCase());
  const col = {
    date: header.findIndex((h) => ["date", "data", "dt"].includes(h)),
    amount: header.findIndex((h) => ["amount", "valor", "value"].includes(h)),
    type: header.findIndex((h) => ["type", "tipo"].includes(h)),
    category: header.findIndex((h) => ["category", "categoria"].includes(h)),
    description: header.findIndex((h) => ["description", "descricao", "hist"].includes(h)),
  };
  const rows = lines.slice(1, 6).map((line) => _parseCsvLine(line, sep));
  const pick = (cells, idx) => (idx >= 0 && idx < cells.length ? cells[idx] : "");
  const body = rows.map((cells) => `
    <tr>
      <td>${escapeHtml(pick(cells, col.date))}</td>
      <td>${escapeHtml(pick(cells, col.amount))}</td>
      <td>${escapeHtml(pick(cells, col.type))}</td>
      <td>${escapeHtml(pick(cells, col.category))}</td>
      <td>${escapeHtml(pick(cells, col.description))}</td>
    </tr>
  `).join("");

  return `
    <div style="border:1px solid var(--border,rgba(255,255,255,.12));border-radius:10px;padding:8px;">
      <div style="font-size:.82em;opacity:.82;margin-bottom:6px;">Preview CSV (primeiras linhas mapeadas)</div>
      <div class="fin-table-wrap">
        <table class="fin-table">
          <thead><tr><th>Data</th><th>Valor</th><th>Tipo</th><th>Categoria</th><th>Descrição</th></tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </div>
  `;
}

function _renderCashflowOfxPreview(text) {
  const blocks = String(text || "").match(/<STMTTRN>(.*?)<\/STMTTRN>/gis) || [];
  if (!blocks.length) return `<p class="fin-empty">Nenhuma transação OFX encontrada para preview.</p>`;
  const pickTag = (block, tag) => {
    const m = block.match(new RegExp(`<${tag}>([^\n\r<]+)`, "i"));
    return (m && m[1]) ? String(m[1]).trim() : "";
  };
  const rows = blocks.slice(0, 5).map((block) => {
    const rawDate = pickTag(block, "DTPOSTED");
    const date = /^\d{8}/.test(rawDate) ? `${rawDate.slice(0, 4)}-${rawDate.slice(4, 6)}-${rawDate.slice(6, 8)}` : rawDate;
    const amount = pickTag(block, "TRNAMT");
    const type = pickTag(block, "TRNTYPE");
    const memo = pickTag(block, "MEMO") || pickTag(block, "NAME");
    return `
      <tr>
        <td>${escapeHtml(date)}</td>
        <td>${escapeHtml(amount)}</td>
        <td>${escapeHtml(type)}</td>
        <td>${escapeHtml(memo)}</td>
      </tr>
    `;
  }).join("");

  return `
    <div style="border:1px solid var(--border,rgba(255,255,255,.12));border-radius:10px;padding:8px;">
      <div style="font-size:.82em;opacity:.82;margin-bottom:6px;">Preview OFX (primeiras transações)</div>
      <div class="fin-table-wrap">
        <table class="fin-table">
          <thead><tr><th>Data</th><th>Valor</th><th>Tipo OFX</th><th>Memo</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  `;
}

async function runCashflowAutoClassify() {
  const month = getSelectedCashflowMonth();
  try {
    const resp = await finFetch("/api/finance/cashflow/auto-classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ month }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Erro");
      return;
    }
    showToast(`${data.updated} lançamento(s) classificado(s) automaticamente`, "success");
    if (data.updated > 0) await refreshByDomains(["cashflow"]);
  } catch {
    showToast("Erro de rede");
  }
}

async function runCashflowAutoReconcile() {
  const month = getSelectedCashflowMonth();
  try {
    const resp = await finFetch("/api/finance/cashflow/reconcile-auto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ month, min_score: 60, apply: false }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Erro ao conciliar automaticamente");
      return;
    }

    const suggestions = Array.isArray(data.suggestions) ? data.suggestions : [];
    if (!suggestions.length) {
      showToast("Nenhum lançamento elegível para conciliação.", "info");
      return;
    }

    const rows = suggestions.slice(0, 50).map((s) => `
      <tr>
        <td><input type="checkbox" data-reconcile-id="${Number(s.id || 0)}" checked /></td>
        <td>${escapeHtml(String(s.entry_date || ""))}</td>
        <td>${formatBRL(Number(s.amount || 0))}</td>
        <td>${escapeHtml(String(s.category || ""))}</td>
        <td>${escapeHtml(String(s.description || ""))}</td>
        <td>${formatNumber(Number(s.score || 0), 1)}</td>
      </tr>
    `).join("");

    openFinModal("🤖 Revisar Auto-Conciliação", `
      <div style="margin-bottom:8px;opacity:.85;">Revise os lançamentos sugeridos antes de confirmar.</div>
      <div class="fin-table-wrap" style="max-height:320px;overflow:auto;">
        <table class="fin-table">
          <thead><tr><th></th><th>Data</th><th>Valor</th><th>Categoria</th><th>Descrição</th><th>Score</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <button id="btnConfirmReconcile" class="fin-form-submit" type="button" style="margin-top:10px;">✅ Confirmar conciliação</button>
    `);

    byId("btnConfirmReconcile")?.addEventListener("click", async () => {
      const checked = [...document.querySelectorAll("[data-reconcile-id]:checked")]
        .map((el) => Number(el.getAttribute("data-reconcile-id") || 0))
        .filter((n) => Number.isFinite(n) && n > 0);
      if (!checked.length) {
        showToast("Selecione ao menos um lançamento");
        return;
      }
      try {
        const confirmResp = await finFetch("/api/finance/cashflow/reconcile-auto/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ review_id: data.review_id, ids: checked }),
        });
        const confirmData = await confirmResp.json();
        if (!confirmResp.ok) {
          showToast(confirmData.error || "Erro ao confirmar conciliação");
          return;
        }
        closeFinModal();
        showToast(`Conciliação concluída: ${Number(confirmData.updated || 0)} item(ns) atualizado(s).`, "success");
        if (Number(confirmData.updated || 0) > 0) await refreshByDomains(["cashflow"]);
      } catch {
        showToast("Erro de rede");
      }
    });
  } catch {
    showToast("Erro de rede");
  }
}

async function loadCashflowKpis() {
  const month = getSelectedCashflowMonth();
  try {
    const resp = await fetch(`/api/finance/cashflow/kpis?month=${encodeURIComponent(month)}`);
    if (resp.ok) renderCashflowKpis(await resp.json());
  } catch {
    // non-critical
  }
}

async function loadCashflowBudgetAlerts() {
  const month = getSelectedCashflowMonth();
  try {
    const resp = await fetch(`/api/finance/cashflow/budget/alerts?month=${encodeURIComponent(month)}&threshold=80`);
    if (resp.ok) {
      const data = await resp.json();
      renderCashflowBudgetAlerts(data.alerts || []);
    }
  } catch {
    // non-critical
  }
}

function renderCashflowDataQuality(payload) {
  const el = byId("finCashflowDataQuality");
  if (!el) return;
  const data = payload || {};
  const issues = Array.isArray(data.issues) ? data.issues.filter((i) => Number(i.count || 0) > 0) : [];
  if (!issues.length) {
    el.innerHTML = '<div class="fin-cashflow-chip"><span>Qualidade dos dados</span><strong class="fin-up">Sem alertas no mês</strong></div>';
    return;
  }
  const issueHtml = issues.slice(0, 4).map((issue) => {
    const cls = issue.severity === "high" ? "fin-down" : "fin-warn";
    return `<div class="fin-cashflow-chip"><span>${escapeHtml(String(issue.label || issue.code || "Alerta"))}</span><strong class="${cls}">${Number(issue.count || 0)}</strong></div>`;
  }).join("");
  el.innerHTML = `
    <div class="fin-cashflow-kpis">
      <div class="fin-cashflow-kpi"><span>Qualidade</span><strong>${formatNumber(Number(data.score || 0), 0)}/100</strong></div>
      ${issueHtml}
    </div>
  `;
}

async function loadCashflowDataQuality() {
  const month = getSelectedCashflowMonth();
  try {
    const resp = await fetch(`/api/finance/cashflow/data-quality?month=${encodeURIComponent(month)}`);
    if (resp.ok) {
      renderCashflowDataQuality(await resp.json());
    }
  } catch {
    // non-critical
  }
}

async function openCashflowAttachmentModal(entryId) {
  const id = Number(entryId || 0);
  if (!id) return;

  let list = [];
  try {
    const resp = await finFetch(`/api/finance/cashflow/${id}/attachments`);
    if (resp.ok) list = await resp.json();
  } catch {
    // ignore and show empty list
  }

  const rows = Array.isArray(list) ? list : [];
  const listHtml = rows.length
    ? `
      <div class="fin-table-wrap" style="max-height:240px;overflow:auto;">
        <table class="fin-table">
          <thead><tr><th>Arquivo</th><th>Tamanho</th><th>Data</th><th></th></tr></thead>
          <tbody>
            ${rows.map((att) => `
              <tr>
                <td>${escapeHtml(att.file_name || "arquivo")}</td>
                <td>${formatNumber((Number(att.file_size || 0) / 1024), 1)} KB</td>
                <td>${escapeHtml(String(att.created_at || "").slice(0, 19).replace("T", " "))}</td>
                <td class="text-center">
                  <a class="fin-del-btn" href="/api/finance/cashflow/attachments/${att.id}/download" target="_blank" rel="noopener" title="Baixar">⬇</a>
                  <button class="fin-del-btn" data-action="deleteCashflowAttachment" data-id="${att.id}" data-entry="${id}" title="Excluir">✕</button>
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `
    : '<p class="fin-empty">Nenhum anexo para este lançamento.</p>';

  openFinModal("📎 Anexos do Lançamento (Gestor Financeiro)", `
    <div class="fin-form-group">
      <label>Enviar arquivo (máx. 2 MB)</label>
      <input id="fmAttachFile" type="file" />
    </div>
    <button id="btnUploadCashflowAttachment" class="fin-form-submit" type="button" data-entry="${id}">Enviar anexo</button>
    <div id="finAttachList" style="margin-top:12px;">${listHtml}</div>
  `);

  byId("btnUploadCashflowAttachment")?.addEventListener("click", async () => {
    await uploadCashflowAttachment(id);
  });
}

async function uploadCashflowAttachment(entryId) {
  const fileEl = byId("fmAttachFile");
  if (!fileEl?.files?.length) {
    showToast("Selecione um arquivo");
    return;
  }
  const fd = new FormData();
  fd.append("file", fileEl.files[0]);
  try {
    const resp = await finFetch(`/api/finance/cashflow/${entryId}/attachments`, {
      method: "POST",
      body: fd,
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Erro ao enviar anexo");
      return;
    }
    showToast("Anexo enviado", "success");
    await openCashflowAttachmentModal(entryId);
  } catch {
    showToast("Erro de rede");
  }
}

async function deleteCashflowAttachment(attachmentId, btnEl) {
  if (!confirm("Excluir este anexo?")) return;
  const entryId = Number(btnEl?.dataset?.entry || 0);
  try {
    const resp = await finFetch(`/api/finance/cashflow/attachments/${Number(attachmentId)}`, {
      method: "DELETE",
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Erro ao excluir anexo");
      return;
    }
    showToast("Anexo excluído", "success");
    if (entryId) await openCashflowAttachmentModal(entryId);
  } catch {
    showToast("Erro de rede");
  }
}

function exportCashflowClosingPdf() {
  const month = getSelectedCashflowMonth();
  const url = `/api/finance/cashflow/closing-pdf?month=${encodeURIComponent(month)}`;
  window.open(url, "_blank", "noopener");
}

function openEditCashflowModal(entryId) {
  const entry = (FIN.cashflowEntries || []).find((i) => Number(i.id) === Number(entryId));
  if (!entry) {
    showToast("Lançamento não encontrado");
    return;
  }
  const _ecard = Number(entry.credit_card_id || 0);
  const _eaccount = Number(entry.account_id || 0);
  const _eaccountOptions = ['<option value="">Sem conta</option>']
    .concat((Array.isArray(FIN.accounts) ? FIN.accounts : []).map((a) => {
      const aid = Number(a.id || 0);
      const sel = aid === _eaccount ? " selected" : "";
      const label = `${a.name || `Conta ${aid}`}${a.account_type ? ` (${a.account_type})` : ""}`;
      return `<option value="${aid}"${sel}>${escapeHtml(label)}</option>`;
    }))
    .join("");
  const _ecardOptions = ['<option value="">Sem cartão</option>']
    .concat((Array.isArray(FIN.creditCards) ? FIN.creditCards : []).map((c) => {
      const cid = Number(c.id || 0);
      const sel = cid === _ecard ? " selected" : "";
      return `<option value="${cid}"${sel}>${escapeHtml(c.name || `Cartão ${cid}`)}</option>`;
    }))
    .join("");
  openFinModal("Editar Lançamento (Gestor Financeiro)", `
    <form data-form-action="submitEditCashflow" data-form-arg="${entryId}">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmCfType">
            <option value="income" ${entry.entry_type === "income" ? "selected" : ""}>Ganho</option>
            <option value="expense" ${entry.entry_type === "expense" ? "selected" : ""}>Gasto</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Data</label>
          <input id="fmCfDate" type="date" value="${escapeHtml(String(entry.entry_date || "").slice(0, 10))}" required />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Status</label>
          <select id="fmCfStatus">
            <option value="pending" ${String(entry.payment_status || "").toLowerCase() === "pending" ? "selected" : ""}>Pendente</option>
            <option value="paid" ${String(entry.payment_status || "").toLowerCase() === "paid" ? "selected" : ""}>Pago</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Data da baixa</label>
          <input id="fmCfSettledAt" type="date" value="${escapeHtml(String(entry.settled_at || "").slice(0, 10))}" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Valor (R$)</label>
          <input id="fmCfAmount" type="number" min="0.01" step="0.01" value="${Number(entry.amount || 0)}" required />
        </div>
        <div class="fin-form-group">
          <label>Categoria</label>
          <input id="fmCfCategory" list="finCfCategoriesDatalist" value="${escapeHtml(entry.category || "")}" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Subcategoria</label>
          <input id="fmCfSubcategory" list="finCfSubcategoriesDatalist" value="${escapeHtml(entry.subcategory || "")}" />
        </div>
        <div class="fin-form-group">
          <label>Centro de custo</label>
          <input id="fmCfCostCenter" value="${escapeHtml(entry.cost_center || "")}" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Descrição</label>
        <input id="fmCfDescription" list="finCfDescriptionsDatalist" value="${escapeHtml(entry.description || "")}" required />
      </div>
      <div class="fin-form-group">
        <label>Cartão (opcional)</label>
        <select id="fmCfCreditCard">${_ecardOptions}</select>
      </div>
      <div class="fin-form-group">
        <label>Conta (opcional)</label>
        <select id="fmCfAccount">${_eaccountOptions}</select>
      </div>
      <div class="fin-form-group">
        <label>Tags</label>
        <input id="fmCfTags" value="${escapeHtml(Array.isArray(entry.tags) ? entry.tags.join(", ") : "")}" placeholder="Ex.: fixo, essencial" />
      </div>
      <div class="fin-form-group">
        <label>Notas</label>
        <textarea id="fmCfNotes" rows="2" placeholder="Opcional">${escapeHtml(entry.notes || "")}</textarea>
      </div>
      <button type="submit" class="fin-form-submit">💾 Salvar Alterações</button>
    </form>
  `);

  if (!Array.isArray(FIN.creditCards) || !FIN.creditCards.length) {
    finFetch("/api/finance/credit-cards")
      .then((resp) => resp.ok ? resp.json() : [])
      .then((cards) => {
        FIN.creditCards = Array.isArray(cards) ? cards : [];
        const sel = byId("fmCfCreditCard");
        if (!sel) return;
        const current = Number(entry.credit_card_id || 0);
        sel.innerHTML = ['<option value="">Sem cartão</option>']
          .concat(FIN.creditCards.map((c) => {
            const cid = Number(c.id || 0);
            const mark = cid === current ? " selected" : "";
            return `<option value="${cid}"${mark}>${escapeHtml(c.name || `Cartão ${cid}`)}</option>`;
          }))
          .join("");
      })
      .catch(() => { /* ignore */ });
  }

  if (!Array.isArray(FIN.accounts) || !FIN.accounts.length) {
    finFetch("/api/finance/accounts")
      .then((resp) => resp.ok ? resp.json() : [])
      .then((accounts) => {
        FIN.accounts = Array.isArray(accounts) ? accounts : [];
        const sel = byId("fmCfAccount");
        if (!sel) return;
        const current = Number(entry.account_id || 0);
        sel.innerHTML = ['<option value="">Sem conta</option>']
          .concat(FIN.accounts.map((a) => {
            const aid = Number(a.id || 0);
            const mark = aid === current ? " selected" : "";
            const label = `${a.name || `Conta ${aid}`}${a.account_type ? ` (${a.account_type})` : ""}`;
            return `<option value="${aid}"${mark}>${escapeHtml(label)}</option>`;
          }))
          .join("");
      })
      .catch(() => { /* ignore */ });
  }
}

async function submitEditCashflow(e, entryId) {
  e.preventDefault();
  const paymentStatus = String(byId("fmCfStatus")?.value || "pending").trim();
  const settledAt = String(byId("fmCfSettledAt")?.value || "").trim();
  const body = {
    entry_type: String(byId("fmCfType")?.value || "expense"),
    amount: Number(byId("fmCfAmount")?.value || 0),
    category: String(byId("fmCfCategory")?.value || "").trim(),
    subcategory: String(byId("fmCfSubcategory")?.value || "").trim(),
    cost_center: String(byId("fmCfCostCenter")?.value || "").trim(),
    description: String(byId("fmCfDescription")?.value || "").trim(),
    entry_date: String(byId("fmCfDate")?.value || "").trim(),
    notes: String(byId("fmCfNotes")?.value || "").trim(),
    account_id: Number(byId("fmCfAccount")?.value) || null,
    credit_card_id: Number(byId("fmCfCreditCard")?.value) || null,
    tags: parseTagsInput(byId("fmCfTags")?.value || ""),
    payment_status: paymentStatus,
    settled_at: paymentStatus === "paid" ? settledAt : null,
  };

  // Personal spending guard on edit
  if (body.entry_type === "expense" && body.category && body.amount > 0) {
    const month = body.entry_date ? body.entry_date.slice(0, 7) : getSelectedCashflowMonth();
    try {
      const chk = await fetch(
        `/api/finance/cashflow/budget/check?category=${encodeURIComponent(body.category)}&amount=${body.amount}&month=${encodeURIComponent(month)}`
      );
      if (chk.ok) {
        const chkData = await chk.json();
        if (chkData.has_budget && chkData.over_budget) {
          const msg = `⚠️ Este gasto de ${formatBRL(body.amount)} levaria "${body.category}" a ${formatBRL(chkData.would_be_spent)} — acima do limite de ${formatBRL(chkData.limit)}. Continuar?`;
          if (!confirm(msg)) return;
        }
      }
    } catch { /* non-blocking */ }
  }

  try {
    const resp = await finFetch(`/api/finance/cashflow/${entryId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const data = await resp.json();
      showToast(data.error || "Erro ao atualizar lançamento");
      return;
    }
    closeFinModal();
    await refreshByDomains(["cashflow"]);
    showToast("Lançamento atualizado!", "success");
  } catch {
    showToast("Erro de rede");
  }
}

async function submitCashflowBudget(e) {
  e.preventDefault();
  const month = String(byId("fmBudgetMonth")?.value || "").trim();
  const rows = Array.from(document.querySelectorAll("#fmBudgetRows [data-budget-row]"));
  const budget = {};
  rows.forEach((row) => {
    const cat = String(row.querySelector("[data-budget-cat]")?.value || "").trim();
    const limit = Number(row.querySelector("[data-budget-limit]")?.value || 0);
    if (!cat || !(limit >= 0)) return;
    budget[cat] = limit;
  });

  try {
    const resp = await finFetch("/api/finance/cashflow/budget", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ month, budget }),
    });
    if (!resp.ok) {
      const data = await resp.json();
      showToast(data.error || "Erro ao salvar orçamento");
      return;
    }
    closeFinModal();
    await refreshByDomains(["cashflow"]);
    showToast("Orçamento atualizado!", "success");
  } catch {
    showToast("Erro de rede");
  }
}

async function submitCashflowRollover(e) {
  e.preventDefault();
  const sourceMonth = String(byId("fmCfRollSourceMonth")?.value || "").trim();
  const targetMonth = String(byId("fmCfRollTargetMonth")?.value || "").trim();
  const entryType = String(byId("fmCfRollType")?.value || "all").trim();

  try {
    const resp = await finFetch("/api/finance/cashflow/rollover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_month: sourceMonth,
        target_month: targetMonth,
        entry_type: entryType,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Erro ao executar virada de mês");
      return;
    }

    closeFinModal();
    await refreshByDomains(["cashflow"]);
    showToast(
      `Virada concluída: ${Number(data.created || 0)} criado(s), ${Number(data.skipped || 0)} ignorado(s).`,
      "success",
    );
  } catch {
    showToast("Erro de rede");
  }
}

async function deleteCashflowEntry(entryId) {
  withUndoDelete("Lançamento será excluído.", async () => {
    try {
      const resp = await finFetch(`/api/finance/cashflow/${entryId}`, { method: "DELETE" });
      if (!resp.ok) {
        const data = await resp.json();
        showToast(data.error || "Erro ao excluir lançamento");
        return;
      }
      await refreshByDomains(["cashflow"]);
      showToast("Lançamento removido.", "success");
    } catch {
      showToast("Erro de rede");
    }
  });
}

function withUndoDelete(label, onDelete, delayMs = 5000) {
  let cancelled = false;
  showToast(label, "warn", {
    actionLabel: "Desfazer",
    timeout: delayMs,
    onAction: () => { cancelled = true; },
  });
  setTimeout(() => { if (!cancelled) onDelete(); }, delayMs);
}

async function toggleCashflowStatus(entryId, btnEl) {
  const nextStatus = String(btnEl?.dataset?.status || "").trim().toLowerCase();
  if (!nextStatus || !["pending", "paid"].includes(nextStatus)) {
    showToast("Status inválido para conciliação");
    return;
  }
  const payload = { status: nextStatus };
  if (nextStatus === "paid") {
    payload.settled_at = new Date().toISOString().slice(0, 10);
  }

  try {
    const resp = await finFetch(`/api/finance/cashflow/${entryId}/status`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Erro ao conciliar lançamento");
      return;
    }
    await refreshByDomains(["cashflow"]);
    showToast(`Lançamento marcado como ${data.status === "paid" ? "pago" : "pendente"}.`, "success");
  } catch {
    showToast("Erro de rede");
  }
}

function _collectCurrentCashflowFilter() {
  return {
    month: String(byId("finCashflowMonth")?.value || "").trim(),
    type: String(byId("finCashflowType")?.value || "").trim(),
    status: String(byId("finCashflowStatus")?.value || "").trim(),
    cost_center: String(byId("finCashflowCostCenter")?.value || "").trim(),
    tag: String(byId("finCashflowTag")?.value || "").trim(),
    q: String(byId("finCashflowQ")?.value || "").trim(),
  };
}

function _applyCashflowFilter(filter) {
  byId("finCashflowMonth").value = String(filter.month || "").trim();
  byId("finCashflowType").value = String(filter.type || "").trim();
  byId("finCashflowStatus").value = String(filter.status || "").trim();
  byId("finCashflowCostCenter").value = String(filter.cost_center || "").trim();
  byId("finCashflowTag").value = String(filter.tag || "").trim();
  byId("finCashflowQ").value = String(filter.q || "").trim();
}

async function openCashflowMonthPlanModal() {
  const month = getSelectedCashflowMonth();
  openFinModal("🗓 Plano Mensal do Gestor Financeiro", `
    <div class="fin-form-group">
      <label>Mês</label>
      <input id="fmMonthPlanMonth" type="month" value="${escapeHtml(month)}" />
    </div>
    <button id="btnRunMonthPlan" class="fin-form-submit" type="button">Gerar plano</button>
    <div id="fmMonthPlanResult" style="margin-top:12px;"></div>
  `);

  const run = async () => {
    const target = String(byId("fmMonthPlanMonth")?.value || "").trim();
    const resultEl = byId("fmMonthPlanResult");
    try {
      const resp = await finFetch(`/api/finance/cashflow/month-plan?month=${encodeURIComponent(target)}`);
      const data = await resp.json();
      if (!resp.ok) {
        if (resultEl) resultEl.innerHTML = `<span class="fin-down">${escapeHtml(data.error || "Erro")}</span>`;
        return;
      }

      const rows = (data.weeks || []).map((w) => `
        <tr>
          <td>${escapeHtml(w.label || "")}</td>
          <td class="text-right mono fin-up">${formatBRL(w.income || 0)}</td>
          <td class="text-right mono fin-down">${formatBRL(w.expense || 0)}</td>
          <td class="text-right mono">${formatBRL(w.expected_income || 0)}</td>
          <td class="text-right mono">${formatBRL(w.expected_expense || 0)}</td>
          <td class="text-right mono ${Number(w.net || 0) >= 0 ? "fin-up" : "fin-down"}">${formatBRL(w.net || 0)}</td>
          <td class="text-right mono ${Number(w.projected_balance || 0) >= 0 ? "fin-up" : "fin-down"}">${formatBRL(w.projected_balance || 0)}</td>
        </tr>
      `).join("");

      const riskHtml = (data.risk_flags || []).length
        ? `<div style="margin-top:8px;">${data.risk_flags.map((r) =>
            `<span class="fin-budget-alert-badge fin-alert-warn">⚠ ${escapeHtml(r.category || "")}: ${Number(r.usage_pct || 0).toFixed(1)}%</span>`
          ).join("")}</div>`
        : "";

      if (resultEl) {
        resultEl.innerHTML = `
          <div class="fin-cashflow-kpis" style="margin-bottom:8px;">
            <div class="fin-cashflow-kpi"><span>Saldo inicial</span><strong>${formatBRL(data.starting_balance || 0)}</strong></div>
            <div class="fin-cashflow-kpi"><span>Saldo projetado fim do mês</span><strong class="${Number(data.projected_end_balance || 0) >= 0 ? "fin-up" : "fin-down"}">${formatBRL(data.projected_end_balance || 0)}</strong></div>
          </div>
          <div class="fin-table-wrap" style="max-height:280px;overflow:auto;">
            <table class="fin-table">
              <thead><tr><th>Semana</th><th class="text-right">Realizado +</th><th class="text-right">Realizado -</th><th class="text-right">Previsto +</th><th class="text-right">Previsto -</th><th class="text-right">Líquido</th><th class="text-right">Saldo proj.</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
          ${riskHtml}
        `;
      }
    } catch {
      if (resultEl) resultEl.innerHTML = '<span class="fin-down">Erro de rede</span>';
    }
  };

  byId("btnRunMonthPlan")?.addEventListener("click", run);
  run();
}

/* ══════════════════════════════════════════════════════════
   Utility Functions for Performance Optimization
   ══════════════════════════════════════════════════════════ */

function _debounce(func, delay = 300) {
  let timeoutId;
  return function(...args) {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => func(...args), delay);
  };
}

/* ══════════════════════════════════════════════════════════
   localStorage Utilities for Filters Modal
   ══════════════════════════════════════════════════════════ */

function _getFilterModalPreferences() {
  try {
    const stored = localStorage.getItem("fin_filters_modal_prefs");
    return stored ? JSON.parse(stored) : { activeTab: 0, recentFilters: [] };
  } catch {
    return { activeTab: 0, recentFilters: [] };
  }
}

function _saveFilterModalPreferences(prefs) {
  try {
    localStorage.setItem("fin_filters_modal_prefs", JSON.stringify(prefs));
  } catch {
    // Fail silently if localStorage is unavailable
  }
}

function _addToRecentFilters(filterId, filterName) {
  const prefs = _getFilterModalPreferences();
  const recent = prefs.recentFilters || [];
  
  // Add to beginning, remove if already exists
  const filtered = recent.filter(f => f.id !== filterId);
  filtered.unshift({ id: filterId, name: filterName, timestamp: Date.now() });
  
  // Keep only last 10
  prefs.recentFilters = filtered.slice(0, 10);
  _saveFilterModalPreferences(prefs);
}

function _getRecentFilters() {
  const prefs = _getFilterModalPreferences();
  return (prefs.recentFilters || []).filter(f => Date.now() - f.timestamp < 7 * 24 * 60 * 60 * 1000); // 7 days
}

function _setActiveFilterTab(tabIndex) {
  const prefs = _getFilterModalPreferences();
  prefs.activeTab = tabIndex;
  _saveFilterModalPreferences(prefs);
}

function _getActiveFilterTab() {
  const prefs = _getFilterModalPreferences();
  return prefs.activeTab || 0;
}

async function openCashflowSavedFiltersModal() {
  const current = _collectCurrentCashflowFilter();
  let rows = [];
  let templates = [];
  try {
    const [filtersResp, templatesResp] = await Promise.all([
      finFetch("/api/finance/cashflow/saved-filters"),
      finFetch("/api/finance/cashflow/filters/templates"),
    ]);
    if (filtersResp.ok) rows = await filtersResp.json();
    if (templatesResp.ok) templates = await templatesResp.json();
  } catch { /* ignore */ }

  // Sort by favorite first, then by usage count
  const sortedRows = (rows || []).sort((a, b) => {
    if (a.is_favorite !== b.is_favorite) return b.is_favorite ? 1 : -1;
    return (b.use_count || 0) - (a.use_count || 0);
  });

  // Get recent filters
  const recentFilters = _getRecentFilters();

  const renderFilterRow = (r) => `
    <div class="fin-filter-row" data-filter-id="${r.id}">
      <div class="fin-filter-name">
        <div class="fin-filter-title">${escapeHtml(r.name || "Filtro")}</div>
        <div class="fin-filter-meta">
          <span class="fin-filter-usage">
            <span>${r.use_count || 0}×</span>
          </span>
          ${r.last_used_at ? `<span title="Última utilização">↻ ${escapeHtml(String(r.last_used_at).slice(0, 10))}</span>` : ''}
        </div>
      </div>
      <div class="fin-filter-actions">
        <span class="fin-filter-star ${r.is_favorite ? 'is-favorite' : ''}" 
              data-action="toggleFavFilter" 
              data-id="${r.id}" 
              title="Favorito">★</span>
        <button class="fin-filter-btn" data-action="applyCashflowSavedFilter" data-id="${r.id}" title="Aplicar">Usar</button>
        <button class="fin-filter-btn delete" data-action="deleteCashflowSavedFilter" data-id="${r.id}" title="Excluir">×</button>
      </div>
    </div>
  `;

  const renderTemplateRow = (t) => `
    <div class="fin-template-row">
      <div class="fin-template-title">${escapeHtml(t.name || "Template")}</div>
      <div class="fin-template-desc">${escapeHtml(t.description || "(Sem descrição)")}</div>
      <button class="fin-template-btn" data-action="applyTemplateFilter" data-id="${t.id}">Usar template</button>
    </div>
  `;

  const renderRecentRow = (r) => `
    <div class="fin-recent-filter" data-filter-id="${r.id}">
      <span class="fin-recent-label">🕐 ${escapeHtml(r.name)}</span>
      <button class="fin-recent-btn" data-action="applyRecentFilter" data-id="${r.id}">Usar</button>
    </div>
  `;

  const myFiltersHtml = sortedRows.length
    ? sortedRows.map(renderFilterRow).join("")
    : '<div class="fin-filters-empty"><div class="fin-filters-empty-icon">📭</div><div>Nenhum filtro salvo</div></div>';

  const templatesHtml = templates.length
    ? templates.map(renderTemplateRow).join("")
    : '<div class="fin-filters-empty"><div class="fin-filters-empty-icon">📋</div><div>Nenhum template disponível</div></div>';

  const recentHtml = recentFilters.length
    ? recentFilters.map(renderRecentRow).join("")
    : '';

  openFinModal("🔖 Filtros & Templates", `
    <div class="fin-filter-tabs">
      <button id="tabMyFilters" class="fin-filter-tab active">
        Meus Filtros <span style="font-size:0.8em;opacity:0.7;">(${sortedRows.length})</span>
      </button>
      <button id="tabTemplates" class="fin-filter-tab">
        Templates <span style="font-size:0.8em;opacity:0.7;">(${templates.length})</span>
      </button>
    </div>

    <div id="myFiltersTab" style="display:block;">
      <div class="fin-form-group">
        <label>Nome do filtro atual</label>
        <input id="fmCashflowFilterName" placeholder="Ex.: Pagamentos pendentes" />
        <small style="display:block;opacity:.7;margin-top:4px;">Filtro: ${escapeHtml(JSON.stringify(current).substring(0, 60))}...</small>
      </div>
      <button id="btnSaveCashflowFilter" class="fin-form-submit" type="button">💾 Salvar filtro atual</button>

      ${recentHtml ? `
        <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:12px;">
          <div style="font-size:0.9em;font-weight:500;margin-bottom:8px;color:var(--text-secondary);">Filtros Recentes</div>
          <div style="display:flex;flex-direction:column;gap:6px;">
            ${recentHtml}
          </div>
        </div>
      ` : ''}

      <div style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px;">
        <div style="font-size:0.9em;font-weight:500;margin-bottom:8px;color:var(--text-secondary);">
          🔍 Buscar
        </div>
        <input id="filterSearchInput" 
               type="text" 
               placeholder="Buscar filtro por nome..." 
               style="width:100%;padding:8px;border:1px solid var(--border);border-radius:4px;margin-bottom:8px;" />
      </div>

      <div class="fin-filter-list" style="margin-top:8px;">
        ${myFiltersHtml}
      </div>
    </div>

    <div id="templatesTab" style="display:none;">
      <p style="opacity:0.7;font-size:0.9em;margin-bottom:12px;">
        Templates são filtros pré-configurados para casos de uso comuns. Clique em "Usar template" para aplicar.
      </p>
      <div class="fin-template-list">
        ${templatesHtml}
      </div>
    </div>
  `);

  // Tab switching with localStorage
  const tabMyFilters = byId("tabMyFilters");
  const tabTemplates = byId("tabTemplates");
  const myFiltersTab = byId("myFiltersTab");
  const templatesTab = byId("templatesTab");

  tabMyFilters?.addEventListener("click", () => {
    myFiltersTab.style.display = "block";
    templatesTab.style.display = "none";
    tabMyFilters.classList.add("active");
    tabTemplates.classList.remove("active");
    _setActiveFilterTab(0);
  });

  tabTemplates?.addEventListener("click", () => {
    myFiltersTab.style.display = "none";
    templatesTab.style.display = "block";
    tabMyFilters.classList.remove("active");
    tabTemplates.classList.add("active");
    _setActiveFilterTab(1);
  });

  // Restore last active tab from localStorage
  if (_getActiveFilterTab() === 1) {
    tabTemplates?.click();
  }

  // Search functionality with debouncing
  const searchInput = byId("filterSearchInput");
  if (searchInput) {
    const performSearch = (e) => {
      const query = String(e.target.value).toLowerCase().trim();
      const rows = byId("myFiltersTab")?.querySelectorAll(".fin-filter-row") || [];

      rows.forEach((row) => {
        const name = row.querySelector(".fin-filter-title")?.textContent || "";
        const matches = name.toLowerCase().includes(query);
        row.style.display = matches ? "flex" : "none";
      });

      const visibleRows = Array.from(rows).filter((r) => r.style.display !== "none");
      const listEl = byId("myFiltersTab")?.querySelector(".fin-filter-list");
      let emptyMsg = byId("myFiltersTab")?.querySelector(".fin-filters-empty");
      if (!emptyMsg && listEl) {
        emptyMsg = document.createElement("div");
        emptyMsg.className = "fin-filters-empty";
        emptyMsg.innerHTML = '<div class="fin-filters-empty-icon">🔍</div><div>Nenhum filtro encontrado</div>';
        listEl.appendChild(emptyMsg);
      }
      if (emptyMsg) {
        emptyMsg.style.display = visibleRows.length === 0 ? "block" : "none";
      }
    };

    const debouncedSearch = _debounce(performSearch, 300);
    searchInput.addEventListener("input", debouncedSearch);
  }

  byId("btnSaveCashflowFilter")?.addEventListener("click", async () => {
    const name = String(byId("fmCashflowFilterName")?.value || "").trim();
    if (!name) { showToast("Informe um nome para o filtro"); return; }
    try {
      const resp = await finFetch("/api/finance/cashflow/saved-filters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, filter: _collectCurrentCashflowFilter() }),
      });
      const data = await resp.json();
      if (!resp.ok) { showToast(data.error || "Erro ao salvar filtro"); return; }
      showToast("Filtro salvo", "success");
      await openCashflowSavedFiltersModal();
    } catch { showToast("Erro de rede"); }
  });

  // Keyboard shortcuts for modal
  if (FIN._cashflowModalKeyHandler) {
    document.removeEventListener("keydown", FIN._cashflowModalKeyHandler);
  }
  const modalKeyHandler = async (e) => {
    // Ctrl+S to save filter
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      const btnSave = byId("btnSaveCashflowFilter");
      if (btnSave) btnSave.click();
      return;
    }

    // Escape to close modal (already handled by modal system)
    if (e.key === 'Escape') {
      closeFinModal();
      return;
    }

    // Delete to remove selected filter (if any)
    if (e.key === 'Delete') {
      e.preventDefault();
      const focusedRow = document.activeElement?.closest(".fin-filter-row");
      if (focusedRow) {
        const filterId = focusedRow.dataset.filterId;
        if (filterId && confirm("Excluir este filtro salvo?")) {
          const deleteBtn = focusedRow.querySelector("[data-action='deleteCashflowSavedFilter']");
          if (deleteBtn) deleteBtn.click();
        }
      }
      return;
    }

    // Enter to apply filter (if search input or filter row focused)
    if (e.key === 'Enter') {
      const activeEl = document.activeElement;
      if (activeEl?.id === 'filterSearchInput') {
        // Apply first visible filter if search is active
        const rowEls = Array.from(byId("myFiltersTab")?.querySelectorAll(".fin-filter-row") || []);
        const visibleRow = rowEls.find((row) => row.style.display !== "none");
        if (visibleRow) {
          const useBtn = visibleRow.querySelector("[data-action='applyCashflowSavedFilter']");
          if (useBtn) useBtn.click();
        }
        return;
      }
      const focusedRow = activeEl?.closest(".fin-filter-row, .fin-recent-filter");
      if (focusedRow) {
        const useBtn = focusedRow.querySelector("[data-action], button:not(.delete)");
        if (useBtn) useBtn.click();
      }
    }
  };

  FIN._cashflowModalKeyHandler = modalKeyHandler;
  document.addEventListener("keydown", modalKeyHandler);

  const modal = document.querySelector("#finModalBody");
  modal?.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const id = Number(btn.dataset.id || 0);

    if (btn.dataset.action === "toggleFavFilter") {
      try {
        const resp = await finFetch(`/api/finance/cashflow/saved-filters/${id}/favorite`, {
          method: "PUT",
        });
        if (!resp.ok) { showToast("Erro ao marcar favorito"); return; }
        const star = btn;
        star.classList.toggle("is-favorite");
        showToast("Favorito atualizado", "success");
      } catch { showToast("Erro de rede"); }
      return;
    }

    if (btn.dataset.action === "applyCashflowSavedFilter") {
      const item = (rows || []).find((x) => Number(x.id) === id);
      if (!item) return;
      try {
        await finFetch(`/api/finance/cashflow/saved-filters/${id}/apply`, {
          method: "POST",
        });
        _addToRecentFilters(item.id, item.name);
      } catch { /* ignore usage tracking error */ }
      _applyCashflowFilter(item.filter || {});
      closeFinModal();
      await refreshByDomains(["cashflow"]);
      showToast("Filtro aplicado", "success");
      return;
    }

    if (btn.dataset.action === "applyRecentFilter") {
      // Find filter by id in rows
      const item = (rows || []).find((x) => Number(x.id) === id);
      if (!item) return;
      try {
        await finFetch(`/api/finance/cashflow/saved-filters/${id}/apply`, {
          method: "POST",
        });
        _addToRecentFilters(item.id, item.name);
      } catch { /* ignore usage tracking error */ }
      _applyCashflowFilter(item.filter || {});
      closeFinModal();
      await refreshByDomains(["cashflow"]);
      showToast("Filtro aplicado", "success");
      return;
    }

    if (btn.dataset.action === "applyTemplateFilter") {
      const item = (templates || []).find((x) => Number(x.id) === id);
      if (!item) return;
      try {
        await finFetch(`/api/finance/cashflow/saved-filters/${id}/apply`, {
          method: "POST",
        });
      } catch { /* ignore usage tracking */ }
      _applyCashflowFilter(item.filter || {});
      closeFinModal();
      await refreshByDomains(["cashflow"]);
      showToast(`Template "${item.name}" aplicado`, "success");
      return;
    }

    if (btn.dataset.action === "deleteCashflowSavedFilter") {
      if (!confirm("Excluir este filtro salvo?")) return;
      try {
        const resp = await finFetch(`/api/finance/cashflow/saved-filters/${id}`, { method: "DELETE" });
        if (!resp.ok) { showToast("Erro ao excluir filtro"); return; }
        showToast("Filtro removido", "success");
        await openCashflowSavedFiltersModal();
      } catch { showToast("Erro de rede"); }
    }
  });
}


async function openCashflowBulkModal() {
  const rows = Array.isArray(FIN.cashflowEntries) ? FIN.cashflowEntries : [];
  if (!rows.length) {
    showToast("Nenhum lançamento carregado para ação em lote");
    return;
  }

  const entriesHtml = rows.slice(0, 300).map((r) => `
    <label style="display:flex;gap:8px;align-items:center;padding:4px 0;">
      <input type="checkbox" data-bulk-id="${r.id}" />
      <span style="flex:1;">${escapeHtml(String(r.entry_date || "").slice(0, 10))} • ${escapeHtml(r.category || "—")} • ${escapeHtml(r.description || "—")}</span>
      <strong class="${String(r.entry_type) === "income" ? "fin-up" : "fin-down"}">${formatBRL(r.amount || 0)}</strong>
    </label>
  `).join("");

  openFinModal("🧩 Ações em Lote (Gestor Financeiro)", `
    <div class="fin-form-row">
      <div class="fin-form-group">
        <label>Ação</label>
        <select id="fmBulkAction">
          <option value="update">Atualizar categoria/tags/notas</option>
          <option value="status">Alterar status (pago/pendente)</option>
          <option value="delete">Excluir lançamentos</option>
        </select>
      </div>
      <div class="fin-form-group">
        <label>Status</label>
        <select id="fmBulkStatus">
          <option value="paid">Pago</option>
          <option value="pending">Pendente</option>
        </select>
      </div>
    </div>
    <div class="fin-form-row">
      <div class="fin-form-group">
        <label>Categoria</label>
        <input id="fmBulkCategory" placeholder="Ex.: Alimentação" />
      </div>
      <div class="fin-form-group">
        <label>Tags</label>
        <input id="fmBulkTags" placeholder="Ex.: recorrente, essencial" />
      </div>
    </div>
    <div class="fin-form-group">
      <label>Notas</label>
      <input id="fmBulkNotes" placeholder="Opcional" />
    </div>
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
      <button id="btnBulkSelectAll" class="btn-text" type="button">Marcar todos</button>
      <button id="btnBulkClearAll" class="btn-text" type="button">Limpar</button>
      <button id="btnBulkRun" class="fin-form-submit" type="button" style="margin-left:auto;">Executar</button>
    </div>
    <div style="max-height:300px;overflow:auto;border:1px solid rgba(255,255,255,.08);padding:8px;border-radius:6px;">${entriesHtml}</div>
  `);

  byId("btnBulkSelectAll")?.addEventListener("click", () => {
    document.querySelectorAll("input[data-bulk-id]").forEach((el) => { el.checked = true; });
  });
  byId("btnBulkClearAll")?.addEventListener("click", () => {
    document.querySelectorAll("input[data-bulk-id]").forEach((el) => { el.checked = false; });
  });

  byId("btnBulkRun")?.addEventListener("click", async () => {
    const ids = Array.from(document.querySelectorAll("input[data-bulk-id]:checked"))
      .map((el) => Number(el.dataset.bulkId || 0))
      .filter((n) => n > 0);
    if (!ids.length) { showToast("Selecione ao menos 1 lançamento"); return; }
    const action = String(byId("fmBulkAction")?.value || "update");
    const updates = {};
    if (action === "status") {
      updates.status = String(byId("fmBulkStatus")?.value || "pending");
      if (updates.status === "paid") updates.settled_at = new Date().toISOString().slice(0, 10);
    } else if (action === "update") {
      const category = String(byId("fmBulkCategory")?.value || "").trim();
      const notes = String(byId("fmBulkNotes")?.value || "").trim();
      const tags = parseTagsInput(String(byId("fmBulkTags")?.value || ""));
      if (category) updates.category = category;
      if (notes) updates.notes = notes;
      if (tags.length) updates.tags = tags;
      if (!Object.keys(updates).length) { showToast("Informe ao menos um campo para atualizar"); return; }
    } else if (action === "delete") {
      if (!confirm(`Excluir ${ids.length} lançamento(s)?`)) return;
    }

    try {
      const resp = await finFetch("/api/finance/cashflow/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, action, updates }),
      });
      const data = await resp.json();
      if (!resp.ok) { showToast(data.error || "Erro na ação em lote"); return; }
      closeFinModal();
      await refreshByDomains(["cashflow"]);
      showToast(`Ação em lote concluída. Atualizados: ${data.updated || 0}, excluídos: ${data.deleted || 0}.`, "success");
    } catch {
      showToast("Erro de rede");
    }
  });
}

function openGoalScenarioModal(goalId) {
  const goals = Array.isArray(FIN.goals) ? FIN.goals : [];
  if (!goals.length) {
    showToast("Cadastre uma meta para simular cenários");
    return;
  }
  const selectedId = Number(goalId || goals[0].id);
  const month = getSelectedCashflowMonth();
  const expenseCats = Array.isArray(FIN.cashflowAnalytics?.categories?.expense)
    ? FIN.cashflowAnalytics.categories.expense
    : [];

  const options = goals.map((g) =>
    `<option value="${g.id}" ${Number(g.id) === selectedId ? "selected" : ""}>${escapeHtml(g.name)} (${formatBRL(g.current_amount || 0)} / ${formatBRL(g.target_amount || 0)})</option>`
  ).join("");

  const catRows = expenseCats.map((c, i) => `
    <div class="fin-form-row" data-goal-sc-row="${i}">
      <div class="fin-form-group" style="flex:2">
        <label>Categoria</label>
        <input data-goal-cat value="${escapeHtml(c.category || "")}" readonly />
      </div>
      <div class="fin-form-group">
        <label>Redução %</label>
        <input data-goal-pct type="number" min="0" max="100" step="1" value="0" />
      </div>
    </div>
  `).join("");

  openFinModal("📉 Cenário de Meta", `
    <div class="fin-form-group">
      <label>Meta</label>
      <select id="fmGoalScenarioGoal">${options}</select>
    </div>
    <div class="fin-form-row">
      <div class="fin-form-group">
        <label>Mês base</label>
        <input id="fmGoalScenarioMonth" type="month" value="${escapeHtml(month)}" />
      </div>
      <div class="fin-form-group">
        <label>Aporte extra mensal (R$)</label>
        <input id="fmGoalScenarioExtra" type="number" min="0" step="0.01" value="0" />
      </div>
    </div>
    <div id="fmGoalScenarioAdjustments">${catRows}</div>
    <button id="btnRunGoalScenario" class="fin-form-submit" type="button">Simular</button>
    <div id="fmGoalScenarioResult" style="margin-top:12px;"></div>
  `);

  byId("btnRunGoalScenario")?.addEventListener("click", async () => {
    const targetGoalId = Number(byId("fmGoalScenarioGoal")?.value || 0);
    const targetMonth = String(byId("fmGoalScenarioMonth")?.value || "").trim();
    const extraMonthly = Number(byId("fmGoalScenarioExtra")?.value || 0);
    const adjustments = [];
    document.querySelectorAll("[data-goal-sc-row]").forEach((row) => {
      const cat = String(row.querySelector("[data-goal-cat]")?.value || "").trim();
      const pct = Number(row.querySelector("[data-goal-pct]")?.value || 0);
      if (cat && pct > 0) adjustments.push({ category: cat, reduction_pct: pct });
    });

    const resultEl = byId("fmGoalScenarioResult");
    try {
      const resp = await finFetch(`/api/finance/goals/${targetGoalId}/scenario`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ month: targetMonth, extra_monthly: extraMonthly, adjustments }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        if (resultEl) resultEl.innerHTML = `<span class="fin-down">${escapeHtml(data.error || "Erro")}</span>`;
        return;
      }

      if (resultEl) {
        resultEl.innerHTML = `
          <div class="fin-cashflow-kpis">
            <div class="fin-cashflow-kpi"><span>Gap atual</span><strong>${formatBRL(data.goal?.gap || 0)}</strong></div>
            <div class="fin-cashflow-kpi"><span>Prazo base</span><strong>${data.projection?.baseline_months_to_goal ?? "—"} meses</strong></div>
            <div class="fin-cashflow-kpi"><span>Prazo simulado</span><strong class="fin-up">${data.projection?.simulated_months_to_goal ?? "—"} meses</strong></div>
            <div class="fin-cashflow-kpi"><span>Meses ganhos</span><strong class="fin-up">${data.projection?.months_saved ?? "—"}</strong></div>
          </div>
        `;
      }
    } catch {
      if (resultEl) resultEl.innerHTML = '<span class="fin-down">Erro de rede</span>';
    }
  });
}

// ── Category autocomplete ─────────────────────────────
async function loadCashflowCategories() {
  try {
    const data = await fetchFinanceJson("/api/finance/cashflow/categories");
    const cats = Array.isArray(data.categories) ? data.categories : [];
    const subs = Array.isArray(data.subcategories) ? data.subcategories : [];
    FIN._cashflowCategories = cats;
    FIN._cashflowSubcategories = subs;
    _populateCfDatalist("finCfCategoriesDatalist", cats);
    _populateCfDatalist("finCfSubcategoriesDatalist", subs);
  } catch { /* silent */ }
}

function _populateCfDatalist(id, values) {
  const dl = document.getElementById(id);
  if (!dl) return;
  dl.innerHTML = values.map((v) => `<option value="${escapeHtml(v)}"></option>`).join("");
}

function _syncDescriptionDatalist() {
  const entries = Array.isArray(FIN.cashflowEntries) ? FIN.cashflowEntries : [];
  const descs = [...new Set(
    entries.map((e) => String(e.description || "").trim()).filter(Boolean)
  )].sort().slice(0, 100);
  _populateCfDatalist("finCfDescriptionsDatalist", descs);
}

// ── CSV export ────────────────────────────────────────
function exportCashflowCsv() {
  const month = getSelectedCashflowMonth();
  const url = `/api/finance/cashflow/export-csv${month ? "?month=" + encodeURIComponent(month) : ""}`;
  window.open(url, "_blank", "noopener");
}

// ── Monthly Comparison ────────────────────────────────
async function openMonthlyComparisonModal() {
  openFinModal("📊 Comparativo Mensal", `<p style="text-align:center;padding:20px;">Carregando...</p>`);
  let data;
  try {
    const resp = await finFetch("/api/finance/cashflow/monthly-comparison?months=12");
    data = await resp.json();
  } catch {
    showToast("Erro ao carregar comparativo");
    return;
  }
  const rows = Array.isArray(data.data) ? data.data : [];
  if (!rows.length) {
    openFinModal("📊 Comparativo Mensal", `<p class="fin-empty">Nenhum dado disponível.</p>`);
    return;
  }
  const tableRows = rows.map((r) => {
    const balCls = Number(r.balance) >= 0 ? "fin-up" : "fin-down";
    return `<tr>
      <td>${escapeHtml(r.month)}</td>
      <td class="text-right fin-up">${formatBRL(r.income)}</td>
      <td class="text-right fin-down">${formatBRL(r.expense)}</td>
      <td class="text-right ${balCls}">${formatBRL(r.balance)}</td>
    </tr>`;
  }).join("");

  const canvasId = "finMonthlyCompChart";
  openFinModal("📊 Comparativo Mensal", `
    <div class="fin-table-wrap" style="max-height:240px;overflow-y:auto;">
      <table class="fin-table">
        <thead><tr><th>Mês</th><th class="text-right">Receitas</th><th class="text-right">Despesas</th><th class="text-right">Saldo</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
    <div style="margin-top:16px;position:relative;height:220px;">
      <canvas id="${canvasId}"></canvas>
    </div>
  `);

  const canvas = byId(canvasId);
  if (!canvas || typeof Chart === "undefined") return;
  const labels = [...rows].reverse().map((r) => r.month);
  const incomes = [...rows].reverse().map((r) => r.income);
  const expenses = [...rows].reverse().map((r) => r.expense);
  new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Receitas", data: incomes, backgroundColor: "rgba(34,197,94,0.7)", borderRadius: 4 },
        { label: "Despesas", data: expenses, backgroundColor: "rgba(239,68,68,0.7)", borderRadius: 4 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: "#94a3b8" } },
        tooltip: { callbacks: { label: (ctx) => " " + formatBRL(ctx.parsed.y) } },
      },
      scales: {
        x: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(255,255,255,0.04)" } },
        y: { ticks: { color: "#94a3b8", callback: (v) => formatBRL(v) }, grid: { color: "rgba(255,255,255,0.05)" } },
      },
    },
  });
}

// ── Installments ──────────────────────────────────────
function openInstallmentsModal() {
  const today = new Date().toISOString().slice(0, 10);
  openFinModal("📅 Parcelar Lançamento", `
    <form data-form-action="submitInstallments">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmInstType">
            <option value="expense">Gasto</option>
            <option value="income">Receita</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Valor total (R$)</label>
          <input id="fmInstTotal" type="number" min="0.01" step="0.01" placeholder="0,00" required />
        </div>
        <div class="fin-form-group">
          <label>Nº de parcelas</label>
          <input id="fmInstN" type="number" min="2" max="120" value="12" required />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Data da 1ª parcela</label>
          <input id="fmInstFirstDate" type="date" value="${escapeHtml(today)}" required />
        </div>
        <div class="fin-form-group">
          <label>Categoria</label>
          <input id="fmInstCategory" type="text" list="finCfCategoriesDatalist" placeholder="Categoria" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Descrição</label>
        <input id="fmInstDesc" type="text" placeholder="Descrição do parcelamento" />
      </div>
      <div id="fmInstPreview" style="font-size:.85em;color:#94a3b8;margin:4px 0 8px;"></div>
      <button type="submit" class="fin-form-submit">📅 Criar parcelas</button>
    </form>
  `);

  function updatePreview() {
    const total = parseFloat(byId("fmInstTotal")?.value || "0");
    const n = parseInt(byId("fmInstN")?.value || "0", 10);
    const el = byId("fmInstPreview");
    if (!el) return;
    if (total > 0 && n >= 2) {
      const each = Math.round(total / n * 100) / 100;
      const last = Math.round((total - each * (n - 1)) * 100) / 100;
      const lastNote = Math.abs(last - each) > 0.005 ? ` • última ${formatBRL(last)}` : "";
      el.textContent = `${n}× ${formatBRL(each)} = ${formatBRL(total)}${lastNote}`;
    } else {
      el.textContent = "";
    }
  }
  byId("fmInstTotal")?.addEventListener("input", updatePreview);
  byId("fmInstN")?.addEventListener("input", updatePreview);
}

async function submitInstallments(e) {
  e.preventDefault();
  const entry_type = byId("fmInstType")?.value || "expense";
  const total_amount = parseFloat(byId("fmInstTotal")?.value || "0");
  const installments = parseInt(byId("fmInstN")?.value || "0", 10);
  const first_date = byId("fmInstFirstDate")?.value || "";
  const category = byId("fmInstCategory")?.value || "";
  const description = byId("fmInstDesc")?.value || "";

  if (!total_amount || total_amount <= 0) { showToast("Informe o valor total"); return; }
  if (installments < 2) { showToast("Mínimo de 2 parcelas"); return; }
  if (!first_date) { showToast("Informe a data da 1ª parcela"); return; }

  try {
    const resp = await finFetch("/api/finance/cashflow/installments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_type, total_amount, installments, first_date, category, description }),
    });
    const data = await resp.json();
    if (!resp.ok) { showToast(data.error || "Erro ao criar parcelas"); return; }
    showToast(`${data.installments} parcelas criadas com sucesso!`, "success");
    byId("finModalOverlay").style.display = "none";
    await refreshByDomains(["cashflow"]);
  } catch {
    showToast("Erro de rede");
  }
}

// ── Savings Goals ─────────────────────────────────────
async function openSavingsGoalsModal() {
  openFinModal("🎯 Metas de Poupança", `<p style="text-align:center;padding:20px;">Carregando...</p>`);
  let goals;
  try {
    const resp = await finFetch("/api/finance/goals");
    goals = await resp.json();
    if (!Array.isArray(goals)) goals = goals.goals || [];
  } catch {
    showToast("Erro ao carregar metas");
    return;
  }

  function renderGoalsHtml() {
    if (!goals.length) return `<p class="fin-empty">Nenhuma meta cadastrada.</p>`;
    return goals.map((g) => {
      const current = Number(g.current_amount || 0);
      const target = Number(g.target_amount || 0);
      const pct = target > 0 ? Math.min(100, Math.round(current / target * 100)) : 0;
      const color = pct >= 100 ? "#22c55e" : pct >= 50 ? "#f59e0b" : "#3b82f6";
      return `
        <div class="fin-goal-card" style="margin-bottom:14px;padding:12px;border:1px solid rgba(255,255,255,0.1);border-radius:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <strong>${escapeHtml(g.name || "Meta")}</strong>
            <span style="font-size:.85em;color:#94a3b8;">${formatBRL(current)} / ${formatBRL(target)}</span>
          </div>
          <div style="background:rgba(255,255,255,0.08);border-radius:4px;height:8px;margin-bottom:8px;">
            <div style="background:${color};height:8px;border-radius:4px;width:${pct}%;transition:width .3s;"></div>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
            <span style="font-size:.8em;color:#94a3b8;">${pct}% concluído</span>
            <button class="btn-text" style="font-size:.8em;" data-goal-deposit="${g.id}" title="Depositar na meta">＋ Depositar</button>
          </div>
        </div>
      `;
    }).join("");
  }

  const overlay = byId("finModalOverlay");
  const modalBody = overlay?.querySelector(".fin-modal-body");
  if (modalBody) modalBody.innerHTML = renderGoalsHtml();

  overlay?.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-goal-deposit]");
    if (!btn) return;
    const goalId = Number(btn.dataset.goalDeposit);
    const goal = goals.find((g) => Number(g.id) === goalId);
    if (!goal) return;
    const raw = prompt(`Depósito para "${goal.name}" (atual: ${formatBRL(goal.current_amount || 0)})\nValor a depositar (R$):`);
    if (!raw) return;
    const amount = parseFloat(raw.replace(",", "."));
    if (isNaN(amount)) { showToast("Valor inválido"); return; }
    try {
      const resp = await finFetch(`/api/finance/goals/${goalId}/deposit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount }),
      });
      const data = await resp.json();
      if (!resp.ok) { showToast(data.error || "Erro ao depositar"); return; }
      showToast(`Depósito de ${formatBRL(amount)} realizado!`, "success");
      // Update local state
      const g = goals.find((g) => Number(g.id) === goalId);
      if (g) g.current_amount = data.current_amount;
      if (modalBody) modalBody.innerHTML = renderGoalsHtml();
    } catch {
      showToast("Erro de rede");
    }
  }, { once: false });
}

// ── Credit Cards ──────────────────────────────────────
async function openCreditCardsModal() {
  openFinModal("💳 Cartões de Crédito", `<p style="text-align:center;padding:20px;">Carregando...</p>`);
  let cards;
  try {
    const resp = await finFetch("/api/finance/credit-cards");
    cards = await resp.json();
    if (!Array.isArray(cards)) cards = [];
    FIN.creditCards = cards;
    for (const c of cards) {
      try {
        const uResp = await finFetch(`/api/finance/credit-cards/${c.id}/usage`);
        c._usage = uResp.ok ? await uResp.json() : null;
      } catch {
        c._usage = null;
      }
    }
  } catch {
    showToast("Erro ao carregar cartões");
    return;
  }

  function renderCardHtml() {
    const list = cards.length ? cards.map((c) => `
      <div style="margin-bottom:12px;padding:12px;border:1px solid rgba(255,255,255,0.1);border-radius:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong>${escapeHtml(c.name)}</strong>
          <span style="font-size:.85em;color:#94a3b8;">Limite: ${formatBRL(c.limit_amount || 0)}</span>
        </div>
        <div style="font-size:.8em;color:#94a3b8;margin:4px 0;">Fechamento dia ${escapeHtml(String(c.closing_day || "—"))} • Vencimento dia ${escapeHtml(String(c.due_day || "—"))}</div>
        ${c.notes ? `<div style="font-size:.8em;color:#64748b;">${escapeHtml(c.notes)}</div>` : ""}
        ${(() => {
          const spent = Number(c._usage?.spent || 0);
          const limit = Number(c.limit_amount || 0);
          const pct = limit > 0 ? Math.min(100, Math.round((spent / limit) * 100)) : 0;
          const barColor = pct >= 90 ? "#ef4444" : pct >= 70 ? "#f59e0b" : "#22c55e";
          const usageText = limit > 0 ? `${formatBRL(spent)} de ${formatBRL(limit)} (${pct}%)` : `${formatBRL(spent)} usado`;
          return `
            <div style="margin-top:8px;">
              <div style="display:flex;justify-content:space-between;font-size:.78em;color:#94a3b8;margin-bottom:4px;">
                <span>Uso do ciclo</span><span>${usageText}</span>
              </div>
              <div style="height:8px;background:rgba(148,163,184,0.22);border-radius:999px;overflow:hidden;">
                <div style="height:100%;width:${pct}%;background:${barColor};transition:width .25s ease;"></div>
              </div>
            </div>
          `;
        })()}
        <div style="display:flex;gap:6px;margin-top:8px;">
          <button class="btn-text" style="font-size:.8em;" data-card-edit="${c.id}">✎ Editar</button>
          <button class="btn-text" style="font-size:.8em;color:#ef4444;" data-card-delete="${c.id}">✕ Excluir</button>
        </div>
      </div>
    `).join("") : `<p class="fin-empty">Nenhum cartão cadastrado.</p>`;
    return `
      ${list}
      <hr style="border-color:rgba(255,255,255,0.08);margin:12px 0;" />
      <form data-form-action="submitAddCreditCard" style="margin-top:8px;">
        <div class="fin-form-row">
          <div class="fin-form-group"><label>Nome</label><input id="fmCardName" type="text" placeholder="Nome do cartão" required /></div>
          <div class="fin-form-group"><label>Limite (R$)</label><input id="fmCardLimit" type="number" min="0" step="0.01" placeholder="0,00" /></div>
        </div>
        <div class="fin-form-row">
          <div class="fin-form-group"><label>Dia fechamento</label><input id="fmCardClosing" type="number" min="1" max="31" value="1" /></div>
          <div class="fin-form-group"><label>Dia vencimento</label><input id="fmCardDue" type="number" min="1" max="31" value="10" /></div>
        </div>
        <div class="fin-form-group"><label>Notas</label><input id="fmCardNotes" type="text" placeholder="Opcional" /></div>
        <button type="submit" class="fin-form-submit">＋ Adicionar cartão</button>
      </form>
    `;
  }

  const overlay = byId("finModalOverlay");
  const modalBody = overlay?.querySelector(".fin-modal-body");
  if (modalBody) modalBody.innerHTML = renderCardHtml();

  overlay?.addEventListener("click", async (e) => {
    const editBtn = e.target.closest("[data-card-edit]");
    const delBtn = e.target.closest("[data-card-delete]");
    if (editBtn) {
      const cid = Number(editBtn.dataset.cardEdit);
      const card = cards.find((c) => Number(c.id) === cid);
      if (!card) return;
      const newName = prompt("Nome:", card.name);
      if (!newName) return;
      const newLimit = prompt("Limite (R$):", card.limit_amount);
      const newClosing = prompt("Dia de fechamento:", card.closing_day);
      const newDue = prompt("Dia de vencimento:", card.due_day);
      try {
        const resp = await finFetch(`/api/finance/credit-cards/${cid}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: newName,
            limit_amount: parseFloat(newLimit) || 0,
            closing_day: parseInt(newClosing) || 1,
            due_day: parseInt(newDue) || 10,
          }),
        });
        const data = await resp.json();
        if (!resp.ok) { showToast(data.error || "Erro ao atualizar"); return; }
        showToast("Cartão atualizado!", "success");
        const idx = cards.findIndex((c) => Number(c.id) === cid);
        if (idx >= 0) {
          cards[idx] = { ...cards[idx], name: newName, limit_amount: parseFloat(newLimit) || 0, closing_day: parseInt(newClosing) || 1, due_day: parseInt(newDue) || 10 };
        }
        FIN.creditCards = cards;
        if (modalBody) modalBody.innerHTML = renderCardHtml();
      } catch { showToast("Erro de rede"); }
    }
    if (delBtn) {
      const cid = Number(delBtn.dataset.cardDelete);
      const card = cards.find((c) => Number(c.id) === cid);
      if (!card) return;
      withUndoDelete(`Cartão "${card.name}" será excluído.`, async () => {
        try {
          const resp = await finFetch(`/api/finance/credit-cards/${cid}`, { method: "DELETE" });
          const data = await resp.json();
          if (!resp.ok) { showToast(data.error || "Erro ao excluir"); return; }
          showToast("Cartão excluído.", "success");
          cards = cards.filter((c) => Number(c.id) !== cid);
          FIN.creditCards = cards;
          if (modalBody) modalBody.innerHTML = renderCardHtml();
        } catch { showToast("Erro de rede"); }
      });
    }
  }, { once: false });
}

async function submitAddCreditCard(e) {
  e.preventDefault();
  const name = byId("fmCardName")?.value || "";
  const limit_amount = parseFloat(byId("fmCardLimit")?.value || "0");
  const closing_day = parseInt(byId("fmCardClosing")?.value || "1", 10);
  const due_day = parseInt(byId("fmCardDue")?.value || "10", 10);
  const notes = byId("fmCardNotes")?.value || "";
  if (!name.trim()) { showToast("Informe o nome do cartão"); return; }
  try {
    const resp = await finFetch("/api/finance/credit-cards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, limit_amount, closing_day, due_day, notes }),
    });
    const data = await resp.json();
    if (!resp.ok) { showToast(data.error || "Erro ao adicionar cartão"); return; }
    showToast("Cartão adicionado!", "success");
    await openCreditCardsModal();
  } catch { showToast("Erro de rede"); }
}

// ── Split Cashflow Entry ───────────────────────────────
async function openSplitCashflowModal(entryId) {
  const entry = (FIN.cashflowEntries || []).find((e) => Number(e.id) === Number(entryId));
  const amount = Number(entry?.amount || 0);
  const label = entry ? `${entry.description || entry.category || "Lançamento"} (${formatBRL(amount)})` : `#${entryId}`;

  openFinModal("↕ Dividir Lançamento", `
    <div style="margin-bottom:12px;font-size:.9em;color:#94a3b8;">Dividindo: <strong>${escapeHtml(label)}</strong></div>
    <form data-form-action="submitSplitCashflow" data-entry-id="${entryId}" data-total="${amount}">
      <div id="splitPartsContainer"></div>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <button id="btnAddSplitPart" type="button" class="btn-text">＋ Adicionar parte</button>
        <span id="splitRemaining" style="font-size:.85em;color:#94a3b8;align-self:center;"></span>
      </div>
      <button type="submit" class="fin-form-submit">↕ Dividir</button>
    </form>
  `);

  function addPart(suggestedAmount) {
    const container = byId("splitPartsContainer");
    if (!container) return;
    const idx = container.querySelectorAll(".split-part-row").length;
    const row = document.createElement("div");
    row.className = "split-part-row fin-form-row";
    row.style.cssText = "align-items:flex-end;gap:8px;";
    row.innerHTML = `
      <div class="fin-form-group" style="flex:1.5;">
        <label>Categoria</label>
        <input class="split-category" type="text" list="finCfCategoriesDatalist" value="${escapeHtml(entry?.category || "")}" placeholder="Categoria" />
      </div>
      <div class="fin-form-group" style="flex:1;">
        <label>Valor (R$)</label>
        <input class="split-amount" type="number" min="0.01" step="0.01" value="${escapeHtml(String(suggestedAmount || ""))}" required />
      </div>
      <div class="fin-form-group" style="flex:1.5;">
        <label>Descrição</label>
        <input class="split-desc" type="text" value="${escapeHtml(entry?.description || "")}" placeholder="Opcional" />
      </div>
      <button type="button" class="fin-del-btn split-remove" title="Remover">✕</button>
    `;
    container.appendChild(row);
    row.querySelector(".split-amount")?.addEventListener("input", updateRemaining);
    row.querySelector(".split-remove")?.addEventListener("click", () => { row.remove(); updateRemaining(); });
  }

  function updateRemaining() {
    const parts = [...document.querySelectorAll(".split-amount")];
    const used = parts.reduce((s, el) => s + (parseFloat(el.value) || 0), 0);
    const rem = Math.round((amount - used) * 100) / 100;
    const el = byId("splitRemaining");
    if (el) el.textContent = `Restante: ${formatBRL(rem)}`;
  }

  byId("btnAddSplitPart")?.addEventListener("click", () => {
    const parts = [...document.querySelectorAll(".split-amount")];
    const used = parts.reduce((s, el) => s + (parseFloat(el.value) || 0), 0);
    const rem = Math.round((amount - used) * 100) / 100;
    addPart(rem > 0 ? rem : "");
    updateRemaining();
  });

  // Start with 2 parts
  addPart(Math.round(amount / 2 * 100) / 100);
  addPart(Math.round(amount / 2 * 100) / 100);
  updateRemaining();
}

async function submitSplitCashflow(e) {
  e.preventDefault();
  const entryId = Number(e.target.dataset.entryId);
  const totalAmount = parseFloat(e.target.dataset.total || "0");
  const partRows = [...e.target.querySelectorAll(".split-part-row")];
  const parts = partRows.map((row) => ({
    amount: parseFloat(row.querySelector(".split-amount")?.value || "0"),
    category: row.querySelector(".split-category")?.value || "",
    description: row.querySelector(".split-desc")?.value || "",
  }));

  if (parts.length < 2) { showToast("Adicione pelo menos 2 partes"); return; }
  const sumParts = parts.reduce((s, p) => s + p.amount, 0);
  if (Math.abs(sumParts - totalAmount) > 0.02) {
    showToast(`Soma das partes (${formatBRL(sumParts)}) deve ser igual ao valor original (${formatBRL(totalAmount)})`);
    return;
  }

  try {
    const resp = await finFetch(`/api/finance/cashflow/${entryId}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parts }),
    });
    const data = await resp.json();
    if (!resp.ok) { showToast(data.error || "Erro ao dividir"); return; }
    showToast(`Lançamento dividido em ${data.created_ids.length} partes!`, "success");
    byId("finModalOverlay").style.display = "none";
    await refreshByDomains(["cashflow"]);
  } catch {
    showToast("Erro de rede");
  }
}

document.addEventListener("blur", (e) => {
  const inp = e.target;
  if (!(inp instanceof HTMLInputElement) || inp.type !== "number") return;
  if (!inp.closest("#finModalOverlay, .fin-modal")) return;
  const val = parseFloat(inp.value);
  if (!isNaN(val) && val > 0) {
    let hint = inp.nextElementSibling;
    if (!(hint instanceof HTMLElement) || !hint.classList.contains("fin-brl-hint")) {
      hint = document.createElement("span");
      hint.className = "fin-brl-hint";
      hint.style.cssText = "font-size:.78em;color:#94a3b8;display:block;margin-top:2px;";
      inp.after(hint);
    }
    hint.textContent = formatBRL(val);
  }
}, true);

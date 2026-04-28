/* ══════════════════════════════════════════════════════════
   Finance Cashflow Domain
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
  if (!rows.length) {
    el.innerHTML = renderEmptyState(
      "Nenhum lançamento de ganhos/gastos para este mês.",
      "Adicionar lançamento",
      "addCashflow",
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
        <td>${escapeHtml(entry.description || "—")}</td>
        <td class="text-right mono ${amountCls}">${formatBRL(entry.amount || 0)}</td>
        <td>${escapeHtml(entry.notes || "")}</td>
        <td class="text-center">
          <button class="fin-del-btn" data-action="toggleCashflowStatus" data-id="${entry.id}" data-status="${status.nextStatus}" title="${status.actionLabel}">✓</button>
          <button class="fin-del-btn" data-action="openCashflowAttachmentModal" data-id="${entry.id}" title="Anexos">📎</button>
          <button class="fin-del-btn" data-action="openEditCashflowModal" data-id="${entry.id}" title="Editar">✎</button>
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
  openFinModal("Novo Lançamento (Ganho/Gasto)", `
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
          <input id="fmCfCategory" placeholder="Ex.: Salário, Moradia, Alimentação" value="${escapeHtml(_pcat)}" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Subcategoria</label>
          <input id="fmCfSubcategory" placeholder="Ex.: Condomínio" />
        </div>
        <div class="fin-form-group">
          <label>Centro de custo</label>
          <input id="fmCfCostCenter" placeholder="Ex.: Casa" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Descrição</label>
        <input id="fmCfDescription" placeholder="Resumo do lançamento" value="${escapeHtml(_pdesc)}" required />
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

  openFinModal("Orçamento Mensal por Categoria", `
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

  openFinModal("🔁 Lançamentos Recorrentes", `
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
  openFinModal("Virada de Mês (Lançamentos Recorrentes)", `
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
    <div class="fin-form-group">
      <label>Imagem do comprovante (JPG, PNG, até 5 MB)</label>
      <input id="fmOcrFile" type="file" accept="image/*" />
    </div>
    <div class="fin-form-group">
      <label>Texto manual (fallback opcional)</label>
      <textarea id="fmOcrManualText" rows="4" placeholder="Cole aqui o texto do comprovante caso o OCR não esteja disponível."></textarea>
    </div>
    <button id="btnDoOcr" class="fin-form-submit" type="button">🔍 Analisar</button>
    <div id="fmOcrResult" style="margin-top:12px"></div>
  `);

  byId("btnDoOcr")?.addEventListener("click", async () => {
    const fileEl = byId("fmOcrFile");
    const manualText = String(byId("fmOcrManualText")?.value || "").trim();
    if (!fileEl?.files?.length && !manualText) {
      showToast("Selecione uma imagem ou preencha o texto manual");
      return;
    }
    const btnDoOcr = byId("btnDoOcr");
    if (btnDoOcr) { btnDoOcr.disabled = true; btnDoOcr.textContent = "Analisando…"; }
    const formData = new FormData();
    if (fileEl?.files?.length) formData.append("file", fileEl.files[0]);
    if (manualText) formData.append("manual_text", manualText);
    try {
      const resp = await finFetch("/api/finance/cashflow/ocr", { method: "POST", body: formData });
      const data = await resp.json();
      const resultEl = byId("fmOcrResult");
      if (!resp.ok || !data.ok) {
        const msg = data.pytesseract_missing
          ? "pytesseract não instalado no servidor. " + (data.error || "")
          : (data.error || "Erro ao processar imagem.");
        if (resultEl) resultEl.innerHTML = `<span class="fin-down">${escapeHtml(msg)}</span>`;
        return;
      }
      if (resultEl) resultEl.innerHTML = `
        <div class="fin-alert fin-alert-info" style="font-size:.85em;">
          <strong>Extraído:</strong><br>
          Data: ${escapeHtml(data.date || "não encontrada")}<br>
          Valor: ${data.amount != null ? formatBRL(data.amount) : "não encontrado"}<br>
          Estabelecimento: ${escapeHtml(data.merchant || "—")}<br>
          Categoria: ${escapeHtml(data.category || "—")}<br>
          Descrição: ${escapeHtml(data.description || "—")}<br>
          Confiança: ${data.confidence != null ? `${Math.round(Number(data.confidence) * 100)}%` : "—"}
          ${data.raw_text ? `<details style="margin-top:6px;"><summary>Texto bruto</summary><pre style="white-space:pre-wrap;font-size:.75em;">${escapeHtml(data.raw_text)}</pre></details>` : ""}
        </div>
        <button id="btnOcrPrefill" class="fin-form-submit" type="button" style="margin-top:10px;">✚ Criar lançamento com estes dados</button>
      `;
      byId("btnOcrPrefill")?.addEventListener("click", () => {
        openAddCashflowModal({
          entry_date: data.date || "",
          amount: data.amount != null ? String(data.amount) : "",
          description: data.description || "",
          category: data.category || "",
          entry_type: "expense",
        });
      });
    } catch { showToast("Erro de rede"); }
    finally {
      if (btnDoOcr) { btnDoOcr.disabled = false; btnDoOcr.textContent = "🔍 Analisar"; }
    }
  });
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

  openFinModal("🔮 Simulador de Cenários", `
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
  openFinModal("📥 Importar Extratos (CSV / OFX)", `
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
    <button id="btnDoImport" class="fin-form-submit" type="button">📥 Importar</button>
    <div id="fmImportResult" style="margin-top:12px"></div>
  `);

  byId("btnDoImport")?.addEventListener("click", async () => {
    const importMonth = String(byId("fmImportMonth")?.value || "").trim();
    const fileEl = byId("fmImportFile");
    if (!fileEl?.files?.length) {
      showToast("Selecione um arquivo");
      return;
    }
    const formData = new FormData();
    formData.append("file", fileEl.files[0]);
    try {
      const resp = await finFetch(`/api/finance/cashflow/import?month=${encodeURIComponent(importMonth)}`, {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      const resultEl = byId("fmImportResult");
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
              <br>Estes lançamentos já existem com data ±3 dias e mesmo valor. Use <code>?force=1</code> na URL para forçar importação.
              <ul style="margin:4px 0 0 16px;">${data.potential_duplicates.map((p) =>
                `<li>${escapeHtml(p.candidate.entry_date)} • R$ ${Number(p.candidate.amount).toFixed(2)} • ${escapeHtml(p.candidate.description || "")}</li>`
              ).join("")}</ul>
            </div>`
          : "";
        resultEl.innerHTML = `
          <span class="fin-up">✓ ${data.imported} lançamento(s) importado(s).</span>
          ${dupHtml}
          ${data.errors?.length ? `<span class="fin-down"> ${data.errors.length} erro(s):</span>${errHtml}` : ""}
        `;
      }
      if (data.imported > 0) await refreshByDomains(["cashflow"]);
    } catch {
      showToast("Erro de rede");
    }
  });
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

  openFinModal("📎 Anexos do Lançamento", `
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
  openFinModal("Editar Lançamento", `
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
          <input id="fmCfCategory" value="${escapeHtml(entry.category || "")}" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Subcategoria</label>
          <input id="fmCfSubcategory" value="${escapeHtml(entry.subcategory || "")}" />
        </div>
        <div class="fin-form-group">
          <label>Centro de custo</label>
          <input id="fmCfCostCenter" value="${escapeHtml(entry.cost_center || "")}" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Descrição</label>
        <input id="fmCfDescription" value="${escapeHtml(entry.description || "")}" required />
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
  if (!confirm("Excluir este lançamento?")) return;
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
  openFinModal("🗓 Plano Mensal Automático", `
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

async function openCashflowSavedFiltersModal() {
  const current = _collectCurrentCashflowFilter();
  let rows = [];
  try {
    const resp = await finFetch("/api/finance/cashflow/saved-filters");
    if (resp.ok) rows = await resp.json();
  } catch { /* ignore */ }

  const listHtml = (rows || []).length
    ? rows.map((r) => `
      <tr>
        <td>${escapeHtml(r.name || "Filtro")}</td>
        <td>${escapeHtml(JSON.stringify(r.filter || {}))}</td>
        <td class="text-center">
          <button class="fin-del-btn" data-action="applyCashflowSavedFilter" data-id="${r.id}" title="Aplicar">✓</button>
          <button class="fin-del-btn" data-action="deleteCashflowSavedFilter" data-id="${r.id}" title="Excluir">✕</button>
        </td>
      </tr>
    `).join("")
    : '<tr><td colspan="3" class="text-center">Nenhum filtro salvo</td></tr>';

  openFinModal("🔖 Filtros Salvos do Cashflow", `
    <div class="fin-form-group">
      <label>Nome do filtro atual</label>
      <input id="fmCashflowFilterName" placeholder="Ex.: Casa pendentes" />
      <small style="display:block;opacity:.7;margin-top:4px;">Filtro atual: ${escapeHtml(JSON.stringify(current))}</small>
    </div>
    <button id="btnSaveCashflowFilter" class="fin-form-submit" type="button">Salvar filtro atual</button>
    <div class="fin-table-wrap" style="max-height:260px;overflow:auto;margin-top:12px;">
      <table class="fin-table">
        <thead><tr><th>Nome</th><th>Conteúdo</th><th></th></tr></thead>
        <tbody id="fmCashflowSavedFiltersRows">${listHtml}</tbody>
      </table>
    </div>
  `);

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

  const modal = document.querySelector("#finModalBody");
  modal?.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const id = Number(btn.dataset.id || 0);
    if (btn.dataset.action === "applyCashflowSavedFilter") {
      const item = (rows || []).find((x) => Number(x.id) === id);
      if (!item) return;
      _applyCashflowFilter(item.filter || {});
      closeFinModal();
      await refreshByDomains(["cashflow"]);
      showToast("Filtro aplicado", "success");
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
  }, { once: true });
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

  openFinModal("🧩 Ações em Lote (Cashflow)", `
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

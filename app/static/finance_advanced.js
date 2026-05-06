/* ══════════════════════════════════════════════════════════
  Advanced Filters + Templates + Alerts + Analytics
  ══════════════════════════════════════════════════════════ */

// === ADVANCED FILTERS UI ===

function renderCashflowFiltersPanel() {
  return `
    <div id="finAdvancedFilters" style="border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px;margin-bottom:12px;background:rgba(0,0,0,0.3);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <h4 style="margin:0;font-size:.95em;">🔍 Filtros Avançados</h4>
        <button id="btnToggleFilters" class="btn-text" style="font-size:.8em;" title="Minimizar">−</button>
      </div>
      <div id="finFilterFields" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;">
        <div class="fin-form-group">
          <label style="font-size:.8em;">Data Inicial</label>
          <input id="filterDateFrom" type="date" />
        </div>
        <div class="fin-form-group">
          <label style="font-size:.8em;">Data Final</label>
          <input id="filterDateTo" type="date" />
        </div>
        <div class="fin-form-group">
          <label style="font-size:.8em;">Categoria</label>
          <select id="filterCategory">
            <option value="">Todas</option>
            ${(() => {
              const cats = FIN._cashflowCategories || [];
              return cats.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
            })()}
          </select>
        </div>
        <div class="fin-form-group">
          <label style="font-size:.8em;">Cartão</label>
          <select id="filterCreditCard">
            <option value="">Todos</option>
            ${(() => {
              const cards = FIN.creditCards || [];
              return cards.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
            })()}
          </select>
        </div>
        <div class="fin-form-group">
          <label style="font-size:.8em;">Conta</label>
          <select id="filterAccount">
            <option value="">Todas</option>
            ${(() => {
              const accounts = FIN.accounts || [];
              return accounts.map((a) => `<option value="${a.id}">${escapeHtml(a.name || `Conta ${a.id}`)}</option>`).join("");
            })()}
          </select>
        </div>
        <div class="fin-form-group">
          <label style="font-size:.8em;">Valor Mín (R$)</label>
          <input id="filterAmountMin" type="number" min="0" step="0.01" />
        </div>
        <div class="fin-form-group">
          <label style="font-size:.8em;">Valor Máx (R$)</label>
          <input id="filterAmountMax" type="number" min="0" step="0.01" />
        </div>
      </div>
      <div style="display:flex;gap:6px;margin-top:10px;">
        <button id="btnApplyFilters" class="fin-form-submit" style="flex:1;font-size:.85em;">Aplicar Filtros</button>
        <button id="btnClearFilters" class="btn-text" style="font-size:.85em;">Limpar</button>
        <button id="btnSaveFilter" class="btn-text" style="font-size:.85em;">Salvar</button>
      </div>
    </div>
  `;
}

async function initAdvancedFilters() {
  const panel = byId("finAdvancedFilters");
  if (!panel) return;

  byId("btnToggleFilters")?.addEventListener("click", () => {
    const fields = byId("finFilterFields");
    if (fields) fields.style.display = fields.style.display === "none" ? "grid" : "none";
  });

  byId("btnApplyFilters")?.addEventListener("click", () => applyAdvancedFilters());
  byId("btnClearFilters")?.addEventListener("click", () => clearAdvancedFilters());
  byId("btnSaveFilter")?.addEventListener("click", () => openSaveFilterModal());
}

async function applyAdvancedFilters() {
  const filters = {
    date_from: String(byId("filterDateFrom")?.value || "").trim(),
    date_to: String(byId("filterDateTo")?.value || "").trim(),
    category: String(byId("filterCategory")?.value || "").trim(),
    credit_card_id: String(byId("filterCreditCard")?.value || "").trim(),
    account_id: String(byId("filterAccount")?.value || "").trim(),
    amount_min: String(byId("filterAmountMin")?.value || "").trim(),
    amount_max: String(byId("filterAmountMax")?.value || "").trim(),
  };

  const queryParams = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v) queryParams.append(k, v);
  });

  try {
    const resp = await finFetch(`/api/finance/cashflow?${queryParams.toString()}`);
    if (!resp.ok) {
      showToast("Erro ao aplicar filtros");
      return;
    }
    const data = await resp.json();
    FIN.cashflowEntries = Array.isArray(data) ? data : [];
    renderCashflow(FIN.cashflowEntries);
    showToast("Filtros aplicados!", "success");
  } catch {
    showToast("Erro ao filtrar");
  }
}

function clearAdvancedFilters() {
  byId("filterDateFrom").value = "";
  byId("filterDateTo").value = "";
  byId("filterCategory").value = "";
  byId("filterCreditCard").value = "";
  byId("filterAccount").value = "";
  byId("filterAmountMin").value = "";
  byId("filterAmountMax").value = "";
  showToast("Filtros limpos", "success");
}

// === SAVE FILTER ===

function openSaveFilterModal() {
  openFinModal("Salvar Filtro", `
    <form data-form-action="submitSaveFilter">
      <div class="fin-form-group">
        <label>Nome do Filtro</label>
        <input id="fmFilterName" type="text" placeholder="Ex.: Gastos maiores que 100" required />
      </div>
      <div class="fin-form-group" style="display:flex;align-items:center;gap:8px;margin:8px 0;">
        <input id="fmFilterFavorite" type="checkbox" />
        <label style="margin:0;">Marcar como favorito</label>
      </div>
      <button type="submit" class="fin-form-submit">Salvar Filtro</button>
    </form>
  `);
}

async function submitSaveFilter(e) {
  e.preventDefault();
  const name = String(byId("fmFilterName")?.value || "").trim();
  const isFav = byId("fmFilterFavorite")?.checked || false;

  const filters = {
    date_from: String(byId("filterDateFrom")?.value || "").trim(),
    date_to: String(byId("filterDateTo")?.value || "").trim(),
    category: String(byId("filterCategory")?.value || "").trim(),
    credit_card_id: String(byId("filterCreditCard")?.value || "").trim(),
    account_id: String(byId("filterAccount")?.value || "").trim(),
    amount_min: String(byId("filterAmountMin")?.value || "").trim(),
    amount_max: String(byId("filterAmountMax")?.value || "").trim(),
  };

  if (!name) {
    showToast("Informe o nome do filtro");
    return;
  }

  try {
    const resp = await finFetch("/api/finance/filters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: `cashflow:${name}`,
        filter: filters,
        is_favorite: isFav,
      }),
    });
    if (!resp.ok) throw new Error("Failed");
    showToast("Filtro salvo!", "success");
    closeFinModal();
  } catch {
    showToast("Erro ao salvar filtro");
  }
}

// === TEMPLATES (Save as template) ===

function openSaveAsTemplateModal(entryId) {
  const entry = (FIN.cashflowEntries || []).find((e) => Number(e.id) === Number(entryId));
  if (!entry) return;

  openFinModal("Salvar como Template", `
    <form data-form-action="submitSaveAsTemplate" data-entry-id="${entryId}">
      <div class="fin-form-group">
        <label>Nome do Template</label>
        <input id="fmTemplateName" type="text" placeholder="Ex.: Pagamento Netflix" required />
      </div>
      <div class="fin-form-group">
        <label>Usar valor padrão?</label>
        <div style="display:flex;gap:8px;margin-top:4px;">
          <button type="button" class="btn-text" id="btnUseValue" style="flex:1;">Sim (${formatBRL(entry.amount)})</button>
          <button type="button" class="btn-text" id="btnSkipValue" style="flex:1;">Não (pedir valor)</button>
        </div>
        <input id="fmTemplateFixedAmount" type="hidden" value="${entry.amount}" />
      </div>
      <button type="submit" class="fin-form-submit">Salvar Template</button>
    </form>
  `);

  byId("btnUseValue")?.addEventListener("click", () => {
    byId("fmTemplateFixedAmount").value = String(entry.amount);
    byId("btnUseValue").style.opacity = "1";
    byId("btnSkipValue").style.opacity = "0.5";
  });

  byId("btnSkipValue")?.addEventListener("click", () => {
    byId("fmTemplateFixedAmount").value = "";
    byId("btnSkipValue").style.opacity = "1";
    byId("btnUseValue").style.opacity = "0.5";
  });
}

async function submitSaveAsTemplate(e, entryId) {
  e.preventDefault();
  const entry = (FIN.cashflowEntries || []).find((e) => Number(e.id) === Number(entryId));
  if (!entry) return;

  const name = String(byId("fmTemplateName")?.value || "").trim();
  const fixedAmount = String(byId("fmTemplateFixedAmount")?.value || "").trim();

  if (!name) {
    showToast("Informe o nome do template");
    return;
  }

  const template = {
    name,
    entry_type: entry.entry_type,
    category: entry.category,
    subcategory: entry.subcategory,
    description: entry.description,
    tags: entry.tags,
    cost_center: entry.cost_center,
    fixed_amount: fixedAmount ? parseFloat(fixedAmount) : null,
  };

  localStorage.setItem(`cashflow_template_${Date.now()}`, JSON.stringify(template));
  showToast("Template salvo!", "success");
  closeFinModal();
}

function applyTemplate(templateJson) {
  try {
    const template = JSON.parse(templateJson);
    const prefill = {
      entry_type: template.entry_type,
      category: template.category,
      subcategory: template.subcategory,
      description: template.description,
      amount: template.fixed_amount || "",
    };
    openAddCashflowModal(prefill);
  } catch {
    showToast("Erro ao aplicar template");
  }
}

// === BUDGET ALERTS ===

function checkBudgetAlerts() {
  const budget = FIN.cashflowBudget || {};
  const analytics = FIN.cashflowAnalytics || {};
  const expenses = Array.isArray(analytics.categories?.expense) ? analytics.categories.expense : [];

  expenses.forEach((cat) => {
    const catName = String(cat.category || "").trim();
    const spent = Number(cat.amount || 0);
    const limit = Number(budget[catName] || 0);

    if (limit <= 0) return;

    const pct = Math.round((spent / limit) * 100);

    if (pct >= 100) {
      showToast(`⚠️ Orçamento de "${catName}" ULTRAPASSADO! (${formatBRL(spent)} de ${formatBRL(limit)})`, "error", { timeout: 10000 });
    } else if (pct >= 90) {
      showToast(`⚠️ "${catName}" em ${pct}% do orçamento (${formatBRL(spent)} de ${formatBRL(limit)})`, "warn", { timeout: 8000 });
    } else if (pct >= 70) {
      showToast(`💡 "${catName}" em ${pct}% do orçamento`, "info", { timeout: 5000 });
    }
  });
}

// === DASHBOARD QUICK STATS ===

function renderQuickStatsPanel() {
  const analytics = FIN.cashflowAnalytics || {};
  const summary = FIN.cashflowSummary || {};
  const expenses = Array.isArray(analytics.categories?.expense) ? analytics.categories.expense : [];

  const topExpense = expenses.sort((a, b) => (b.amount || 0) - (a.amount || 0))[0];
  const income = Number(summary.current_income || 0);
  const expense = Number(summary.current_expense || 0);
  const balance = Number(summary.current_balance || 0);

  const changeIndicator = (current, prev) => {
    if (!prev) return "—";
    const diff = current - prev;
    const icon = diff > 0 ? "📈" : diff < 0 ? "📉" : "→";
    return `${icon} ${formatBRL(Math.abs(diff))}`;
  };

  return `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px;">
      <div style="border:1px solid #22c55e;border-radius:6px;padding:10px;background:rgba(34,197,94,0.1);">
        <div style="font-size:.75em;color:#94a3b8;text-transform:uppercase;">Ganhos</div>
        <div style="font-size:1.2em;font-weight:bold;color:#22c55e;">${formatBRL(income)}</div>
        <div style="font-size:.7em;color:#64748b;margin-top:2px;">Este mês</div>
      </div>
      <div style="border:1px solid #ef4444;border-radius:6px;padding:10px;background:rgba(239,68,68,0.1);">
        <div style="font-size:.75em;color:#94a3b8;text-transform:uppercase;">Gastos</div>
        <div style="font-size:1.2em;font-weight:bold;color:#ef4444;">${formatBRL(expense)}</div>
        <div style="font-size:.7em;color:#64748b;margin-top:2px;">Este mês</div>
      </div>
      <div style="border:1px solid ${balance >= 0 ? "#3b82f6" : "#ef4444"};border-radius:6px;padding:10px;background:rgba(59,130,246,0.1);">
        <div style="font-size:.75em;color:#94a3b8;text-transform:uppercase;">Saldo</div>
        <div style="font-size:1.2em;font-weight:bold;color:${balance >= 0 ? "#3b82f6" : "#ef4444"};">${formatBRL(balance)}</div>
        <div style="font-size:.7em;color:#64748b;margin-top:2px;">Mês atual</div>
      </div>
      ${
        topExpense
          ? `
        <div style="border:1px solid #f59e0b;border-radius:6px;padding:10px;background:rgba(245,158,11,0.1);">
          <div style="font-size:.75em;color:#94a3b8;text-transform:uppercase;">Top Gasto</div>
          <div style="font-size:.95em;font-weight:bold;color:#f59e0b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(topExpense.category || "—")}</div>
          <div style="font-size:.8em;color:#64748b;margin-top:2px;">${formatBRL(topExpense.amount || 0)}</div>
        </div>
      `
          : ""
      }
    </div>
  `;
}

// === CSV IMPORT ===

function openCSVImportModal() {
  openFinModal("📥 Importar CSV", `
    <form data-form-action="submitCSVImport">
      <div class="fin-form-group">
        <label>Selecione o arquivo CSV</label>
        <input id="fmCSVFile" type="file" accept=".csv" required />
        <small style="display:block;margin-top:4px;color:#94a3b8;">Formato: data,tipo,categoria,valor,descrição (separado por vírgula)</small>
      </div>
      <div id="csvPreview" style="max-height:300px;overflow-y:auto;margin:10px 0;border:1px solid rgba(255,255,255,0.1);border-radius:4px;padding:8px;display:none;"></div>
      <button type="submit" class="fin-form-submit">Importar Lançamentos</button>
    </form>
  `);

  byId("fmCSVFile")?.addEventListener("change", (e) => previewCSVImport(e));
}

function previewCSVImport(e) {
  const file = e.target.files?.[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (evt) => {
    try {
      const csv = evt.target?.result || "";
      const lines = csv.split("\n").slice(0, 6);
      const preview = byId("csvPreview");
      if (preview) {
        preview.style.display = "block";
        preview.innerHTML = lines.map((line) => `<div style="font-size:.8em;padding:2px 0;color:#94a3b8;">${escapeHtml(line)}</div>`).join("");
      }
    } catch {
      /* ignore */
    }
  };
  reader.readAsText(file);
}

async function submitCSVImport(e) {
  e.preventDefault();
  const file = byId("fmCSVFile")?.files?.[0];
  if (!file) {
    showToast("Selecione um arquivo");
    return;
  }

  const text = await file.text();
  const lines = text.split("\n").filter((l) => l.trim());

  let imported = 0;
  let errors = 0;

  for (const line of lines) {
    const parts = line.split(",").map((p) => p.trim());
    if (parts.length < 4) continue;

    const [date, type, category, amount, desc] = parts;

    try {
      const resp = await finFetch("/api/finance/cashflow", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entry_date: date,
          entry_type: type === "receita" || type === "income" ? "income" : "expense",
          category: category,
          description: desc || category,
          amount: parseFloat(amount),
          payment_status: "pending",
        }),
      });

      if (resp.ok) imported++;
      else errors++;
    } catch {
      errors++;
    }
  }

  showToast(`Importados: ${imported} | Erros: ${errors}`, imported > 0 ? "success" : "error");
  closeFinModal();
  if (imported > 0) {
    await refreshByDomains(["cashflow"]);
  }
}

// === ANALYTICS PANEL ===

function renderAnalyticsPanel() {
  const analytics = FIN.cashflowAnalytics || {};
  const expenses = Array.isArray(analytics.categories?.expense) ? analytics.categories.expense : [];
  const income = Array.isArray(analytics.categories?.income) ? analytics.categories.income : [];

  const totalExp = expenses.reduce((s, x) => s + (x.amount || 0), 0);
  const totalInc = income.reduce((s, x) => s + (x.amount || 0), 0);

  const topExpByDay = "N/A";
  const avgDailyExp = totalExp / 30;

  return `
    <div style="border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px;margin:16px 0;background:rgba(0,0,0,0.3);">
      <h4 style="margin:0 0 10px 0;font-size:.95em;">📊 Analytics & Insights</h4>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;font-size:.85em;">
        <div>
          <div style="color:#94a3b8;font-size:.75em;text-transform:uppercase;margin-bottom:4px;">Gasto Médio/Dia</div>
          <div style="font-size:1.1em;font-weight:bold;color:#ef4444;">${formatBRL(avgDailyExp)}</div>
        </div>
        <div>
          <div style="color:#94a3b8;font-size:.75em;text-transform:uppercase;margin-bottom:4px;">Total Gastos</div>
          <div style="font-size:1.1em;font-weight:bold;color:#ef4444;">${formatBRL(totalExp)}</div>
        </div>
        <div>
          <div style="color:#94a3b8;font-size:.75em;text-transform:uppercase;margin-bottom:4px;">Total Ganhos</div>
          <div style="font-size:1.1em;font-weight:bold;color:#22c55e;">${formatBRL(totalInc)}</div>
        </div>
        <div>
          <div style="color:#94a3b8;font-size:.75em;text-transform:uppercase;margin-bottom:4px;">Razão Gasto</div>
          <div style="font-size:1.1em;font-weight:bold;color:#3b82f6;">${totalInc > 0 ? Math.round((totalExp / totalInc) * 100) : 0}%</div>
        </div>
      </div>
    </div>
  `;
}

console.log("✓ Advanced filters, templates, alerts & analytics loaded");

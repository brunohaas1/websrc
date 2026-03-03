/* ══════════════════════════════════════════════════════════
   Finance Dashboard JavaScript
   ══════════════════════════════════════════════════════════ */

/* eslint-disable no-unused-vars */

const FIN = {
  summary: null,
  portfolio: [],
  transactions: [],
  watchlist: [],
  goals: [],
  assets: [],
  marketData: null,
  dividends: [],
  allocationTargets: [],
  charts: {},
};

const byId = (id) => document.getElementById(id);

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = String(text ?? "");
  return d.innerHTML;
}

function formatBRL(value) {
  if (value == null || isNaN(value)) return "—";
  return Number(value).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function formatPct(value) {
  if (value == null || isNaN(value)) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

function formatNumber(value, decimals = 2) {
  if (value == null || isNaN(value)) return "—";
  return Number(value).toLocaleString("pt-BR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function changeClass(value) {
  if (value == null) return "";
  return value >= 0 ? "fin-up" : "fin-down";
}

function badgeClass(type) {
  const map = {
    stock: "fin-badge-stock",
    crypto: "fin-badge-crypto",
    fii: "fin-badge-fii",
    etf: "fin-badge-etf",
    fund: "fin-badge-fund",
    "renda-fixa": "fin-badge-renda-fixa",
  };
  return map[type] || "fin-badge-stock";
}

// ── Theme Toggle ─────────────────────────────────────────

function initTheme() {
  const saved = localStorage.getItem("fin-theme");
  if (saved === "light") document.body.classList.add("light");
  const btn = byId("themeToggle");
  if (btn) {
    btn.addEventListener("click", () => {
      document.body.classList.toggle("light");
      const isLight = document.body.classList.contains("light");
      localStorage.setItem("fin-theme", isLight ? "light" : "dark");
      btn.textContent = isLight ? "🌙" : "☀️";
    });
    btn.textContent = document.body.classList.contains("light") ? "🌙" : "☀️";
  }
}

// ══════════════════════════════════════════════════════════
// Data Loading
// ══════════════════════════════════════════════════════════

async function loadAll() {
  try {
    const [summary, transactions, watchlist, goals, market, assets, dividends, allocTargets] = await Promise.all([
      fetch("/api/finance/summary").then((r) => r.json()),
      fetch("/api/finance/transactions").then((r) => r.json()),
      fetch("/api/finance/watchlist").then((r) => r.json()),
      fetch("/api/finance/goals").then((r) => r.json()),
      fetch("/api/finance/market-data").then((r) => r.json()),
      fetch("/api/finance/assets").then((r) => r.json()),
      fetch("/api/finance/dividends").then((r) => r.json()),
      fetch("/api/finance/allocation-targets").then((r) => r.json()),
    ]);

    FIN.summary = summary;
    FIN.portfolio = summary.portfolio || [];
    FIN.transactions = transactions;
    FIN.watchlist = watchlist;
    FIN.goals = goals;
    FIN.marketData = market;
    FIN.assets = (assets || []).map((a) => ({
      id: a.id,
      symbol: a.symbol,
      name: a.name || a.symbol,
      asset_type: a.asset_type,
    }));
    FIN.dividends = dividends || [];
    FIN.allocationTargets = allocTargets || [];

    renderSummary(summary);
    renderCurrency(summary.currency_rates || []);
    renderIndices(market.indices || {});
    renderPortfolio(FIN.portfolio);
    renderTransactions(transactions);
    renderWatchlist(watchlist);
    renderGoals(goals);
    renderAllocationChart(summary);
    renderPnLChart(FIN.portfolio);
    renderPerformanceChart(FIN.portfolio);
    renderDividends(FIN.dividends);
    renderRebalance();
    populateHistorySelect();
    populateIRYears();
    checkWatchlistAlerts();
  } catch (err) {
    console.error("Finance load error:", err);
  }
}

// ══════════════════════════════════════════════════════════
// Render Functions
// ══════════════════════════════════════════════════════════

function renderSummary(s) {
  const invested = byId("summaryInvested");
  const current = byId("summaryCurrentValue");
  const pnl = byId("summaryPnL");
  const pnlPct = byId("summaryPnLPct");
  const assets = byId("summaryAssets");

  if (invested) invested.querySelector(".fin-summary-value").textContent = formatBRL(s.total_invested);
  if (current) current.querySelector(".fin-summary-value").textContent = formatBRL(s.current_value);

  if (pnl) {
    pnl.querySelector(".fin-summary-value").textContent = formatBRL(s.total_pnl);
    pnl.classList.toggle("positive", s.total_pnl >= 0);
    pnl.classList.toggle("negative", s.total_pnl < 0);
  }

  if (pnlPct) {
    pnlPct.querySelector(".fin-summary-value").textContent = formatPct(s.total_pnl_pct);
    pnlPct.classList.toggle("positive", s.total_pnl_pct >= 0);
    pnlPct.classList.toggle("negative", s.total_pnl_pct < 0);
  }

  if (assets) assets.querySelector(".fin-summary-value").textContent = s.asset_count || 0;
}

function renderCurrency(rates) {
  const el = byId("finCurrencyContent");
  if (!el) return;
  if (!rates.length) {
    el.innerHTML = '<p class="fin-empty">Nenhuma cotação disponível.</p>';
    return;
  }
  const icons = { "USD-BRL": "🇺🇸", "EUR-BRL": "🇪🇺", "BTC-BRL": "₿" };
  el.innerHTML = rates
    .map((r) => {
      const icon = icons[r.pair] || "💱";
      const variation = Number(r.variation) || 0;
      const cls = changeClass(variation);
      const rateStr = r.pair === "BTC-BRL"
        ? formatNumber(r.rate, 2)
        : formatNumber(r.rate, 4);
      return `
        <div class="fin-currency-row">
          <span class="fin-currency-icon">${icon}</span>
          <span class="fin-currency-pair">${escapeHtml(r.pair)}</span>
          <span class="fin-currency-rate">R$ ${rateStr}</span>
          <span class="${cls}" style="margin-left:10px;font-weight:600">${formatPct(variation)}</span>
        </div>
      `;
    })
    .join("");
}

function renderIndices(indices) {
  const el = byId("finIndicesContent");
  if (!el) return;
  const entries = Object.entries(indices);
  if (!entries.length) {
    el.innerHTML = '<p class="fin-empty">Dados de mercado indisponíveis.</p>';
    return;
  }
  el.innerHTML = entries
    .map(([_key, idx]) => {
      const cls = changeClass(idx.change_pct);
      return `
        <div class="fin-index-row">
          <span class="fin-index-name">${escapeHtml(idx.name)}</span>
          <span class="fin-index-price">${formatNumber(idx.price, 0)} pts</span>
          <span class="fin-index-change ${cls}">${formatPct(idx.change_pct)}</span>
        </div>
      `;
    })
    .join("");
}

function renderPortfolio(portfolio) {
  const el = byId("finPortfolioContent");
  if (!el) return;
  if (!portfolio.length) {
    el.innerHTML = `
      <p class="fin-empty">
        Nenhum ativo no portfólio. Adicione um ativo e registre transações para começar!
      </p>
    `;
    return;
  }

  const rows = portfolio
    .map((p) => {
      const currentVal = (p.current_price || 0) * p.quantity;
      const pnl = currentVal - p.total_invested;
      const pnlPct = p.total_invested ? (pnl / p.total_invested * 100) : 0;
      const pnlCls = changeClass(pnl);
      const typeCls = badgeClass(p.asset_type);

      // Renda fixa extra info
      let rfInfo = "";
      if (p.asset_type === "renda-fixa" && p.extra_json) {
        try {
          const extra = typeof p.extra_json === "string" ? JSON.parse(p.extra_json) : p.extra_json;
          const parts = [];
          if (extra.indexer) parts.push(extra.indexer + (extra.yield_rate ? ` ${extra.yield_rate}%` : ""));
          if (extra.maturity_date) parts.push(`Venc: ${extra.maturity_date.slice(0, 10)}`);
          if (extra.issuer) parts.push(extra.issuer);
          if (parts.length) rfInfo = `<div class="fin-rf-info">${escapeHtml(parts.join(" · "))}</div>`;
        } catch { /* ignore parse errors */ }
      }

      return `
        <tr>
          <td>
            <strong>${escapeHtml(p.symbol)}</strong>
            <span class="fin-badge ${typeCls}">${escapeHtml(p.asset_type)}</span>
            ${rfInfo}
          </td>
          <td>${escapeHtml(p.name)}</td>
          <td class="text-right mono">${formatNumber(p.quantity)}</td>
          <td class="text-right mono">${formatBRL(p.avg_price)}</td>
          <td class="text-right mono">${formatBRL(p.current_price)}</td>
          <td class="text-right mono">${formatBRL(p.total_invested)}</td>
          <td class="text-right mono">${formatBRL(currentVal)}</td>
          <td class="text-right mono ${pnlCls}">${formatBRL(pnl)}</td>
          <td class="text-right mono ${pnlCls}">${formatPct(pnlPct)}</td>
          <td class="text-center">
            <button class="fin-del-btn" data-action="deleteAsset" data-id="${p.asset_id}" title="Remover">🗑️</button>
          </td>
        </tr>
      `;
    })
    .join("");

  el.innerHTML = `
    <div class="fin-table-wrap">
      <table class="fin-table">
        <thead>
          <tr>
            <th>Ativo</th>
            <th>Nome</th>
            <th class="text-right">Qtd</th>
            <th class="text-right">PM</th>
            <th class="text-right">Atual</th>
            <th class="text-right">Investido</th>
            <th class="text-right">Valor</th>
            <th class="text-right">P&L</th>
            <th class="text-right">P&L %</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderTransactions(txns) {
  const el = byId("finTransactionsContent");
  if (!el) return;
  if (!txns.length) {
    el.innerHTML = '<p class="fin-empty">Nenhuma transação registrada.</p>';
    return;
  }

  const rows = txns
    .slice(0, 50)
    .map((t) => {
      const typeCls = t.tx_type === "buy" ? "fin-badge-buy" : "fin-badge-sell";
      const label = t.tx_type === "buy" ? "COMPRA" : "VENDA";
      const date = (t.tx_date || t.created_at || "").slice(0, 10);
      return `
        <tr>
          <td>${escapeHtml(date)}</td>
          <td><span class="fin-badge ${typeCls}">${label}</span></td>
          <td><strong>${escapeHtml(t.symbol)}</strong></td>
          <td class="text-right mono">${formatNumber(t.quantity)}</td>
          <td class="text-right mono">${formatBRL(t.price)}</td>
          <td class="text-right mono">${formatBRL(t.total)}</td>
          <td class="text-right mono">${formatBRL(t.fees)}</td>
          <td>${escapeHtml(t.notes || "")}</td>
          <td class="text-center">
            <button class="fin-del-btn" data-action="deleteTransaction" data-id="${t.id}" title="Excluir">🗑️</button>
          </td>
        </tr>
      `;
    })
    .join("");

  el.innerHTML = `
    <div class="fin-table-wrap">
      <table class="fin-table">
        <thead>
          <tr>
            <th>Data</th>
            <th>Tipo</th>
            <th>Ativo</th>
            <th class="text-right">Qtd</th>
            <th class="text-right">Preço</th>
            <th class="text-right">Total</th>
            <th class="text-right">Taxas</th>
            <th>Notas</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderWatchlist(watchlist) {
  const el = byId("finWatchlistContent");
  if (!el) return;
  if (!watchlist.length) {
    el.innerHTML = '<p class="fin-empty">Watchlist vazia. Adicione ativos para monitorar!</p>';
    return;
  }

  el.innerHTML = watchlist
    .map((w) => {
      const targetStr = w.target_price ? `Alvo: ${formatBRL(w.target_price)}` : "";
      const dir = w.alert_above ? "↑" : "↓";
      const typeCls = badgeClass(w.asset_type);
      const hasPrice = w.current_price != null;
      const priceStr = hasPrice ? formatBRL(w.current_price) : "—";

      // Change info
      let changeHtml = "";
      if (hasPrice && w.day_change != null) {
        const cls = changeClass(w.day_change);
        const pctStr = w.day_change_pct != null ? ` (${formatPct(w.day_change_pct)})` : "";
        changeHtml = `<span class="fin-wl-change ${cls}">${formatBRL(w.day_change)}${pctStr}</span>`;
      }

      // Alert status: compare current price with target
      let alertHtml = "";
      if (hasPrice && w.target_price) {
        const triggered = w.alert_above
          ? w.current_price >= w.target_price
          : w.current_price <= w.target_price;
        if (triggered) {
          alertHtml = '<span class="fin-wl-alert">🔔 Alvo atingido!</span>';
        }
      }

      return `
        <div class="fin-wl-item">
          <div class="fin-wl-info">
            <span class="fin-wl-symbol">${escapeHtml(w.symbol)}</span>
            <span class="fin-badge ${typeCls}">${escapeHtml(w.asset_type)}</span>
            <span class="fin-wl-name">${escapeHtml(w.name)}</span>
          </div>
          <div class="fin-wl-prices">
            <span class="fin-wl-price">${priceStr}</span>
            ${changeHtml}
          </div>
          <div class="fin-wl-meta">
            <span class="fin-wl-target">${targetStr} ${dir}</span>
            ${alertHtml}
          </div>
          <button class="fin-del-btn" data-action="deleteWatchlistItem" data-id="${w.id}" title="Remover">🗑️</button>
        </div>
      `;
    })
    .join("");
}

function renderGoals(goals) {
  const el = byId("finGoalsContent");
  if (!el) return;
  if (!goals.length) {
    el.innerHTML = '<p class="fin-empty">Nenhuma meta financeira. Crie uma meta para acompanhar!</p>';
    return;
  }

  el.innerHTML = goals
    .map((g) => {
      const pct = g.target_amount ? Math.min(100, (g.current_amount / g.target_amount) * 100) : 0;
      const fillClass = pct >= 100 ? "complete" : "";
      const deadlineStr = g.deadline
        ? `<span class="fin-goal-deadline">Prazo: ${escapeHtml(g.deadline.slice(0, 10))}</span>`
        : "";

      return `
        <div class="fin-goal-item">
          <div class="fin-goal-header">
            <span class="fin-goal-name">${escapeHtml(g.name)}</span>
            <div class="fin-goal-actions">
              <button class="fin-del-btn" data-action="openEditGoalModal" data-id="${g.id}" title="Editar">✏️</button>
              <button class="fin-del-btn" data-action="deleteGoal" data-id="${g.id}" title="Excluir">🗑️</button>
            </div>
          </div>
          <div class="fin-goal-amounts">
            ${formatBRL(g.current_amount)} / ${formatBRL(g.target_amount)}
          </div>
          <div class="fin-goal-bar">
            <div class="fin-goal-fill ${fillClass}" style="width: ${pct.toFixed(1)}%"></div>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span class="fin-goal-pct">${pct.toFixed(1)}%</span>
            ${deadlineStr}
          </div>
        </div>
      `;
    })
    .join("");
}

// ══════════════════════════════════════════════════════════
// Charts
// ══════════════════════════════════════════════════════════

function chartColors(count) {
  const palette = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f97316",
    "#eab308", "#22c55e", "#14b8a6", "#06b6d4", "#3b82f6",
    "#a855f7", "#d946ef", "#f59e0b", "#10b981", "#0ea5e9",
  ];
  return Array.from({ length: count }, (_, i) => palette[i % palette.length]);
}

function renderAllocationChart(summary) {
  if (typeof Chart === "undefined") return;
  const canvas = byId("allocationChart");
  if (!canvas) return;
  const alloc = summary.allocation || {};
  const entries = Object.entries(alloc).filter(([_, v]) => v > 0);

  if (!entries.length) {
    canvas.parentElement.innerHTML = '<p class="fin-empty">Sem dados de alocação.</p>';
    return;
  }

  const labels = entries.map(([k]) => k.charAt(0).toUpperCase() + k.slice(1));
  const data = entries.map(([_, v]) => v);
  const colors = chartColors(data.length);

  if (FIN.charts.allocation) FIN.charts.allocation.destroy();

  FIN.charts.allocation = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: colors,
        borderWidth: 0,
        hoverOffset: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "55%",
      plugins: {
        legend: {
          position: "right",
          labels: {
            color: getComputedStyle(document.body).getPropertyValue("--text") || "#e2e8f0",
            font: { size: 12, weight: 600 },
            padding: 12,
            usePointStyle: true,
            pointStyleWidth: 10,
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = ((ctx.raw / total) * 100).toFixed(1);
              return ` ${ctx.label}: ${formatBRL(ctx.raw)} (${pct}%)`;
            },
          },
        },
      },
    },
  });
}

function renderPnLChart(portfolio) {
  if (typeof Chart === "undefined") return;
  const canvas = byId("pnlChart");
  if (!canvas) return;

  if (!portfolio.length) {
    canvas.parentElement.innerHTML = '<p class="fin-empty">Sem dados de P&L.</p>';
    return;
  }

  const sorted = [...portfolio].sort((a, b) => {
    const pnlA = ((a.current_price || 0) * a.quantity) - a.total_invested;
    const pnlB = ((b.current_price || 0) * b.quantity) - b.total_invested;
    return pnlB - pnlA;
  });

  const labels = sorted.map((p) => p.symbol);
  const data = sorted.map((p) => {
    const val = (p.current_price || 0) * p.quantity;
    return Math.round((val - p.total_invested) * 100) / 100;
  });
  const bgColors = data.map((v) => v >= 0 ? "rgba(34, 197, 94, 0.7)" : "rgba(239, 68, 68, 0.7)");
  const borderColors = data.map((v) => v >= 0 ? "#22c55e" : "#ef4444");

  if (FIN.charts.pnl) FIN.charts.pnl.destroy();

  FIN.charts.pnl = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: bgColors,
        borderColor: borderColors,
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: "y",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => ` P&L: ${formatBRL(ctx.raw)}`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "#8b92a5",
            font: { size: 10 },
            callback: (v) => formatBRL(v),
          },
        },
        y: {
          grid: { display: false },
          ticks: {
            color: "#e2e8f0",
            font: { size: 11, weight: 600 },
          },
        },
      },
    },
  });
}

function renderPerformanceChart(portfolio) {
  if (typeof Chart === "undefined") return;
  const canvas = byId("performanceChart");
  if (!canvas) return;

  if (!portfolio.length) {
    canvas.parentElement.innerHTML = '<p class="fin-empty">Adicione ativos para ver a performance.</p>';
    return;
  }

  const labels = portfolio.map((p) => p.symbol);
  const invested = portfolio.map((p) => p.total_invested);
  const current = portfolio.map((p) => (p.current_price || 0) * p.quantity);
  const colors = chartColors(portfolio.length);

  if (FIN.charts.performance) FIN.charts.performance.destroy();

  FIN.charts.performance = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Investido",
          data: invested,
          backgroundColor: "rgba(99, 102, 241, 0.5)",
          borderColor: "#6366f1",
          borderWidth: 1,
          borderRadius: 4,
        },
        {
          label: "Valor Atual",
          data: current,
          backgroundColor: colors.map((c) => c + "88"),
          borderColor: colors,
          borderWidth: 1,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: {
            color: "#e2e8f0",
            font: { size: 11 },
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
          grid: { display: false },
          ticks: { color: "#e2e8f0", font: { size: 11, weight: 600 } },
        },
        y: {
          grid: { color: "rgba(255,255,255,0.05)" },
          ticks: {
            color: "#8b92a5",
            font: { size: 10 },
            callback: (v) => formatBRL(v),
          },
        },
      },
    },
  });
}

// ══════════════════════════════════════════════════════════
// Modals & CRUD
// ══════════════════════════════════════════════════════════

function openFinModal(title, bodyHtml) {
  byId("finModalTitle").textContent = title;
  byId("finModalBody").innerHTML = bodyHtml;
  byId("finModalOverlay").style.display = "flex";

  // Bind form submit via data-form-action (CSP-safe)
  const formActionMap = { submitAddAsset, submitAddTransaction, submitAddWatchlist, submitAddGoal, submitEditGoal, submitAddDividend, submitAllocationTargets };
  const form = byId("finModalBody").querySelector("form[data-form-action]");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const fn = formActionMap[form.dataset.formAction];
      if (fn) {
        const arg = form.dataset.formArg ? Number(form.dataset.formArg) : undefined;
        fn(e, arg);
      }
    });
  }
}

function closeFinModal() {
  byId("finModalOverlay").style.display = "none";
}

// ── Import Excel/CSV ─────────────────────────────────────

function openImportModal() {
  openFinModal("Importar Dados", `
    <div class="fin-import-section">
      <div class="fin-import-tabs">
        <button class="fin-import-tab active" data-tab="general">📥 Importação Geral</button>
        <button class="fin-import-tab" data-tab="nota">📄 Nota de Corretagem</button>
      </div>

      <!-- General Import -->
      <div id="importTabGeneral" class="fin-import-tab-content">
        <p class="fin-import-desc">
          Importe ativos e transações de um arquivo <strong>CSV</strong> ou <strong>Excel (.xlsx)</strong>.<br>
          O arquivo deve conter ao menos uma coluna <code>símbolo</code> (ou <code>symbol</code>).
        </p>

        <div class="fin-import-cols">
          <h4>Colunas reconhecidas:</h4>
          <div class="fin-import-cols-grid">
            <span class="fin-import-col"><strong>símbolo</strong> — ticker do ativo (obrigatório)</span>
            <span class="fin-import-col"><strong>nome</strong> — nome do ativo</span>
            <span class="fin-import-col"><strong>tipo</strong> — ação, fii, etf, crypto, fundo, renda fixa</span>
            <span class="fin-import-col"><strong>operação</strong> — compra ou venda (C/V)</span>
            <span class="fin-import-col"><strong>quantidade</strong> — qtd negociada</span>
            <span class="fin-import-col"><strong>preço</strong> — preço unitário</span>
            <span class="fin-import-col"><strong>taxas</strong> — corretagem / emolumentos</span>
            <span class="fin-import-col"><strong>data</strong> — data da operação</span>
            <span class="fin-import-col"><strong>notas</strong> — observações</span>
          </div>
        </div>

        <div class="fin-import-actions">
          <a href="/api/finance/import-template" class="fin-import-template-btn" download>
            📄 Baixar modelo CSV
          </a>
        </div>

        <form id="finImportForm" class="fin-import-form">
          <label class="fin-import-dropzone" id="finImportDropzone">
            <input type="file" id="finImportFile" accept=".csv,.tsv,.xlsx,.xls" style="display:none" />
            <span class="fin-import-dropzone-icon">📁</span>
            <span class="fin-import-dropzone-text">Clique ou arraste o arquivo aqui</span>
            <span class="fin-import-dropzone-hint">CSV, TSV, Excel (.xlsx)</span>
          </label>
          <div id="finImportStatus" class="fin-import-status" style="display:none"></div>
          <button type="submit" class="fin-form-submit" id="finImportSubmit" disabled>
            📥 Importar Dados
          </button>
        </form>
      </div>

      <!-- Nota de Corretagem Import -->
      <div id="importTabNota" class="fin-import-tab-content" style="display:none">
        <p class="fin-import-desc">
          Importe diretamente sua <strong>nota de corretagem</strong> exportada da B3 (CEI) ou corretora.<br>
          Aceita formatos CSV e Excel com colunas típicas de notas.
        </p>

        <div class="fin-import-cols">
          <h4>Colunas reconhecidas automaticamente:</h4>
          <div class="fin-import-cols-grid">
            <span class="fin-import-col"><strong>papel / código</strong> — ticker do ativo</span>
            <span class="fin-import-col"><strong>C/V / operação</strong> — compra ou venda</span>
            <span class="fin-import-col"><strong>quantidade</strong> — qtd negociada</span>
            <span class="fin-import-col"><strong>preço / valor unitário</strong> — preço por unidade</span>
            <span class="fin-import-col"><strong>corretagem</strong> — taxa da corretora</span>
            <span class="fin-import-col"><strong>emolumentos</strong> — taxas B3</span>
            <span class="fin-import-col"><strong>data pregão</strong> — data da operação</span>
          </div>
        </div>

        <form id="finNotaForm" class="fin-import-form">
          <label class="fin-import-dropzone" id="finNotaDropzone">
            <input type="file" id="finNotaFile" accept=".csv,.tsv,.xlsx,.xls" style="display:none" />
            <span class="fin-import-dropzone-icon">📄</span>
            <span class="fin-import-dropzone-text">Clique ou arraste a nota aqui</span>
            <span class="fin-import-dropzone-hint">CSV, TSV, Excel (.xlsx)</span>
          </label>
          <div id="finNotaStatus" class="fin-import-status" style="display:none"></div>
          <button type="submit" class="fin-form-submit" id="finNotaSubmit" disabled>
            📄 Importar Nota
          </button>
        </form>
      </div>
    </div>
  `);

  // Tab switching
  document.querySelectorAll(".fin-import-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".fin-import-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const isNota = tab.dataset.tab === "nota";
      const genTab = byId("importTabGeneral");
      const notaTab = byId("importTabNota");
      if (genTab) genTab.style.display = isNota ? "none" : "";
      if (notaTab) notaTab.style.display = isNota ? "" : "none";
    });
  });

  const fileInput = byId("finImportFile");
  const dropzone = byId("finImportDropzone");
  const submitBtn = byId("finImportSubmit");

  if (fileInput) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files.length) {
        dropzone.querySelector(".fin-import-dropzone-text").textContent = fileInput.files[0].name;
        dropzone.classList.add("has-file");
        submitBtn.disabled = false;
      }
    });
  }

  if (dropzone) {
    dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
    dropzone.addEventListener("dragleave", () => { dropzone.classList.remove("dragover"); });
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        dropzone.querySelector(".fin-import-dropzone-text").textContent = e.dataTransfer.files[0].name;
        dropzone.classList.add("has-file");
        submitBtn.disabled = false;
      }
    });
  }

  const form = byId("finImportForm");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await submitImport();
    });
  }

  // Nota de corretagem tab
  const notaFile = byId("finNotaFile");
  const notaDrop = byId("finNotaDropzone");
  const notaSubmit = byId("finNotaSubmit");

  if (notaFile) {
    notaFile.addEventListener("change", () => {
      if (notaFile.files.length) {
        notaDrop.querySelector(".fin-import-dropzone-text").textContent = notaFile.files[0].name;
        notaDrop.classList.add("has-file");
        notaSubmit.disabled = false;
      }
    });
  }
  if (notaDrop) {
    notaDrop.addEventListener("dragover", (e) => { e.preventDefault(); notaDrop.classList.add("dragover"); });
    notaDrop.addEventListener("dragleave", () => notaDrop.classList.remove("dragover"));
    notaDrop.addEventListener("drop", (e) => {
      e.preventDefault();
      notaDrop.classList.remove("dragover");
      if (e.dataTransfer.files.length) {
        notaFile.files = e.dataTransfer.files;
        notaDrop.querySelector(".fin-import-dropzone-text").textContent = e.dataTransfer.files[0].name;
        notaDrop.classList.add("has-file");
        notaSubmit.disabled = false;
      }
    });
  }
  const notaForm = byId("finNotaForm");
  if (notaForm) {
    notaForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      await submitNotaImport();
    });
  }
}

async function submitImport() {
  const fileInput = byId("finImportFile");
  const status = byId("finImportStatus");
  const submitBtn = byId("finImportSubmit");
  if (!fileInput || !fileInput.files.length) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "⏳ Importando...";
  status.style.display = "block";
  status.className = "fin-import-status loading";
  status.textContent = "Processando arquivo...";

  const fd = new FormData();
  fd.append("file", fileInput.files[0]);

  try {
    const resp = await fetch("/api/finance/import", {
      method: "POST",
      body: fd,
    });
    const data = await resp.json();

    if (resp.ok && data.ok) {
      status.className = "fin-import-status success";
      let msg = `✅ ${data.imported} de ${data.total_rows} registros importados com sucesso!`;
      if (data.errors && data.errors.length) {
        msg += `\n⚠️ ${data.errors.length} erro(s):\n` + data.errors.join("\n");
      }
      status.textContent = msg;
      loadAll();
    } else {
      status.className = "fin-import-status error";
      status.textContent = `❌ ${data.error || "Erro ao importar"}`;
      if (data.errors && data.errors.length) {
        status.textContent += "\n" + data.errors.join("\n");
      }
    }
  } catch {
    status.className = "fin-import-status error";
    status.textContent = "❌ Erro de rede ao enviar arquivo";
  }

  submitBtn.textContent = "📥 Importar Dados";
  submitBtn.disabled = false;
}

async function submitNotaImport() {
  const fileInput = byId("finNotaFile");
  const status = byId("finNotaStatus");
  const submitBtn = byId("finNotaSubmit");
  if (!fileInput || !fileInput.files.length) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "⏳ Importando nota...";
  status.style.display = "block";
  status.className = "fin-import-status loading";
  status.textContent = "Processando nota de corretagem...";

  const fd = new FormData();
  fd.append("file", fileInput.files[0]);

  try {
    const resp = await fetch("/api/finance/import-nota", {
      method: "POST",
      body: fd,
    });
    const data = await resp.json();

    if (resp.ok && data.ok) {
      status.className = "fin-import-status success";
      let msg = `✅ ${data.imported} de ${data.total_rows} operações importadas!`;
      if (data.errors && data.errors.length) {
        msg += `\n⚠️ ${data.errors.length} erro(s):\n` + data.errors.join("\n");
      }
      status.textContent = msg;
      loadAll();
    } else {
      status.className = "fin-import-status error";
      status.textContent = `❌ ${data.error || "Erro ao importar nota"}`;
      if (data.errors && data.errors.length) {
        status.textContent += "\n" + data.errors.join("\n");
      }
    }
  } catch {
    status.className = "fin-import-status error";
    status.textContent = "❌ Erro de rede ao enviar arquivo";
  }

  submitBtn.textContent = "📄 Importar Nota";
  submitBtn.disabled = false;
}

// ── Add Asset ────────────────────────────────────────────

function openAddAssetModal() {
  openFinModal("Adicionar Ativo", `
    <form data-form-action="submitAddAsset">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Símbolo</label>
          <input id="fmAssetSymbol" placeholder="PETR4, BITCOIN, etc" required />
        </div>
        <div class="fin-form-group">
          <label>Nome</label>
          <input id="fmAssetName" placeholder="Petrobras PN" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmAssetType">
            <option value="stock">Ação</option>
            <option value="fii">FII</option>
            <option value="etf">ETF</option>
            <option value="crypto">Crypto</option>
            <option value="fund">Fundo</option>
            <option value="renda-fixa">Renda Fixa</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Moeda</label>
          <select id="fmAssetCurrency">
            <option value="BRL">BRL</option>
            <option value="USD">USD</option>
          </select>
        </div>
      </div>
      <div id="fmRendaFixaBlock" class="fin-form-new-asset" style="display:none">
        <p style="font-size:0.78rem;color:var(--text-s,#94a3b8);margin-bottom:10px">📌 Dados de Renda Fixa</p>
        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>Indexador</label>
            <select id="fmRfIndexer">
              <option value="CDI">CDI</option>
              <option value="IPCA">IPCA+</option>
              <option value="PRE">Pré-fixado</option>
              <option value="SELIC">Selic</option>
              <option value="IGPM">IGP-M</option>
            </select>
          </div>
          <div class="fin-form-group">
            <label>Taxa (% a.a.)</label>
            <input id="fmRfYield" type="number" step="0.01" placeholder="12.50" />
          </div>
        </div>
        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>Vencimento</label>
            <input id="fmRfMaturity" type="date" />
          </div>
          <div class="fin-form-group">
            <label>Emissor</label>
            <input id="fmRfIssuer" placeholder="Tesouro Nacional, Banco X" />
          </div>
        </div>
      </div>
      <button type="submit" class="fin-form-submit">➕ Adicionar Ativo</button>
    </form>
  `);

  const typeSelect = byId("fmAssetType");
  const rfBlock = byId("fmRendaFixaBlock");
  if (typeSelect && rfBlock) {
    typeSelect.addEventListener("change", () => {
      rfBlock.style.display = typeSelect.value === "renda-fixa" ? "block" : "none";
    });
  }
}

async function submitAddAsset(e) {
  e.preventDefault();
  const body = {
    symbol: byId("fmAssetSymbol").value.trim(),
    name: byId("fmAssetName").value.trim() || byId("fmAssetSymbol").value.trim(),
    asset_type: byId("fmAssetType").value,
    currency: byId("fmAssetCurrency").value,
  };
  // Add renda-fixa extra info
  if (body.asset_type === "renda-fixa") {
    body.extra = {
      indexer: (byId("fmRfIndexer") || {}).value || "CDI",
      yield_rate: Number((byId("fmRfYield") || {}).value || 0),
      maturity_date: (byId("fmRfMaturity") || {}).value || null,
      issuer: (byId("fmRfIssuer") || {}).value || "",
    };
  }
  try {
    const resp = await fetch("/api/finance/assets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      alert(data.error || "Erro ao adicionar ativo");
    }
  } catch {
    alert("Erro de rede");
  }
}

async function deleteAsset(assetId) {
  if (!confirm("Remover este ativo e todas as transações associadas?")) return;
  try {
    await fetch(`/api/finance/assets/${assetId}`, { method: "DELETE" });
    loadAll();
  } catch {
    alert("Erro ao remover ativo");
  }
}

// ── Add Transaction ──────────────────────────────────────

function openAddTransactionModal() {
  const assetOptions = FIN.assets.length
    ? FIN.assets.map((a) => `<option value="${a.id}">${escapeHtml(a.symbol)} — ${escapeHtml(a.name)}</option>`).join("")
    : "";

  openFinModal("Nova Transação", `
    <form data-form-action="submitAddTransaction">
      <div class="fin-form-group">
        <label>Ativo</label>
        <select id="fmTxAsset">
          ${assetOptions}
          <option value="__new__">➕ Criar novo ativo...</option>
        </select>
      </div>
      <div id="fmTxNewAssetBlock" class="fin-form-new-asset" style="display:none">
        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>Símbolo</label>
            <input id="fmTxNewSymbol" placeholder="PETR4" />
          </div>
          <div class="fin-form-group">
            <label>Nome</label>
            <input id="fmTxNewName" placeholder="Petrobras PN" />
          </div>
        </div>
        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>Tipo de ativo</label>
            <select id="fmTxNewType">
              <option value="stock">Ação</option>
              <option value="fii">FII</option>
              <option value="etf">ETF</option>
              <option value="crypto">Crypto</option>
              <option value="fund">Fundo</option>
              <option value="renda-fixa">Renda Fixa</option>
            </select>
          </div>
          <div class="fin-form-group">
            <label>Moeda</label>
            <select id="fmTxNewCurrency">
              <option value="BRL">BRL</option>
              <option value="USD">USD</option>
            </select>
          </div>
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmTxType">
            <option value="buy">Compra</option>
            <option value="sell">Venda</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Data</label>
          <input id="fmTxDate" type="date" value="${new Date().toISOString().slice(0, 10)}" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Quantidade</label>
          <input id="fmTxQty" type="number" step="0.01" min="0.01" required />
        </div>
        <div class="fin-form-group">
          <label>Preço unitário (R$)</label>
          <input id="fmTxPrice" type="number" step="0.01" min="0.01" required />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Taxas (R$)</label>
          <input id="fmTxFees" type="number" step="0.01" value="0" />
        </div>
        <div class="fin-form-group">
          <label>Notas</label>
          <input id="fmTxNotes" placeholder="Opcional" />
        </div>
      </div>
      <button type="submit" class="fin-form-submit">💰 Registrar Transação</button>
    </form>
  `);

  // Toggle new asset fields
  const sel = byId("fmTxAsset");
  if (sel) {
    sel.addEventListener("change", () => {
      const block = byId("fmTxNewAssetBlock");
      if (block) block.style.display = sel.value === "__new__" ? "block" : "none";
    });
    // Auto-show if no assets exist
    if (!FIN.assets.length) {
      sel.value = "__new__";
      const block = byId("fmTxNewAssetBlock");
      if (block) block.style.display = "block";
    }
  }
}

async function submitAddTransaction(e) {
  e.preventDefault();
  let assetId = byId("fmTxAsset").value;

  // If user chose to create a new asset, do that first
  if (assetId === "__new__") {
    const sym = (byId("fmTxNewSymbol").value || "").trim().toUpperCase();
    if (!sym) { alert("Informe o símbolo do ativo"); return; }
    try {
      const aResp = await fetch("/api/finance/assets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: sym,
          name: byId("fmTxNewName").value.trim() || sym,
          asset_type: byId("fmTxNewType").value,
          currency: byId("fmTxNewCurrency").value,
        }),
      });
      if (!aResp.ok) {
        const d = await aResp.json();
        alert(d.error || "Erro ao criar ativo");
        return;
      }
      const aData = await aResp.json();
      assetId = aData.id;
    } catch {
      alert("Erro de rede ao criar ativo");
      return;
    }
  }

  const body = {
    asset_id: Number(assetId),
    tx_type: byId("fmTxType").value,
    quantity: Number(byId("fmTxQty").value),
    price: Number(byId("fmTxPrice").value),
    fees: Number(byId("fmTxFees").value || 0),
    notes: byId("fmTxNotes").value.trim(),
    tx_date: byId("fmTxDate").value,
  };
  if (!body.asset_id) {
    alert("Selecione ou crie um ativo");
    return;
  }
  try {
    const resp = await fetch("/api/finance/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      alert(data.error || "Erro ao registrar transação");
    }
  } catch {
    alert("Erro de rede");
  }
}

async function deleteTransaction(txId) {
  if (!confirm("Excluir esta transação?")) return;
  try {
    await fetch(`/api/finance/transactions/${txId}`, { method: "DELETE" });
    loadAll();
  } catch {
    alert("Erro ao excluir transação");
  }
}

// ── Watchlist ────────────────────────────────────────────

function openAddWatchlistModal() {
  openFinModal("Adicionar à Watchlist", `
    <form data-form-action="submitAddWatchlist">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Símbolo</label>
          <input id="fmWlSymbol" placeholder="VALE3" required />
        </div>
        <div class="fin-form-group">
          <label>Nome</label>
          <input id="fmWlName" placeholder="Vale S.A." />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmWlType">
            <option value="stock">Ação</option>
            <option value="fii">FII</option>
            <option value="etf">ETF</option>
            <option value="crypto">Crypto</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Preço alvo (R$)</label>
          <input id="fmWlTarget" type="number" step="0.01" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Alertar quando</label>
        <select id="fmWlAlertAbove">
          <option value="0">Preço cair abaixo do alvo</option>
          <option value="1">Preço subir acima do alvo</option>
        </select>
      </div>
      <button type="submit" class="fin-form-submit">👁️ Adicionar à Watchlist</button>
    </form>
  `);
}

async function submitAddWatchlist(e) {
  e.preventDefault();
  const body = {
    symbol: byId("fmWlSymbol").value.trim(),
    name: byId("fmWlName").value.trim() || byId("fmWlSymbol").value.trim(),
    asset_type: byId("fmWlType").value,
    target_price: byId("fmWlTarget").value ? Number(byId("fmWlTarget").value) : null,
    alert_above: byId("fmWlAlertAbove").value === "1",
  };
  try {
    const resp = await fetch("/api/finance/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      alert(data.error || "Erro ao adicionar à watchlist");
    }
  } catch {
    alert("Erro de rede");
  }
}

async function deleteWatchlistItem(wlId) {
  if (!confirm("Remover da watchlist?")) return;
  try {
    await fetch(`/api/finance/watchlist/${wlId}`, { method: "DELETE" });
    loadAll();
  } catch {
    alert("Erro ao remover item");
  }
}

// ── Goals ────────────────────────────────────────────────

function openAddGoalModal() {
  openFinModal("Nova Meta Financeira", `
    <form data-form-action="submitAddGoal">
      <div class="fin-form-group">
        <label>Nome da meta</label>
        <input id="fmGoalName" placeholder="Reserva de emergência" required />
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Valor alvo (R$)</label>
          <input id="fmGoalTarget" type="number" step="0.01" min="1" required />
        </div>
        <div class="fin-form-group">
          <label>Valor atual (R$)</label>
          <input id="fmGoalCurrent" type="number" step="0.01" value="0" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Prazo</label>
          <input id="fmGoalDeadline" type="date" />
        </div>
        <div class="fin-form-group">
          <label>Categoria</label>
          <select id="fmGoalCategory">
            <option value="savings">Reserva</option>
            <option value="investment">Investimento</option>
            <option value="travel">Viagem</option>
            <option value="education">Educação</option>
            <option value="retirement">Aposentadoria</option>
            <option value="property">Imóvel</option>
            <option value="other">Outro</option>
          </select>
        </div>
      </div>
      <div class="fin-form-group">
        <label>Notas</label>
        <textarea id="fmGoalNotes" rows="2" placeholder="Opcional"></textarea>
      </div>
      <button type="submit" class="fin-form-submit">🎯 Criar Meta</button>
    </form>
  `);
}

async function submitAddGoal(e) {
  e.preventDefault();
  const body = {
    name: byId("fmGoalName").value.trim(),
    target_amount: Number(byId("fmGoalTarget").value),
    current_amount: Number(byId("fmGoalCurrent").value || 0),
    deadline: byId("fmGoalDeadline").value || null,
    category: byId("fmGoalCategory").value,
    notes: byId("fmGoalNotes").value.trim(),
  };
  try {
    const resp = await fetch("/api/finance/goals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      alert(data.error || "Erro ao criar meta");
    }
  } catch {
    alert("Erro de rede");
  }
}

function openEditGoalModal(goalId) {
  const goal = FIN.goals.find((g) => g.id === goalId);
  if (!goal) return;

  openFinModal("Editar Meta", `
    <form data-form-action="submitEditGoal" data-form-arg="${goalId}">
      <div class="fin-form-group">
        <label>Nome da meta</label>
        <input id="fmGoalName" value="${escapeHtml(goal.name)}" required />
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Valor alvo (R$)</label>
          <input id="fmGoalTarget" type="number" step="0.01" value="${goal.target_amount}" required />
        </div>
        <div class="fin-form-group">
          <label>Valor atual (R$)</label>
          <input id="fmGoalCurrent" type="number" step="0.01" value="${goal.current_amount}" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Prazo</label>
          <input id="fmGoalDeadline" type="date" value="${(goal.deadline || "").slice(0, 10)}" />
        </div>
        <div class="fin-form-group">
          <label>Categoria</label>
          <select id="fmGoalCategory">
            <option value="savings" ${goal.category === "savings" ? "selected" : ""}>Reserva</option>
            <option value="investment" ${goal.category === "investment" ? "selected" : ""}>Investimento</option>
            <option value="travel" ${goal.category === "travel" ? "selected" : ""}>Viagem</option>
            <option value="education" ${goal.category === "education" ? "selected" : ""}>Educação</option>
            <option value="retirement" ${goal.category === "retirement" ? "selected" : ""}>Aposentadoria</option>
            <option value="property" ${goal.category === "property" ? "selected" : ""}>Imóvel</option>
            <option value="other" ${goal.category === "other" ? "selected" : ""}>Outro</option>
          </select>
        </div>
      </div>
      <button type="submit" class="fin-form-submit">💾 Salvar Alterações</button>
    </form>
  `);
}

async function submitEditGoal(e, goalId) {
  e.preventDefault();
  const body = {
    name: byId("fmGoalName").value.trim(),
    target_amount: Number(byId("fmGoalTarget").value),
    current_amount: Number(byId("fmGoalCurrent").value || 0),
    deadline: byId("fmGoalDeadline").value || null,
    category: byId("fmGoalCategory").value,
  };
  try {
    const resp = await fetch(`/api/finance/goals/${goalId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      alert(data.error || "Erro ao salvar meta");
    }
  } catch {
    alert("Erro de rede");
  }
}

async function deleteGoal(goalId) {
  if (!confirm("Excluir esta meta?")) return;
  try {
    await fetch(`/api/finance/goals/${goalId}`, { method: "DELETE" });
    loadAll();
  } catch {
    alert("Erro ao excluir meta");
  }
}

// ══════════════════════════════════════════════════════════
// Dividends
// ══════════════════════════════════════════════════════════

function renderDividends(divs) {
  const el = byId("finDividendsContent");
  const summaryEl = byId("finDividendSummary");
  if (!el) return;

  if (!divs.length) {
    el.innerHTML = '<p class="fin-empty">Nenhum dividendo registrado. Registre proventos recebidos!</p>';
    if (summaryEl) summaryEl.innerHTML = "";
    return;
  }

  // Summary totals by type
  const totals = {};
  let grandTotal = 0;
  divs.forEach((d) => {
    const t = d.div_type || "dividend";
    totals[t] = (totals[t] || 0) + (d.total_amount || 0);
    grandTotal += d.total_amount || 0;
  });
  const typeLabels = { dividend: "Dividendos", jcp: "JCP", rendimento: "Rendimentos", bonus: "Bonificação" };
  if (summaryEl) {
    summaryEl.innerHTML = `
      <div class="fin-div-totals">
        ${Object.entries(totals).map(([k, v]) =>
          `<div class="fin-div-total-item"><span>${typeLabels[k] || k}</span><strong>${formatBRL(v)}</strong></div>`
        ).join("")}
        <div class="fin-div-total-item fin-div-grand"><span>Total</span><strong>${formatBRL(grandTotal)}</strong></div>
      </div>
    `;
  }

  const rows = divs.slice(0, 50).map((d) => {
    const date = (d.pay_date || d.ex_date || d.created_at || "").slice(0, 10);
    const typeCls = d.div_type === "jcp" ? "fin-badge-sell" : "fin-badge-buy";
    const label = (typeLabels[d.div_type] || d.div_type || "DIV").toUpperCase();
    return `
      <tr>
        <td>${escapeHtml(date)}</td>
        <td><span class="fin-badge ${typeCls}">${escapeHtml(label)}</span></td>
        <td><strong>${escapeHtml(d.symbol || "—")}</strong></td>
        <td class="text-right mono">${formatNumber(d.quantity, 0)}</td>
        <td class="text-right mono">${formatBRL(d.amount_per_share)}</td>
        <td class="text-right mono">${formatBRL(d.total_amount)}</td>
        <td>${escapeHtml(d.notes || "")}</td>
        <td class="text-center">
          <button class="fin-del-btn" data-action="deleteDividend" data-id="${d.id}" title="Excluir">🗑️</button>
        </td>
      </tr>
    `;
  }).join("");

  el.innerHTML = `
    <div class="fin-table-wrap">
      <table class="fin-table">
        <thead>
          <tr>
            <th>Data Pgto</th>
            <th>Tipo</th>
            <th>Ativo</th>
            <th class="text-right">Qtd</th>
            <th class="text-right">$/Ação</th>
            <th class="text-right">Total</th>
            <th>Notas</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function openAddDividendModal() {
  const assetOptions = FIN.assets.length
    ? FIN.assets.map((a) => `<option value="${a.id}">${escapeHtml(a.symbol)} — ${escapeHtml(a.name)}</option>`).join("")
    : '<option value="">Nenhum ativo cadastrado</option>';

  openFinModal("Registrar Dividendo / Provento", `
    <form data-form-action="submitAddDividend">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Ativo</label>
          <select id="fmDivAsset" required>${assetOptions}</select>
        </div>
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmDivType">
            <option value="dividend">Dividendo</option>
            <option value="jcp">JCP</option>
            <option value="rendimento">Rendimento</option>
            <option value="bonus">Bonificação</option>
          </select>
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Valor por ação (R$)</label>
          <input id="fmDivPerShare" type="number" step="0.0001" min="0" />
        </div>
        <div class="fin-form-group">
          <label>Quantidade</label>
          <input id="fmDivQty" type="number" step="1" min="1" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Valor total (R$)</label>
          <input id="fmDivTotal" type="number" step="0.01" min="0.01" required />
        </div>
        <div class="fin-form-group">
          <label>Data ex</label>
          <input id="fmDivExDate" type="date" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Data pagamento</label>
          <input id="fmDivPayDate" type="date" value="${new Date().toISOString().slice(0, 10)}" />
        </div>
        <div class="fin-form-group">
          <label>Notas</label>
          <input id="fmDivNotes" placeholder="Opcional" />
        </div>
      </div>
      <button type="submit" class="fin-form-submit">💸 Registrar Provento</button>
    </form>
  `);

  // Auto-calc total when per_share and qty change
  const perShare = byId("fmDivPerShare");
  const qty = byId("fmDivQty");
  const total = byId("fmDivTotal");
  const autoCalc = () => {
    const ps = Number(perShare?.value || 0);
    const q = Number(qty?.value || 0);
    if (ps > 0 && q > 0 && total) total.value = (ps * q).toFixed(2);
  };
  if (perShare) perShare.addEventListener("input", autoCalc);
  if (qty) qty.addEventListener("input", autoCalc);
}

async function submitAddDividend(e) {
  e.preventDefault();
  const body = {
    asset_id: Number(byId("fmDivAsset").value),
    div_type: byId("fmDivType").value,
    amount_per_share: Number(byId("fmDivPerShare").value || 0),
    total_amount: Number(byId("fmDivTotal").value),
    quantity: Number(byId("fmDivQty").value || 0),
    ex_date: byId("fmDivExDate").value || null,
    pay_date: byId("fmDivPayDate").value || null,
    notes: byId("fmDivNotes").value.trim(),
  };
  try {
    const resp = await fetch("/api/finance/dividends", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      alert(data.error || "Erro ao registrar dividendo");
    }
  } catch {
    alert("Erro de rede");
  }
}

async function deleteDividend(divId) {
  if (!confirm("Excluir este dividendo?")) return;
  try {
    await fetch(`/api/finance/dividends/${divId}`, { method: "DELETE" });
    loadAll();
  } catch {
    alert("Erro ao excluir dividendo");
  }
}

// ══════════════════════════════════════════════════════════
// Price History Chart (Evolução Patrimonial)
// ══════════════════════════════════════════════════════════

function populateHistorySelect() {
  const sel = byId("historyAssetSelect");
  if (!sel) return;
  const current = sel.value;
  const opts = FIN.assets.map((a) =>
    `<option value="${a.id}" ${String(a.id) === current ? "selected" : ""}>${escapeHtml(a.symbol)}</option>`
  ).join("");
  sel.innerHTML = '<option value="">Selecione um ativo...</option>' + opts;
}

async function loadHistoryChart(assetId) {
  const emptyEl = byId("historyEmpty");
  const canvas = byId("historyChart");
  if (!canvas) return;

  if (!assetId) {
    if (FIN.charts.history) { FIN.charts.history.destroy(); FIN.charts.history = null; }
    canvas.style.display = "none";
    if (emptyEl) emptyEl.style.display = "";
    return;
  }

  try {
    const resp = await fetch(`/api/finance/asset-history/${assetId}?limit=180`);
    const data = await resp.json();

    if (!data.length) {
      canvas.style.display = "none";
      if (emptyEl) { emptyEl.style.display = ""; emptyEl.textContent = "Sem dados históricos para este ativo ainda."; }
      if (FIN.charts.history) { FIN.charts.history.destroy(); FIN.charts.history = null; }
      return;
    }

    canvas.style.display = "";
    if (emptyEl) emptyEl.style.display = "none";

    const sorted = data.reverse();
    const labels = sorted.map((d) => (d.captured_at || "").slice(0, 10));
    const prices = sorted.map((d) => d.price);

    if (FIN.charts.history) FIN.charts.history.destroy();

    FIN.charts.history = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "Preço (R$)",
          data: prices,
          borderColor: "#6366f1",
          backgroundColor: "rgba(99,102,241,0.1)",
          fill: true,
          tension: 0.3,
          pointRadius: prices.length > 60 ? 0 : 2,
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { intersect: false, mode: "index" },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${formatBRL(ctx.raw)}`,
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: "#8b92a5", font: { size: 10 }, maxTicksLimit: 12 },
          },
          y: {
            grid: { color: "rgba(255,255,255,0.05)" },
            ticks: { color: "#8b92a5", font: { size: 10 }, callback: (v) => formatBRL(v) },
          },
        },
      },
    });
  } catch (err) {
    console.error("History chart error:", err);
  }
}

// ══════════════════════════════════════════════════════════
// Rebalancing
// ══════════════════════════════════════════════════════════

async function renderRebalance() {
  const el = byId("finRebalanceContent");
  if (!el) return;

  if (!FIN.allocationTargets.length) {
    el.innerHTML = '<p class="fin-empty">Configure suas metas de alocação para ver sugestões de rebalanceamento.</p>';
    return;
  }

  try {
    const resp = await fetch("/api/finance/rebalance");
    const data = await resp.json();
    const suggestions = data.suggestions || [];

    if (!suggestions.length) {
      el.innerHTML = `<p class="fin-empty">${escapeHtml(data.message || "Sem sugestões no momento.")}</p>`;
      return;
    }

    const rows = suggestions.map((s) => {
      const diffCls = s.diff_pct > 0 ? "fin-up" : s.diff_pct < 0 ? "fin-down" : "";
      const actionCls = s.action === "COMPRAR" ? "fin-badge-buy" : s.action === "VENDER" ? "fin-badge-sell" : "fin-badge-stock";
      return `
        <div class="fin-rebal-row">
          <div class="fin-rebal-type">
            <strong>${escapeHtml(s.asset_type)}</strong>
          </div>
          <div class="fin-rebal-bars">
            <div class="fin-rebal-bar-container">
              <div class="fin-rebal-bar fin-rebal-current" style="width:${Math.min(100, Math.abs(s.current_pct || 0))}%"></div>
              <span class="fin-rebal-label">Atual: ${formatPct(s.current_pct).replace("+", "")}</span>
            </div>
            <div class="fin-rebal-bar-container">
              <div class="fin-rebal-bar fin-rebal-target" style="width:${Math.min(100, s.target_pct || 0)}%"></div>
              <span class="fin-rebal-label">Meta: ${Number(s.target_pct).toFixed(1)}%</span>
            </div>
          </div>
          <div class="fin-rebal-diff ${diffCls}">
            ${formatBRL(s.diff_value)}
          </div>
          <span class="fin-badge ${actionCls}">${escapeHtml(s.action)}</span>
        </div>
      `;
    }).join("");

    el.innerHTML = `<div class="fin-rebal-list">${rows}</div>`;
  } catch {
    el.innerHTML = '<p class="fin-empty">Erro ao carregar sugestões.</p>';
  }
}

function openAllocationModal() {
  const types = ["stock", "fii", "etf", "crypto", "fund", "renda-fixa"];
  const typeLabels = { stock: "Ações", fii: "FIIs", etf: "ETFs", crypto: "Crypto", fund: "Fundos", "renda-fixa": "Renda Fixa" };
  const currentMap = {};
  FIN.allocationTargets.forEach((t) => { currentMap[t.asset_type] = t.target_pct; });

  const fields = types.map((t) => `
    <div class="fin-form-row">
      <div class="fin-form-group" style="flex:2">
        <label>${typeLabels[t] || t}</label>
      </div>
      <div class="fin-form-group" style="flex:1">
        <input class="fm-alloc-pct" data-type="${t}" type="number" step="0.1" min="0" max="100"
               value="${currentMap[t] != null ? currentMap[t] : ""}" placeholder="%" />
      </div>
    </div>
  `).join("");

  openFinModal("Metas de Alocação (%)", `
    <form data-form-action="submitAllocationTargets">
      ${fields}
      <p id="fmAllocTotal" class="fin-alloc-total">Total: 0%</p>
      <button type="submit" class="fin-form-submit">💾 Salvar Metas</button>
    </form>
  `);

  // Update total on input
  const updateTotal = () => {
    let sum = 0;
    document.querySelectorAll(".fm-alloc-pct").forEach((inp) => {
      sum += Number(inp.value || 0);
    });
    const totalEl = byId("fmAllocTotal");
    if (totalEl) {
      totalEl.textContent = `Total: ${sum.toFixed(1)}%`;
      totalEl.classList.toggle("fin-alloc-warning", Math.abs(sum - 100) > 0.5);
    }
  };
  document.querySelectorAll(".fm-alloc-pct").forEach((inp) => {
    inp.addEventListener("input", updateTotal);
  });
  updateTotal();
}

async function submitAllocationTargets(e) {
  e.preventDefault();
  const targets = [];
  document.querySelectorAll(".fm-alloc-pct").forEach((inp) => {
    const pct = Number(inp.value || 0);
    if (pct > 0) {
      targets.push({ asset_type: inp.dataset.type, target_pct: pct });
    }
  });
  try {
    const resp = await fetch("/api/finance/allocation-targets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets }),
    });
    if (resp.ok) {
      closeFinModal();
      // Reload targets
      const tResp = await fetch("/api/finance/allocation-targets");
      FIN.allocationTargets = await tResp.json();
      renderRebalance();
    } else {
      alert("Erro ao salvar metas");
    }
  } catch {
    alert("Erro de rede");
  }
}

// ══════════════════════════════════════════════════════════
// IR Report
// ══════════════════════════════════════════════════════════

function populateIRYears() {
  const sel = byId("irYearSelect");
  if (!sel) return;
  const currentYear = new Date().getFullYear();
  let html = "";
  for (let y = currentYear; y >= currentYear - 5; y--) {
    html += `<option value="${y}">${y}</option>`;
  }
  sel.innerHTML = html;
}

async function loadIRReport(year) {
  const el = byId("finIRContent");
  if (!el || !year) return;

  el.innerHTML = '<div class="fin-ai-loading">Gerando relatório IR...</div>';

  try {
    const resp = await fetch(`/api/finance/ir-report?year=${year}`);
    const data = await resp.json();

    if (data.error) {
      el.innerHTML = `<p class="fin-empty">${escapeHtml(data.error)}</p>`;
      return;
    }

    let html = "";

    // Monthly sells summary
    const months = data.monthly_sells || [];
    if (months.length) {
      html += '<div class="fin-ir-section"><h4>📊 Vendas Mensais</h4>';
      html += '<div class="fin-ir-months">';
      const monthNames = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
      months.forEach((m) => {
        const overLimit = m.total_sell > 20000;
        const cls = overLimit ? "fin-ir-month over" : "fin-ir-month";
        html += `
          <div class="${cls}">
            <span class="fin-ir-month-name">${monthNames[m.month - 1] || m.month}</span>
            <span class="fin-ir-month-sell">${formatBRL(m.total_sell)}</span>
            <span class="fin-ir-month-pnl ${changeClass(m.profit)}">${formatBRL(m.profit)}</span>
            ${overLimit ? '<span class="fin-ir-darf">DARF</span>' : ""}
          </div>
        `;
      });
      html += "</div></div>";
    }

    // Dividend totals
    const divTotals = data.dividend_totals || {};
    const divEntries = Object.entries(divTotals);
    if (divEntries.length) {
      html += '<div class="fin-ir-section"><h4>💸 Proventos no Ano</h4>';
      html += '<div class="fin-ir-divs">';
      divEntries.forEach(([type, val]) => {
        html += `<div class="fin-ir-div-row"><span>${escapeHtml(type)}</span><strong>${formatBRL(val)}</strong></div>`;
      });
      html += "</div></div>";
    }

    // Year-end positions
    const positions = data.positions || [];
    if (positions.length) {
      html += '<div class="fin-ir-section"><h4>📋 Posição em 31/12</h4>';
      html += '<div class="fin-table-wrap"><table class="fin-table"><thead><tr><th>Ativo</th><th>Tipo</th><th class="text-right">Qtd</th><th class="text-right">Custo Médio</th><th class="text-right">Total Investido</th></tr></thead><tbody>';
      positions.forEach((p) => {
        html += `<tr>
          <td><strong>${escapeHtml(p.symbol)}</strong></td>
          <td>${escapeHtml(p.asset_type)}</td>
          <td class="text-right mono">${formatNumber(p.quantity)}</td>
          <td class="text-right mono">${formatBRL(p.avg_price)}</td>
          <td class="text-right mono">${formatBRL(p.total_invested)}</td>
        </tr>`;
      });
      html += "</tbody></table></div></div>";
    }

    if (!html) {
      html = '<p class="fin-empty">Nenhuma movimentação encontrada para este ano.</p>';
    }

    el.innerHTML = html;
  } catch {
    el.innerHTML = '<p class="fin-empty">Erro ao gerar relatório IR.</p>';
  }
}

// ══════════════════════════════════════════════════════════
// Export Data
// ══════════════════════════════════════════════════════════

function openExportModal() {
  openFinModal("Exportar Dados", `
    <div class="fin-export-section">
      <p>Escolha o formato e o tipo de dados para exportar:</p>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Formato</label>
          <select id="fmExportFormat">
            <option value="xlsx">Excel (.xlsx)</option>
            <option value="csv">CSV</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Dados</label>
          <select id="fmExportType">
            <option value="all">Todos</option>
            <option value="portfolio">Portfólio</option>
            <option value="transactions">Transações</option>
            <option value="dividends">Dividendos</option>
          </select>
        </div>
      </div>
      <button id="fmExportBtn" class="fin-form-submit">📤 Exportar</button>
    </div>
  `);

  const btn = byId("fmExportBtn");
  if (btn) {
    btn.addEventListener("click", () => {
      const format = byId("fmExportFormat").value;
      const type = byId("fmExportType").value;
      window.location.href = `/api/finance/export?format=${format}&type=${type}`;
      closeFinModal();
    });
  }
}

// ══════════════════════════════════════════════════════════
// Push Notifications
// ══════════════════════════════════════════════════════════

function setupNotifications() {
  if (!("Notification" in window)) {
    alert("Seu navegador não suporta notificações.");
    return;
  }
  if (Notification.permission === "granted") {
    alert("Notificações já estão ativas! Você será alertado quando metas da watchlist forem atingidas.");
    return;
  }
  Notification.requestPermission().then((perm) => {
    if (perm === "granted") {
      alert("Notificações ativadas! Você será alertado quando metas da watchlist forem atingidas.");
      checkWatchlistAlerts();
    }
  });
}

function checkWatchlistAlerts() {
  if (Notification.permission !== "granted") return;
  FIN.watchlist.forEach((w) => {
    if (w.current_price == null || !w.target_price) return;
    const triggered = w.alert_above
      ? w.current_price >= w.target_price
      : w.current_price <= w.target_price;
    if (triggered) {
      const dir = w.alert_above ? "subiu acima" : "caiu abaixo";
      new Notification(`🔔 ${w.symbol} atingiu alvo!`, {
        body: `${w.symbol} ${dir} de ${formatBRL(w.target_price)} — Atual: ${formatBRL(w.current_price)}`,
        icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>💰</text></svg>",
      });
    }
  });
}

// ══════════════════════════════════════════════════════════
// AI Analysis
// ══════════════════════════════════════════════════════════

async function requestAIAnalysis(type) {
  const el = byId("finAIContent");
  if (!el) return;

  // Toggle active state
  document.querySelectorAll(".fin-ai-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.type === type);
  });

  el.innerHTML = '<div class="fin-ai-loading">Analisando seus dados financeiros...</div>';

  try {
    const resp = await fetch("/api/finance/ai-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type }),
    });
    const data = await resp.json();
    if (resp.ok && data.answer) {
      el.innerHTML = renderMarkdown(data.answer);
    } else {
      el.innerHTML = `<p class="fin-empty">${escapeHtml(data.error || "Erro na análise")}</p>`;
    }
  } catch {
    el.innerHTML = '<p class="fin-empty">Erro de rede ao comunicar com a IA.</p>';
  }
}

async function sendFinAIChat() {
  const input = byId("finAIChatInput");
  const history = byId("finAIChatHistory");
  if (!input || !history) return;
  const msg = input.value.trim();
  if (!msg) return;

  input.value = "";
  history.innerHTML += `<div class="fin-chat-msg user">${escapeHtml(msg)}</div>`;
  history.innerHTML += '<div class="fin-chat-msg ai fin-ai-loading" id="finAIChatLoading">Pensando...</div>';
  history.scrollTop = history.scrollHeight;

  try {
    const resp = await fetch("/api/finance/ai-chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
    });
    const data = await resp.json();
    const loadingEl = byId("finAIChatLoading");
    if (loadingEl) {
      if (resp.ok && data.answer) {
        let html = renderMarkdown(data.answer);

        // Display AI action confirmations
        if (data.actions && data.actions.length) {
          html += '<div class="fin-ai-actions">';
          for (const act of data.actions) {
            const icon = act.ok ? "✅" : "❌";
            let desc = "";
            if (act.action === "add_transaction" || act.action === "buy" || act.action === "sell") {
              const op = act.tx_type === "sell" ? "Venda" : "Compra";
              desc = `${op} registrada: ${act.quantity} × ${act.symbol} a ${formatBRL(act.price)}`;
            } else if (act.action === "add_asset") {
              desc = `Ativo cadastrado: ${act.symbol}`;
            } else if (act.action === "add_watchlist") {
              desc = `Adicionado à watchlist: ${act.symbol}`;
            } else if (act.action === "add_goal") {
              desc = `Meta criada: ${act.name}`;
            } else {
              desc = `${act.action}: ${act.error || "ok"}`;
            }
            html += `<div class="fin-ai-action-item ${act.ok ? "success" : "error"}">${icon} ${escapeHtml(desc)}</div>`;
          }
          html += "</div>";
          // Reload data since actions modified the DB
          loadAll();
        }

        loadingEl.innerHTML = html;
        loadingEl.classList.remove("fin-ai-loading");
      } else {
        loadingEl.textContent = data.error || "Erro";
        loadingEl.classList.remove("fin-ai-loading");
      }
    }
    loadingEl?.removeAttribute("id");
  } catch {
    const loadingEl = byId("finAIChatLoading");
    if (loadingEl) {
      loadingEl.textContent = "Erro de rede";
      loadingEl.classList.remove("fin-ai-loading");
      loadingEl.removeAttribute("id");
    }
  }
  history.scrollTop = history.scrollHeight;
}

// Simple markdown renderer
function renderMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>")
    .replace(/\n/g, "<br>");
}

// ══════════════════════════════════════════════════════════
// Bootstrap
// ══════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  loadAll();

  const refreshBtn = byId("finRefreshBtn");
  if (refreshBtn) refreshBtn.addEventListener("click", loadAll);

  const chatInput = byId("finAIChatInput");
  if (chatInput) {
    chatInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendFinAIChat();
    });
  }

  // ── Button bindings (CSP-safe, no inline onclick) ────
  const bind = (id, fn) => { const el = byId(id); if (el) el.addEventListener("click", fn); };

  bind("btnImportTop", openImportModal);
  bind("btnImportPortfolio", openImportModal);
  bind("btnAddAsset", openAddAssetModal);
  bind("btnAddTransaction", openAddTransactionModal);
  bind("btnAddWatchlist", openAddWatchlistModal);
  bind("btnAddGoal", openAddGoalModal);
  bind("btnAddDividend", openAddDividendModal);
  bind("btnEditAllocation", openAllocationModal);
  bind("btnExportData", openExportModal);
  bind("btnNotifications", setupNotifications);
  bind("finAIChatSend", sendFinAIChat);
  bind("finModalClose", closeFinModal);

  // Modal overlay: close on background click
  const overlay = byId("finModalOverlay");
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeFinModal();
    });
  }

  // AI analysis type buttons
  document.querySelectorAll(".fin-ai-btn[data-type]").forEach((btn) => {
    btn.addEventListener("click", () => requestAIAnalysis(btn.dataset.type));
  });

  // History chart: asset select
  const histSel = byId("historyAssetSelect");
  if (histSel) {
    histSel.addEventListener("change", () => loadHistoryChart(histSel.value));
  }

  // IR report: year select
  const irSel = byId("irYearSelect");
  if (irSel) {
    irSel.addEventListener("change", () => loadIRReport(irSel.value));
  }

  // ── Event delegation for dynamic buttons (CSP-safe) ──
  const actionMap = { deleteAsset, deleteTransaction, deleteWatchlistItem, deleteGoal, openEditGoalModal, deleteDividend };
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const fn = actionMap[btn.dataset.action];
    if (fn) fn(Number(btn.dataset.id));
  });
});

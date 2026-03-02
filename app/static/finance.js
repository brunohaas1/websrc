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
    const [summary, transactions, watchlist, goals, market] = await Promise.all([
      fetch("/api/finance/summary").then((r) => r.json()),
      fetch("/api/finance/transactions").then((r) => r.json()),
      fetch("/api/finance/watchlist").then((r) => r.json()),
      fetch("/api/finance/goals").then((r) => r.json()),
      fetch("/api/finance/market-data").then((r) => r.json()),
    ]);

    FIN.summary = summary;
    FIN.portfolio = summary.portfolio || [];
    FIN.transactions = transactions;
    FIN.watchlist = watchlist;
    FIN.goals = goals;
    FIN.marketData = market;
    FIN.assets = FIN.portfolio.map((p) => ({
      id: p.asset_id,
      symbol: p.symbol,
      name: p.name,
    }));

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
      return `
        <tr>
          <td>
            <strong>${escapeHtml(p.symbol)}</strong>
            <span class="fin-badge ${typeCls}">${escapeHtml(p.asset_type)}</span>
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
            <button class="fin-del-btn" onclick="deleteAsset(${p.asset_id})" title="Remover">🗑️</button>
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
            <button class="fin-del-btn" onclick="deleteTransaction(${t.id})" title="Excluir">🗑️</button>
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
      return `
        <div class="fin-wl-item">
          <span class="fin-wl-symbol">${escapeHtml(w.symbol)}</span>
          <span class="fin-badge ${typeCls}">${escapeHtml(w.asset_type)}</span>
          <span class="fin-wl-name">${escapeHtml(w.name)}</span>
          <span class="fin-wl-target">${targetStr} ${dir}</span>
          <button class="fin-del-btn" onclick="deleteWatchlistItem(${w.id})" title="Remover">🗑️</button>
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
              <button class="fin-del-btn" onclick="openEditGoalModal(${g.id})" title="Editar">✏️</button>
              <button class="fin-del-btn" onclick="deleteGoal(${g.id})" title="Excluir">🗑️</button>
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
}

function closeFinModal() {
  byId("finModalOverlay").style.display = "none";
}

// ── Add Asset ────────────────────────────────────────────

function openAddAssetModal() {
  openFinModal("Adicionar Ativo", `
    <form onsubmit="submitAddAsset(event)">
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
      <button type="submit" class="fin-form-submit">➕ Adicionar Ativo</button>
    </form>
  `);
}

async function submitAddAsset(e) {
  e.preventDefault();
  const body = {
    symbol: byId("fmAssetSymbol").value.trim(),
    name: byId("fmAssetName").value.trim() || byId("fmAssetSymbol").value.trim(),
    asset_type: byId("fmAssetType").value,
    currency: byId("fmAssetCurrency").value,
  };
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
    : '<option value="">Nenhum ativo cadastrado</option>';

  openFinModal("Nova Transação", `
    <form onsubmit="submitAddTransaction(event)">
      <div class="fin-form-group">
        <label>Ativo</label>
        <select id="fmTxAsset" required>${assetOptions}</select>
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
}

async function submitAddTransaction(e) {
  e.preventDefault();
  const body = {
    asset_id: Number(byId("fmTxAsset").value),
    tx_type: byId("fmTxType").value,
    quantity: Number(byId("fmTxQty").value),
    price: Number(byId("fmTxPrice").value),
    fees: Number(byId("fmTxFees").value || 0),
    notes: byId("fmTxNotes").value.trim(),
    tx_date: byId("fmTxDate").value,
  };
  if (!body.asset_id) {
    alert("Selecione um ativo");
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
    <form onsubmit="submitAddWatchlist(event)">
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
    <form onsubmit="submitAddGoal(event)">
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
    <form onsubmit="submitEditGoal(event, ${goalId})">
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
        loadingEl.innerHTML = renderMarkdown(data.answer);
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
});

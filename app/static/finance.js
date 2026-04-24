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
  // auto-refresh
  _autoRefreshInterval: null,
  // portfolio sort
  _portfolioSort: { col: null, dir: 1 },
  // transactions sort + filter
  _txSort: { col: null, dir: 1 },
  _txFilter: { asset: "", type: "" },
};

const byId = (id) => document.getElementById(id);

// ── Toast notifications (replaces alert()) ────────────────
function showToast(message, type = "error") {
  let container = byId("finToastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "finToastContainer";
    container.className = "fin-toast-container";
    container.setAttribute("aria-live", "polite");
    container.setAttribute("aria-atomic", "false");
    container.setAttribute("role", "status");
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  toast.className = `fin-toast fin-toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("fin-toast-show"));
  setTimeout(() => {
    toast.classList.remove("fin-toast-show");
    toast.addEventListener("transitionend", () => toast.remove());
    setTimeout(() => toast.remove(), 400);
  }, 3500);
}

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

// ── Authenticated fetch helper ────────────────────────────
// The finance key can be provided via a <meta name="finance-key"> tag in the template.
function finFetch(url, opts = {}) {
  const meta = document.querySelector('meta[name="finance-key"]');
  const key = meta ? meta.getAttribute("content") : "";
  if (key) {
    opts.headers = { ...(opts.headers || {}), "X-Finance-Key": key };
  }
  return fetch(url, opts);
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

// ── Keyboard Shortcuts ───────────────────────────────────

function initFinanceKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Ignore when typing in an input/textarea/select or modal is open
    const tag = document.activeElement && document.activeElement.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    const overlay = byId("finModalOverlay");
    if (overlay && overlay.style.display !== "none") return;

    const ctrl = e.ctrlKey || e.metaKey;

    if (ctrl && e.key === "r") { e.preventDefault(); loadAll(); showToast("Atualizando dados...", "info"); return; }
    if (ctrl && e.key === "i") { e.preventDefault(); openImportModal(); return; }
    if (ctrl && e.key === "e") { e.preventDefault(); openExportModal(); return; }
    if (e.key === "?") { showKeyboardShortcutsHelp(); return; }
    if (e.key === "Escape") { closeFinModal(); return; }
  });
}

function showKeyboardShortcutsHelp() {
  openFinModal("Atalhos de Teclado", `
    <div class="fin-shortcuts-list">
      <div class="fin-shortcut-row"><kbd>Ctrl+R</kbd><span>Atualizar dados</span></div>
      <div class="fin-shortcut-row"><kbd>Ctrl+I</kbd><span>Importar Excel/CSV</span></div>
      <div class="fin-shortcut-row"><kbd>Ctrl+E</kbd><span>Exportar dados</span></div>
      <div class="fin-shortcut-row"><kbd>?</kbd><span>Mostrar atalhos</span></div>
      <div class="fin-shortcut-row"><kbd>Esc</kbd><span>Fechar modal</span></div>
    </div>
  `);
}

// ══════════════════════════════════════════════════════════
// Data Loading
// ══════════════════════════════════════════════════════════

async function loadAll() {
  try {
    const [summary, transactions, watchlist, goals, market, assets, dividends, allocTargets] = await Promise.all([
      finFetch("/api/finance/summary").then((r) => r.json()),
      finFetch("/api/finance/transactions").then((r) => r.json()),
      finFetch("/api/finance/watchlist").then((r) => r.json()),
      finFetch("/api/finance/goals").then((r) => r.json()),
      finFetch("/api/finance/market-data").then((r) => r.json()),
      finFetch("/api/finance/assets").then((r) => r.json()),
      finFetch("/api/finance/dividends").then((r) => r.json()),
      finFetch("/api/finance/allocation-targets").then((r) => r.json()),
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
    renderProjection();
    populateHistorySelect();
    applyHistoryPrefs();
    loadHistoryFromControls();
    populateIRYears();
    checkWatchlistAlerts();
    checkGoalsMilestones(goals);
    updateLastUpdated();
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
  const dividends = byId("summaryDividends");

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

  if (dividends) {
    const totalDiv = (FIN.dividends || []).reduce((sum, d) => sum + (d.total_amount || 0), 0);
    dividends.querySelector(".fin-summary-value").textContent = formatBRL(totalDiv);
  }
}

function updateLastUpdated() {
  const el = byId("finLastUpdated");
  if (!el) return;
  const now = new Date();
  el.textContent = `Atualizado: ${now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
  el.title = now.toLocaleString("pt-BR");
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

  // Apply sort
  let sorted = [...portfolio];
  if (FIN._portfolioSort.col) {
    sorted.sort((a, b) => {
      const av = a[FIN._portfolioSort.col] ?? 0;
      const bv = b[FIN._portfolioSort.col] ?? 0;
      return (av < bv ? -1 : av > bv ? 1 : 0) * FIN._portfolioSort.dir;
    });
  }

  const totalValue = portfolio.reduce((sum, p) => sum + (p.current_price || 0) * p.quantity, 0);

  const sortIcon = (col) => {
    if (FIN._portfolioSort.col !== col) return '<span class="fin-sort-icon">⇅</span>';
    return `<span class="fin-sort-icon active">${FIN._portfolioSort.dir === 1 ? "↑" : "↓"}</span>`;
  };

  const rows = sorted
    .map((p) => {
      const currentVal = (p.current_price || 0) * p.quantity;
      const pnl = currentVal - p.total_invested;
      const pnlPct = p.total_invested ? (pnl / p.total_invested * 100) : 0;
      const pnlCls = changeClass(pnl);
      const typeCls = badgeClass(p.asset_type);
      const weightPct = totalValue > 0 ? (currentVal / totalValue * 100) : 0;

      // Dividend yield for this asset
      const assetDivs = (FIN.dividends || []).filter((d) => d.symbol === p.symbol);
      const totalDiv = assetDivs.reduce((s, d) => s + (d.total_amount || 0), 0);
      const dy = p.total_invested > 0 ? (totalDiv / p.total_invested * 100) : 0;
      const dyHtml = totalDiv > 0
        ? `<span class="fin-dy" title="Dividend Yield: dividendos / custo">${dy.toFixed(1)}%</span>`
        : "—";

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
          <td class="text-right mono">${weightPct.toFixed(1)}%</td>
          <td class="text-right mono">${dyHtml}</td>
          <td class="text-center">
            <button class="fin-del-btn" data-action="addTxForAsset" data-id="${p.asset_id}" title="Nova transação">➕</button>
            <button class="fin-del-btn" data-action="deleteAsset" data-id="${p.asset_id}" title="Remover">🗑️</button>
          </td>
        </tr>
      `;
    })
    .join("");

  el.innerHTML = `
    <div class="fin-table-wrap">
      <table class="fin-table fin-sortable-table" id="portfolioTable">
        <thead>
          <tr>
            <th data-sort-col="symbol" class="fin-th-sort">Ativo ${sortIcon("symbol")}</th>
            <th>Nome</th>
            <th class="text-right fin-th-sort" data-sort-col="quantity">Qtd ${sortIcon("quantity")}</th>
            <th class="text-right fin-th-sort" data-sort-col="avg_price">PM ${sortIcon("avg_price")}</th>
            <th class="text-right fin-th-sort" data-sort-col="current_price">Atual ${sortIcon("current_price")}</th>
            <th class="text-right fin-th-sort" data-sort-col="total_invested">Investido ${sortIcon("total_invested")}</th>
            <th class="text-right">Valor</th>
            <th class="text-right fin-th-sort" data-sort-col="unrealized_pnl">P&amp;L ${sortIcon("unrealized_pnl")}</th>
            <th class="text-right">P&amp;L %</th>
            <th class="text-right">Peso</th>
            <th class="text-right" title="Dividend Yield: total dividendos ÷ custo">DY</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;

  // Bind sort headers
  el.querySelectorAll(".fin-th-sort[data-sort-col]").forEach((th) => {
    th.style.cursor = "pointer";
    th.addEventListener("click", () => {
      const col = th.dataset.sortCol;
      if (FIN._portfolioSort.col === col) {
        FIN._portfolioSort.dir *= -1;
      } else {
        FIN._portfolioSort.col = col;
        FIN._portfolioSort.dir = 1;
      }
      renderPortfolio(FIN.portfolio);
    });
  });
}

let _txPage = 0;
const _TX_PER_PAGE = 20;

function renderTransactions(txns) {
  const el = byId("finTransactionsContent");
  if (!el) return;

  // Apply filter
  let filtered = txns;
  if (FIN._txFilter.asset) {
    filtered = filtered.filter((t) => t.asset_id === Number(FIN._txFilter.asset));
  }
  if (FIN._txFilter.type) {
    filtered = filtered.filter((t) => t.tx_type === FIN._txFilter.type);
  }

  // Apply sort
  if (FIN._txSort.col) {
    filtered = [...filtered].sort((a, b) => {
      const av = a[FIN._txSort.col] ?? "";
      const bv = b[FIN._txSort.col] ?? "";
      return (av < bv ? -1 : av > bv ? 1 : 0) * FIN._txSort.dir;
    });
  }

  const filterBar = `
    <div class="fin-tx-filter-bar">
      <select id="txFilterAsset" class="fin-inline-select" title="Filtrar por ativo">
        <option value="">Todos os ativos</option>
        ${FIN.assets.map((a) => `<option value="${a.id}" ${FIN._txFilter.asset === String(a.id) ? "selected" : ""}>${escapeHtml(a.symbol)}</option>`).join("")}
      </select>
      <select id="txFilterType" class="fin-inline-select" title="Filtrar por tipo">
        <option value="" ${!FIN._txFilter.type ? "selected" : ""}>Compra e Venda</option>
        <option value="buy" ${FIN._txFilter.type === "buy" ? "selected" : ""}>Compras</option>
        <option value="sell" ${FIN._txFilter.type === "sell" ? "selected" : ""}>Vendas</option>
      </select>
      <span class="fin-tx-count">${filtered.length} de ${txns.length}</span>
    </div>
  `;

  if (!filtered.length) {
    el.innerHTML = filterBar + '<p class="fin-empty">Nenhuma transação encontrada.</p>';
    _bindTxFilters();
    return;
  }

  const totalPages = Math.ceil(filtered.length / _TX_PER_PAGE);
  if (_txPage >= totalPages) _txPage = totalPages - 1;
  if (_txPage < 0) _txPage = 0;
  const start = _txPage * _TX_PER_PAGE;
  const page = filtered.slice(start, start + _TX_PER_PAGE);

  const sortIcon = (col) => {
    if (FIN._txSort.col !== col) return '<span class="fin-sort-icon">⇅</span>';
    return `<span class="fin-sort-icon active">${FIN._txSort.dir === 1 ? "↑" : "↓"}</span>`;
  };

  const rows = page
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
            <button class="fin-del-btn" data-action="openEditTransactionModal" data-id="${t.id}" title="Editar">✏️</button>
            <button class="fin-del-btn" data-action="deleteTransaction" data-id="${t.id}" title="Excluir">🗑️</button>
          </td>
        </tr>
      `;
    })
    .join("");

  let paginationHtml = "";
  if (totalPages > 1) {
    paginationHtml = `<div class="fin-pagination">
      <button class="fin-page-btn" data-action="txPagePrev" ${_txPage === 0 ? "disabled" : ""}>◀</button>
      <span class="fin-page-info">${_txPage + 1} / ${totalPages} (${filtered.length} itens)</span>
      <button class="fin-page-btn" data-action="txPageNext" ${_txPage >= totalPages - 1 ? "disabled" : ""}>▶</button>
    </div>`;
  }

  el.innerHTML = filterBar + `
    <div class="fin-table-wrap">
      <table class="fin-table fin-sortable-table">
        <thead>
          <tr>
            <th data-sort-col="tx_date" class="fin-th-sort">Data ${sortIcon("tx_date")}</th>
            <th data-sort-col="tx_type" class="fin-th-sort">Tipo ${sortIcon("tx_type")}</th>
            <th data-sort-col="symbol" class="fin-th-sort">Ativo ${sortIcon("symbol")}</th>
            <th class="text-right" data-sort-col="quantity" class="fin-th-sort">Qtd ${sortIcon("quantity")}</th>
            <th class="text-right" data-sort-col="price" class="fin-th-sort">Preço ${sortIcon("price")}</th>
            <th class="text-right" data-sort-col="total" class="fin-th-sort">Total ${sortIcon("total")}</th>
            <th class="text-right" data-sort-col="fees" class="fin-th-sort">Taxas ${sortIcon("fees")}</th>
            <th>Notas</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    ${paginationHtml}
  `;
  _bindTxFilters();
  _bindTxSortHeaders(el);
}

function _bindTxFilters() {
  const assetSel = byId("txFilterAsset");
  const typeSel = byId("txFilterType");
  if (assetSel) {
    assetSel.addEventListener("change", () => {
      FIN._txFilter.asset = assetSel.value;
      _txPage = 0;
      renderTransactions(FIN.transactions);
    });
  }
  if (typeSel) {
    typeSel.addEventListener("change", () => {
      FIN._txFilter.type = typeSel.value;
      _txPage = 0;
      renderTransactions(FIN.transactions);
    });
  }
}

function _bindTxSortHeaders(container) {
  container.querySelectorAll(".fin-th-sort[data-sort-col]").forEach((th) => {
    th.style.cursor = "pointer";
    th.addEventListener("click", () => {
      const col = th.dataset.sortCol;
      if (FIN._txSort.col === col) {
        FIN._txSort.dir *= -1;
      } else {
        FIN._txSort.col = col;
        FIN._txSort.dir = 1;
      }
      _txPage = 0;
      renderTransactions(FIN.transactions);
    });
  });
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
          <div class="fin-wl-actions">
            <button class="fin-del-btn" data-action="openEditWatchlistModal" data-id="${w.id}" title="Editar">✏️</button>
            <button class="fin-del-btn" data-action="deleteWatchlistItem" data-id="${w.id}" title="Remover">🗑️</button>
          </div>
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
  const formActionMap = {
    submitAddAsset,
    submitAddTransaction,
    submitAddWatchlist,
    submitAddGoal,
    submitEditGoal,
    submitAddDividend,
    submitAllocationTargets,
    submitFinanceSettings,
  };
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
        <button class="fin-import-tab" data-tab="b3">📊 Movimentação B3</button>
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

      <!-- B3 Movimentação Import -->
      <div id="importTabB3" class="fin-import-tab-content" style="display:none">
        <p class="fin-import-desc">
          Importe o extrato de <strong>Movimentação</strong> exportado do <strong>B3 / CEI</strong> (Área do Investidor).<br>
          O sistema reconhece automaticamente compras, vendas, rendimentos, dividendos e JCP.
        </p>

        <div class="fin-import-cols">
          <h4>O que será importado:</h4>
          <div class="fin-import-cols-grid">
            <span class="fin-import-col"><strong>Transferência - Liquidação</strong> → compras</span>
            <span class="fin-import-col"><strong>COMPRA / VENDA</strong> → compras e vendas</span>
            <span class="fin-import-col"><strong>Rendimento</strong> → dividendos de FIIs</span>
            <span class="fin-import-col"><strong>Dividendo</strong> → dividendos de ações</span>
            <span class="fin-import-col"><strong>JCP</strong> → juros sobre capital próprio</span>
            <span class="fin-import-col"><strong>Bonificação</strong> → bonificação em ativos</span>
          </div>
        </div>

        <form id="finB3Form" class="fin-import-form">
          <label class="fin-import-dropzone" id="finB3Dropzone">
            <input type="file" id="finB3File" accept=".xlsx,.xls" style="display:none" />
            <span class="fin-import-dropzone-icon">📊</span>
            <span class="fin-import-dropzone-text">Clique ou arraste o arquivo de Movimentação aqui</span>
            <span class="fin-import-dropzone-hint">Excel (.xlsx) exportado do CEI/B3</span>
          </label>
          <div id="finB3Status" class="fin-import-status" style="display:none"></div>
          <button type="submit" class="fin-form-submit" id="finB3Submit" disabled>
            📊 Importar Movimentação B3
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
      const sel = tab.dataset.tab;
      const genTab = byId("importTabGeneral");
      const notaTab = byId("importTabNota");
      const b3Tab = byId("importTabB3");
      if (genTab) genTab.style.display = sel === "general" ? "" : "none";
      if (notaTab) notaTab.style.display = sel === "nota" ? "" : "none";
      if (b3Tab) b3Tab.style.display = sel === "b3" ? "" : "none";
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

  // B3 Movimentação tab
  const b3File = byId("finB3File");
  const b3Drop = byId("finB3Dropzone");
  const b3Submit = byId("finB3Submit");

  if (b3File) {
    b3File.addEventListener("change", () => {
      if (b3File.files.length) {
        b3Drop.querySelector(".fin-import-dropzone-text").textContent = b3File.files[0].name;
        b3Drop.classList.add("has-file");
        b3Submit.disabled = false;
      }
    });
  }
  if (b3Drop) {
    b3Drop.addEventListener("dragover", (e) => { e.preventDefault(); b3Drop.classList.add("dragover"); });
    b3Drop.addEventListener("dragleave", () => b3Drop.classList.remove("dragover"));
    b3Drop.addEventListener("drop", (e) => {
      e.preventDefault();
      b3Drop.classList.remove("dragover");
      if (e.dataTransfer.files.length) {
        b3File.files = e.dataTransfer.files;
        b3Drop.querySelector(".fin-import-dropzone-text").textContent = e.dataTransfer.files[0].name;
        b3Drop.classList.add("has-file");
        b3Submit.disabled = false;
      }
    });
  }
  const b3Form = byId("finB3Form");
  if (b3Form) {
    b3Form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await submitB3Import();
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
    const resp = await finFetch("/api/finance/import", {
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
    const resp = await finFetch("/api/finance/import-nota", {
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

async function submitB3Import() {
  const fileInput = byId("finB3File");
  const status = byId("finB3Status");
  const submitBtn = byId("finB3Submit");
  if (!fileInput || !fileInput.files.length) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "⏳ Importando movimentação...";
  status.style.display = "block";
  status.className = "fin-import-status loading";
  status.textContent = "Processando arquivo de movimentação B3...";

  const fd = new FormData();
  fd.append("file", fileInput.files[0]);

  try {
    const resp = await finFetch("/api/finance/import-b3", {
      method: "POST",
      body: fd,
    });
    const data = await resp.json();

    if (resp.ok && data.ok) {
      status.className = "fin-import-status success";
      let msg = `✅ Importado com sucesso!\n`;
      msg += `📈 ${data.transactions || 0} transações (compras/vendas)\n`;
      msg += `💰 ${data.dividends || 0} dividendos/rendimentos\n`;
      msg += `⏭️ ${data.skipped || 0} registros ignorados\n`;
      msg += `📋 ${data.total_rows || 0} linhas no arquivo`;
      if (data.errors && data.errors.length) {
        msg += `\n⚠️ ${data.errors.length} erro(s):\n` + data.errors.join("\n");
      }
      status.textContent = msg;
      status.style.whiteSpace = "pre-line";
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

  submitBtn.textContent = "📊 Importar Movimentação B3";
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
    const resp = await finFetch("/api/finance/assets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao adicionar ativo");
    }
  } catch {
    showToast("Erro de rede");
  }
}

async function deleteAsset(assetId) {
  if (!confirm("Remover este ativo e todas as transações associadas?")) return;
  try {
    await finFetch(`/api/finance/assets/${assetId}`, { method: "DELETE" });
    loadAll();
  } catch {
    showToast("Erro ao remover ativo");
  }
}

// ── Add Transaction ──────────────────────────────────────

function addTxForAsset(assetId) {
  openAddTransactionModal();
  // After modal renders, pre-select the asset
  requestAnimationFrame(() => {
    const sel = byId("fmTxAsset");
    if (sel) sel.value = String(assetId);
  });
}

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
    if (!sym) { showToast("Informe o símbolo do ativo"); return; }
    try {
      const aResp = await finFetch("/api/finance/assets", {
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
        showToast(d.error || "Erro ao criar ativo");
        return;
      }
      const aData = await aResp.json();
      assetId = aData.id;
    } catch {
      showToast("Erro de rede ao criar ativo");
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
    showToast("Selecione ou crie um ativo");
    return;
  }
  try {
    const resp = await finFetch("/api/finance/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao registrar transação");
    }
  } catch {
    showToast("Erro de rede");
  }
}

async function deleteTransaction(txId) {
  if (!confirm("Excluir esta transação?")) return;
  try {
    await finFetch(`/api/finance/transactions/${txId}`, { method: "DELETE" });
    loadAll();
  } catch {
    showToast("Erro ao excluir transação");
  }
}

async function openEditTransactionModal(txId) {
  // Find transaction in loaded data
  const tx = FIN.transactions.find((t) => t.id === txId);
  if (!tx) { showToast("Transação não encontrada"); return; }

  openFinModal("Editar Transação", `
    <form data-form-action="submitEditTransaction" data-tx-id="${txId}">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Ativo</label>
          <input value="${escapeHtml(tx.symbol || "")}" disabled />
        </div>
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmEditTxType">
            <option value="buy" ${tx.tx_type === "buy" ? "selected" : ""}>Compra</option>
            <option value="sell" ${tx.tx_type === "sell" ? "selected" : ""}>Venda</option>
          </select>
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Data</label>
          <input id="fmEditTxDate" type="date" value="${(tx.tx_date || "").slice(0, 10)}" />
        </div>
        <div class="fin-form-group">
          <label>Quantidade</label>
          <input id="fmEditTxQty" type="number" step="0.01" min="0.01" value="${tx.quantity}" required />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Preço unitário (R$)</label>
          <input id="fmEditTxPrice" type="number" step="0.01" min="0.01" value="${tx.price}" required />
        </div>
        <div class="fin-form-group">
          <label>Taxas (R$)</label>
          <input id="fmEditTxFees" type="number" step="0.01" value="${tx.fees || 0}" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Notas</label>
        <input id="fmEditTxNotes" value="${escapeHtml(tx.notes || "")}" placeholder="Opcional" />
      </div>
      <button type="submit" class="fin-form-submit">💾 Salvar Alterações</button>
    </form>
  `);
}

async function submitEditTransaction(e) {
  e.preventDefault();
  const form = e.target;
  const txId = Number(form.dataset.txId);
  const body = {
    tx_type: byId("fmEditTxType").value,
    quantity: Number(byId("fmEditTxQty").value),
    price: Number(byId("fmEditTxPrice").value),
    fees: Number(byId("fmEditTxFees").value || 0),
    notes: byId("fmEditTxNotes").value.trim(),
    tx_date: byId("fmEditTxDate").value,
  };
  try {
    const resp = await finFetch(`/api/finance/transactions/${txId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
      showToast("Transação atualizada!", "success");
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao atualizar transação");
    }
  } catch {
    showToast("Erro de rede");
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
    const resp = await finFetch("/api/finance/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao adicionar à watchlist");
    }
  } catch {
    showToast("Erro de rede");
  }
}

async function deleteWatchlistItem(wlId) {
  if (!confirm("Remover da watchlist?")) return;
  try {
    await finFetch(`/api/finance/watchlist/${wlId}`, { method: "DELETE" });
    loadAll();
  } catch {
    showToast("Erro ao remover item");
  }
}

async function openEditWatchlistModal(wlId) {
  const item = FIN.watchlist.find((w) => w.id === wlId);
  if (!item) { showToast("Item não encontrado"); return; }

  openFinModal("Editar Watchlist", `
    <form data-form-action="submitEditWatchlist" data-wl-id="${wlId}">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Símbolo</label>
          <input value="${escapeHtml(item.symbol)}" disabled />
        </div>
        <div class="fin-form-group">
          <label>Nome</label>
          <input id="fmEditWlName" value="${escapeHtml(item.name || "")}" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmEditWlType">
            <option value="stock" ${item.asset_type === "stock" ? "selected" : ""}>Ação</option>
            <option value="fii" ${item.asset_type === "fii" ? "selected" : ""}>FII</option>
            <option value="etf" ${item.asset_type === "etf" ? "selected" : ""}>ETF</option>
            <option value="crypto" ${item.asset_type === "crypto" ? "selected" : ""}>Crypto</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Preço alvo (R$)</label>
          <input id="fmEditWlTarget" type="number" step="0.01" value="${item.target_price || ""}" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Alertar quando</label>
        <select id="fmEditWlAlertAbove">
          <option value="0" ${!item.alert_above ? "selected" : ""}>Preço cair abaixo do alvo</option>
          <option value="1" ${item.alert_above ? "selected" : ""}>Preço subir acima do alvo</option>
        </select>
      </div>
      <div class="fin-form-group">
        <label>Notas</label>
        <input id="fmEditWlNotes" value="${escapeHtml(item.notes || "")}" placeholder="Opcional" />
      </div>
      <button type="submit" class="fin-form-submit">💾 Salvar Alterações</button>
    </form>
  `);
}

async function submitEditWatchlist(e) {
  e.preventDefault();
  const form = e.target;
  const wlId = Number(form.dataset.wlId);
  const body = {
    name: byId("fmEditWlName").value.trim(),
    asset_type: byId("fmEditWlType").value,
    target_price: byId("fmEditWlTarget").value ? Number(byId("fmEditWlTarget").value) : null,
    alert_above: byId("fmEditWlAlertAbove").value === "1",
    notes: byId("fmEditWlNotes").value.trim(),
  };
  try {
    const resp = await finFetch(`/api/finance/watchlist/${wlId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
      showToast("Watchlist atualizada!", "success");
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao atualizar watchlist");
    }
  } catch {
    showToast("Erro de rede");
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
    const resp = await finFetch("/api/finance/goals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao criar meta");
    }
  } catch {
    showToast("Erro de rede");
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
    const resp = await finFetch(`/api/finance/goals/${goalId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao salvar meta");
    }
  } catch {
    showToast("Erro de rede");
  }
}

async function deleteGoal(goalId) {
  if (!confirm("Excluir esta meta?")) return;
  try {
    await finFetch(`/api/finance/goals/${goalId}`, { method: "DELETE" });
    loadAll();
  } catch {
    showToast("Erro ao excluir meta");
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

  // Render monthly bar chart
  renderDividendsChart(divs);
}

function renderDividendsChart(divs) {
  const canvas = byId("dividendsChart");
  if (!canvas || !window.Chart) return;

  // Group by YYYY-MM
  const monthly = {};
  divs.forEach((d) => {
    const raw = d.pay_date || d.ex_date || d.created_at || "";
    const key = raw.slice(0, 7); // "YYYY-MM"
    if (!key) return;
    monthly[key] = (monthly[key] || 0) + (d.total_amount || 0);
  });

  const labels = Object.keys(monthly).sort();
  const data = labels.map((k) => monthly[k]);

  if (FIN.charts.dividends) {
    FIN.charts.dividends.destroy();
    delete FIN.charts.dividends;
  }

  FIN.charts.dividends = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Dividendos (R$)",
          data,
          backgroundColor: "rgba(16, 185, 129, 0.7)",
          borderColor: "rgba(16, 185, 129, 1)",
          borderWidth: 1,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${formatBRL(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            callback: (v) => `R$ ${Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`,
          },
        },
      },
    },
  });
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
    const resp = await finFetch("/api/finance/dividends", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      closeFinModal();
      loadAll();
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao registrar dividendo");
    }
  } catch {
    showToast("Erro de rede");
  }
}

async function deleteDividend(divId) {
  if (!confirm("Excluir este dividendo?")) return;
  try {
    await finFetch(`/api/finance/dividends/${divId}`, { method: "DELETE" });
    loadAll();
  } catch {
    showToast("Erro ao excluir dividendo");
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
  sel.innerHTML =
    `<option value="">Selecione...</option>`
    + `<option value="__total__" ${current === "__total__" ? "selected" : ""}>Total da carteira</option>`
    + opts;
}

const HISTORY_PREFS_KEY = "fin-history-prefs";

function readHistoryPrefs() {
  try {
    const raw = localStorage.getItem(HISTORY_PREFS_KEY);
    if (!raw) return {
      assetId: "", period: "180", compareTotal: false, benchmark: "", showInvested: true,
    };
    const parsed = JSON.parse(raw);
    return {
      assetId: String(parsed.assetId || ""),
      period: String(parsed.period || "180"),
      compareTotal: Boolean(parsed.compareTotal),
      benchmark: String(parsed.benchmark || ""),
      showInvested: parsed.showInvested !== false,
    };
  } catch {
    return {
      assetId: "", period: "180", compareTotal: false, benchmark: "", showInvested: true,
    };
  }
}

function saveHistoryPrefs() {
  const sel = byId("historyAssetSelect");
  const periodSel = byId("historyPeriodSelect");
  const compareEl = byId("historyCompareTotal");
  const benchmarkSel = byId("historyBenchmarkSelect");
  const investedEl = byId("historyShowInvested");
  if (!sel || !periodSel || !compareEl || !benchmarkSel || !investedEl) return;
  localStorage.setItem(HISTORY_PREFS_KEY, JSON.stringify({
    assetId: sel.value || "",
    period: periodSel.value || "180",
    compareTotal: compareEl.checked,
    benchmark: benchmarkSel.value || "",
    showInvested: investedEl.checked,
  }));
}

function applyHistoryPrefs() {
  const prefs = readHistoryPrefs();
  const sel = byId("historyAssetSelect");
  const periodSel = byId("historyPeriodSelect");
  const compareEl = byId("historyCompareTotal");
  const benchmarkSel = byId("historyBenchmarkSelect");
  const investedEl = byId("historyShowInvested");

  if (periodSel) {
    const allowed = ["30", "90", "180", "365"];
    periodSel.value = allowed.includes(prefs.period) ? prefs.period : "180";
  }
  if (compareEl) compareEl.checked = !!prefs.compareTotal;
  if (benchmarkSel) {
    const allowedB = ["", "ibov"];
    benchmarkSel.value = allowedB.includes(prefs.benchmark) ? prefs.benchmark : "";
  }
  if (investedEl) investedEl.checked = prefs.showInvested !== false;

  if (sel) {
    const validValues = new Set(["", "__total__", ...FIN.assets.map((a) => String(a.id))]);
    sel.value = validValues.has(prefs.assetId) ? prefs.assetId : "";
  }
}

function _historySeriesMap(rows) {
  const map = new Map();
  for (const row of rows || []) {
    const date = (row.captured_at || "").slice(0, 10);
    if (!date) continue;
    map.set(date, Number(row.price || 0));
  }
  return map;
}

function _historyRangeDays() {
  const periodSel = byId("historyPeriodSelect");
  return Number(periodSel?.value || 180);
}

async function loadHistoryFromControls() {
  const sel = byId("historyAssetSelect");
  const compareEl = byId("historyCompareTotal");
  const benchmarkSel = byId("historyBenchmarkSelect");
  const investedEl = byId("historyShowInvested");
  if (!sel) return;
  saveHistoryPrefs();
  await loadHistoryChart(sel.value, {
    compareTotal: !!(compareEl && compareEl.checked),
    rangeDays: _historyRangeDays(),
    benchmark: (benchmarkSel && benchmarkSel.value) || "",
    showInvested: !(investedEl && investedEl.checked === false),
  });
}

async function loadHistoryChart(assetId, options = {}) {
  const emptyEl = byId("historyEmpty");
  const canvas = byId("historyChart");
  if (!canvas) return;
  const isTotal = assetId === "__total__";
  const compareTotal = !!options.compareTotal;
  const rangeDays = Number(options.rangeDays || 180);
  const benchmark = String(options.benchmark || "").trim().toLowerCase();
  const showInvested = options.showInvested !== false;
  const limit = Math.min(365, Math.max(1, rangeDays));

  if (!assetId) {
    if (FIN.charts.history) { FIN.charts.history.destroy(); FIN.charts.history = null; }
    canvas.style.display = "none";
    if (emptyEl) emptyEl.style.display = "";
    return;
  }

  try {
    const reqs = [];
    reqs.push(
      finFetch(isTotal
        ? `/api/finance/portfolio-history?limit=${limit}`
        : `/api/finance/asset-history/${assetId}?limit=${limit}`
      ).then((r) => r.json())
    );
    if (!isTotal && compareTotal) {
      reqs.push(finFetch(`/api/finance/portfolio-history?limit=${limit}`).then((r) => r.json()));
    }
    if (showInvested) {
      const investedUrl = isTotal
        ? `/api/finance/invested-history?limit=${limit}`
        : `/api/finance/invested-history?asset_id=${encodeURIComponent(assetId)}&limit=${limit}`;
      reqs.push(finFetch(investedUrl).then((r) => r.json()));
    }
    if (benchmark) {
      reqs.push(finFetch(`/api/finance/benchmark-history?benchmark=${encodeURIComponent(benchmark)}&limit=${limit}`).then((r) => r.json()));
    }

    const [primaryData, totalData, investedData, benchmarkData] = await Promise.all(reqs);

    if (!primaryData.length) {
      canvas.style.display = "none";
      if (emptyEl) {
        emptyEl.style.display = "";
        emptyEl.textContent = isTotal
          ? "Sem dados históricos para o total da carteira ainda."
          : "Sem dados históricos para este ativo ainda.";
      }
      if (FIN.charts.history) { FIN.charts.history.destroy(); FIN.charts.history = null; }
      return;
    }

    canvas.style.display = "";
    if (emptyEl) emptyEl.style.display = "none";

    const primary = (primaryData || []).slice().reverse();
    const hasCompare = !isTotal && compareTotal && Array.isArray(totalData) && totalData.length > 0;

    let datasets = [];
    let labels = primary.map((d) => (d.captured_at || "").slice(0, 10));

    if (hasCompare) {
      const total = totalData.slice().reverse();
      const assetMap = _historySeriesMap(primary);
      const totalMap = _historySeriesMap(total);
      labels = [...new Set([...assetMap.keys(), ...totalMap.keys()])].sort();

      datasets.push({
        label: "Ativo (R$)",
        data: labels.map((d) => assetMap.get(d) ?? null),
        yAxisID: "y",
        borderColor: "#6366f1",
        backgroundColor: "rgba(99,102,241,0.08)",
        fill: false,
        tension: 0.3,
        pointRadius: labels.length > 60 ? 0 : 2,
        borderWidth: 2,
        spanGaps: true,
      });
      datasets.push({
        label: "Total da carteira (R$)",
        data: labels.map((d) => totalMap.get(d) ?? null),
        yAxisID: "y",
        borderColor: "#22c55e",
        backgroundColor: "rgba(34,197,94,0.08)",
        fill: false,
        tension: 0.3,
        pointRadius: labels.length > 60 ? 0 : 2,
        borderWidth: 2,
        spanGaps: true,
      });
    } else {
      const prices = primary.map((d) => Number(d.price || 0));
      datasets.push({
        label: isTotal ? "Total da carteira (R$)" : "Preço (R$)",
        data: prices,
        yAxisID: "y",
        borderColor: "#6366f1",
        backgroundColor: "rgba(99,102,241,0.1)",
        fill: true,
        tension: 0.3,
        pointRadius: prices.length > 60 ? 0 : 2,
        borderWidth: 2,
      });
    }

    if (benchmark && Array.isArray(benchmarkData) && benchmarkData.length) {
      const bMap = new Map();
      for (const row of benchmarkData) {
        const d = (row.captured_at || "").slice(0, 10);
        if (!d) continue;
        bMap.set(d, Number(row.normalized_pct || 0));
      }

      if (bMap.size) {
        const mergedLabels = [...new Set([...labels, ...bMap.keys()])].sort();
        datasets = datasets.map((ds) => {
          const map = new Map(labels.map((d, i) => [d, ds.data[i] ?? null]));
          return {
            ...ds,
            data: mergedLabels.map((d) => (map.has(d) ? map.get(d) : null)),
            spanGaps: true,
          };
        });
        datasets.push({
          label: benchmark === "ibov" ? "Benchmark IBOV (%)" : "Benchmark (%)",
          data: mergedLabels.map((d) => (bMap.has(d) ? bMap.get(d) : null)),
          yAxisID: "y1",
          borderColor: "#f59e0b",
          backgroundColor: "rgba(245,158,11,0.08)",
          fill: false,
          tension: 0.3,
          pointRadius: mergedLabels.length > 60 ? 0 : 2,
          borderWidth: 2,
          spanGaps: true,
        });
        labels = mergedLabels;
      }
    }

    if (showInvested && Array.isArray(investedData) && investedData.length) {
      const invMap = _historySeriesMap(investedData);
      if (invMap.size) {
        const mergedLabels = [...new Set([...labels, ...invMap.keys()])].sort();
        datasets = datasets.map((ds) => {
          const map = new Map(labels.map((d, i) => [d, ds.data[i] ?? null]));
          return {
            ...ds,
            data: mergedLabels.map((d) => (map.has(d) ? map.get(d) : null)),
            spanGaps: true,
          };
        });

        let last = null;
        const investedSeries = mergedLabels.map((d) => {
          if (invMap.has(d)) last = invMap.get(d);
          return last;
        });

        datasets.push({
          label: "Aporte acumulado (R$)",
          data: investedSeries,
          yAxisID: "y",
          borderColor: "#94a3b8",
          backgroundColor: "rgba(148,163,184,0.08)",
          borderDash: [6, 4],
          fill: false,
          tension: 0.2,
          pointRadius: mergedLabels.length > 60 ? 0 : 1.5,
          borderWidth: 2,
          spanGaps: true,
        });
        labels = mergedLabels;
      }
    }

    if (FIN.charts.history) FIN.charts.history.destroy();

    FIN.charts.history = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { intersect: false, mode: "index" },
        plugins: {
          legend: { display: datasets.length > 1 },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const raw = Number(ctx.raw || 0);
                if (ctx.dataset.yAxisID === "y1") {
                  return ` ${ctx.dataset.label}: ${formatPct(raw)}`;
                }
                return ` ${ctx.dataset.label}: ${formatBRL(raw)}`;
              },
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
          y1: {
            display: datasets.some((d) => d.yAxisID === "y1"),
            position: "right",
            grid: { drawOnChartArea: false },
            ticks: { color: "#f59e0b", font: { size: 10 }, callback: (v) => formatPct(v) },
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

  const aporteInput = byId("rebalAporteInput");
  const aporte = Math.max(0, Number((aporteInput && aporteInput.value) || 0));

  try {
    const resp = await finFetch(`/api/finance/rebalance?aporte=${encodeURIComponent(aporte)}`);
    const data = await resp.json();
    const suggestions = data.suggestions || [];

    if (!suggestions.length) {
      el.innerHTML = '<p class="fin-empty">Sem sugestões no momento.</p>';
      return;
    }

    const summary = `
      <div style="font-size:0.82rem;opacity:0.9;margin-bottom:8px;display:flex;gap:16px;flex-wrap:wrap;">
        <span>Carteira atual: <strong>${formatBRL(data.total_value || 0)}</strong></span>
        <span>Aporte: <strong>${formatBRL(data.aporte || 0)}</strong></span>
        <span>Total simulado: <strong>${formatBRL(data.total_after_aporte || 0)}</strong></span>
      </div>
    `;

    const rows = suggestions.map((s) => {
      const diffCls = s.diff_pct > 0 ? "fin-up" : s.diff_pct < 0 ? "fin-down" : "";
      const act = (s.action || "").toUpperCase();
      const actionCls = act === "COMPRAR" ? "fin-badge-buy" : act === "VENDER" ? "fin-badge-sell" : "fin-badge-stock";
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
          <div style="min-width:140px;font-size:0.8rem;opacity:0.9;text-align:right;">
            Aporte: <strong>${formatBRL(s.aporte_sugerido || 0)}</strong>
          </div>
          <span class="fin-badge ${actionCls}">${escapeHtml(s.action)}</span>
        </div>
      `;
    }).join("");

    el.innerHTML = `${summary}<div class="fin-rebal-list">${rows}</div>`;
  } catch (err) {
    console.error("Rebalance error:", err);
    el.innerHTML = '<p class="fin-empty">Erro ao calcular rebalanceamento.</p>';
  }
}

async function renderProjection() {
  const el = byId("finProjectionContent");
  if (!el) return;

  const monthsInput = byId("projectionMonthsInput");
  const aporteInput = byId("projectionAporteMensalInput");
  const months = Math.min(600, Math.max(1, Number((monthsInput && monthsInput.value) || 12)));
  const aporteMensal = Math.max(0, Number((aporteInput && aporteInput.value) || 0));

  try {
    const resp = await finFetch(
      `/api/finance/projection?months=${months}&aporte_mensal=${encodeURIComponent(aporteMensal)}`,
    );
    const data = await resp.json();
    const scenarios = data.scenarios || {};
    const rows = [
      ["conservador", "Conservador"],
      ["base", "Base"],
      ["otimista", "Otimista"],
    ].map(([key, label]) => {
      const item = scenarios[key] || {};
      const rate = Number(item.annual_rate || 0) * 100;
      const finalValue = Number(item.final_value || 0);
      return `
        <tr>
          <td>${label}</td>
          <td>${rate.toFixed(1)}% a.a.</td>
          <td>${formatBRL(finalValue)}</td>
        </tr>
      `;
    }).join("");

    el.innerHTML = `
      <div style="font-size:0.82rem;opacity:0.9;margin-bottom:8px;display:flex;gap:16px;flex-wrap:wrap;">
        <span>Valor atual: <strong>${formatBRL(data.current_value || 0)}</strong></span>
        <span>Horizonte: <strong>${Number(data.months || months)} meses</strong></span>
        <span>Aporte mensal: <strong>${formatBRL(data.aporte_mensal || 0)}</strong></span>
      </div>
      <table class="fin-table" style="margin-top:0;">
        <thead>
          <tr>
            <th>Cenário</th>
            <th>Retorno</th>
            <th>Patrimônio final</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  } catch (err) {
    console.error("Projection error:", err);
    el.innerHTML = '<p class="fin-empty">Erro ao calcular projeção.</p>';
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
    const resp = await finFetch("/api/finance/allocation-targets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets }),
    });
    if (resp.ok) {
      closeFinModal();
      // Reload targets
      const tResp = await finFetch("/api/finance/allocation-targets");
      FIN.allocationTargets = await tResp.json();
      renderRebalance();
    } else {
      showToast("Erro ao salvar metas");
    }
  } catch {
    showToast("Erro de rede");
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
    const resp = await finFetch(`/api/finance/ir-report?year=${year}`);
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
        // m.month is string like "2026-01" — extract month number
        const monthIdx = typeof m.month === "string" ? parseInt(m.month.split("-")[1], 10) - 1 : (m.month - 1);
        html += `
          <div class="${cls}">
            <span class="fin-ir-month-name">${monthNames[monthIdx] || m.month}</span>
            <span class="fin-ir-month-sell">${formatBRL(m.total_sell)}</span>
            <span class="fin-ir-month-pnl ${changeClass(m.profit)}">${formatBRL(m.profit)}</span>
            ${overLimit ? '<span class="fin-ir-darf">DARF</span>' : ""}
          </div>
        `;
      });
      html += "</div></div>";
    }

    // Dividend totals
    const totalDiv = data.total_dividends;
    const dividends = data.dividends || [];
    if (totalDiv || dividends.length) {
      html += '<div class="fin-ir-section"><h4>💸 Proventos no Ano</h4>';
      html += '<div class="fin-ir-divs">';
      if (totalDiv) {
        html += `<div class="fin-ir-div-row"><span>Total</span><strong>${formatBRL(totalDiv)}</strong></div>`;
      }
      // Group dividends by type
      const byType = {};
      dividends.forEach((d) => {
        const t = d.dividend_type || "dividendo";
        byType[t] = (byType[t] || 0) + (d.amount || 0);
      });
      Object.entries(byType).forEach(([type, val]) => {
        html += `<div class="fin-ir-div-row"><span>${escapeHtml(type)}</span><strong>${formatBRL(val)}</strong></div>`;
      });
      html += "</div></div>";
    }

    // Year-end positions
    const positions = data.positions_dec31 || [];
    if (positions.length) {
      html += '<div class="fin-ir-section"><h4>📋 Posição em 31/12</h4>';
      html += '<div class="fin-table-wrap"><table class="fin-table"><thead><tr><th>Ativo</th><th class="text-right">Qtd</th><th class="text-right">Custo Médio</th><th class="text-right">Total</th></tr></thead><tbody>';
      positions.forEach((p) => {
        html += `<tr>
          <td><strong>${escapeHtml(p.symbol)}</strong></td>
          <td class="text-right mono">${formatNumber(p.quantity)}</td>
          <td class="text-right mono">${formatBRL(p.avg_cost)}</td>
          <td class="text-right mono">${formatBRL(p.total_cost)}</td>
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

function renderWatchlistAlertsBanner(triggeredItems) {
  const banner = byId("finAlertsBanner");
  if (!banner) return;
  if (!triggeredItems || !triggeredItems.length) {
    banner.style.display = "none";
    banner.innerHTML = "";
    return;
  }

  const dismissed = JSON.parse(localStorage.getItem("fin_dismissed_banners") || "[]");
  const visible = triggeredItems.filter((w) => {
    const key = `${w.symbol}_${w.target_price}_${w.alert_above}`;
    return !dismissed.includes(key);
  });

  if (!visible.length) {
    banner.style.display = "none";
    banner.innerHTML = "";
    return;
  }

  const items = visible.map((w) => {
    const key = `${w.symbol}_${w.target_price}_${w.alert_above}`;
    const dir = w.alert_above ? "subiu acima de" : "caiu abaixo de";
    return `
      <div class="fin-alert-item" data-alert-key="${escapeHtml(key)}">
        <span class="fin-alert-icon">🔔</span>
        <span class="fin-alert-text">
          <strong>${escapeHtml(w.symbol)}</strong> ${dir}
          <strong>${formatBRL(w.target_price)}</strong> — Atual: ${formatBRL(w.current_price)}
        </span>
        <button class="fin-alert-dismiss" data-alert-key="${escapeHtml(key)}" aria-label="Dispensar alerta de ${escapeHtml(w.symbol)}">✕</button>
      </div>
    `;
  }).join("");

  banner.innerHTML = `
    <div class="fin-alerts-inner">
      ${items}
    </div>
  `;
  banner.style.display = "block";

  // Bind dismiss buttons
  banner.querySelectorAll(".fin-alert-dismiss").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.alertKey;
      const saved = JSON.parse(localStorage.getItem("fin_dismissed_banners") || "[]");
      if (!saved.includes(key)) saved.push(key);
      // Keep only last 50 dismissals
      if (saved.length > 50) saved.splice(0, saved.length - 50);
      localStorage.setItem("fin_dismissed_banners", JSON.stringify(saved));
      const item = banner.querySelector(`[data-alert-key="${CSS.escape(key)}"]`);
      if (item) item.remove();
      if (!banner.querySelectorAll(".fin-alert-item").length) {
        banner.style.display = "none";
      }
    });
  });
}

// ── Goals Milestones ─────────────────────────────────────

function checkGoalsMilestones(goals) {
  if (!goals || !goals.length) return;
  const MILESTONES = [25, 50, 75, 100];
  const stored = JSON.parse(localStorage.getItem("fin_goal_milestones") || "{}");
  let changed = false;

  goals.forEach((g) => {
    if (!g.target_amount || g.target_amount <= 0) return;
    const pct = Math.min(100, (g.current_amount / g.target_amount) * 100);
    const key = String(g.id);
    const prevMilestone = stored[key] || 0;

    const reached = MILESTONES.filter((m) => pct >= m && m > prevMilestone);
    if (reached.length) {
      const highest = Math.max(...reached);
      stored[key] = highest;
      changed = true;
      const icon = highest >= 100 ? "🎉" : "🎯";
      const label = highest >= 100 ? "Meta concluída!" : `${highest}% atingido!`;
      showToast(`${icon} "${escapeHtml(g.name)}" — ${label}`, "success");

      if (Notification.permission === "granted") {
        new Notification(`${icon} Meta: ${g.name}`, {
          body: `${label} Atual: ${formatBRL(g.current_amount)} / ${formatBRL(g.target_amount)}`,
          icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎯</text></svg>",
        });
      }
    }
  });

  if (changed) localStorage.setItem("fin_goal_milestones", JSON.stringify(stored));
}

function setupNotifications() {
  if (!("Notification" in window)) {
    showToast("Seu navegador não suporta notificações.");
    return;
  }
  if (Notification.permission === "granted") {
    showToast("Notificações já estão ativas! Você será alertado quando metas da watchlist forem atingidas.", "info");
    return;
  }
  Notification.requestPermission().then((perm) => {
    if (perm === "granted") {
      showToast("Notificações ativadas! Você será alertado quando metas da watchlist forem atingidas.", "success");
      checkWatchlistAlerts();
    }
  });
}

function checkWatchlistAlerts() {
  // Always render visual banner regardless of notification permission
  const triggered = FIN.watchlist.filter((w) => {
    if (w.current_price == null || !w.target_price) return false;
    return w.alert_above
      ? w.current_price >= w.target_price
      : w.current_price <= w.target_price;
  });
  renderWatchlistAlertsBanner(triggered);

  if (Notification.permission !== "granted") return;
  const notified = JSON.parse(localStorage.getItem("fin_notified_alerts") || "{}");
  const now = Date.now();
  // Prune entries older than 1 hour
  Object.keys(notified).forEach((k) => {
    if (now - notified[k] > 3600000) delete notified[k];
  });
  triggered.forEach((w) => {
      const key = `${w.symbol}_${w.target_price}_${w.alert_above}`;
      if (notified[key]) return; // Already notified recently
      notified[key] = now;
      const dir = w.alert_above ? "subiu acima" : "caiu abaixo";
      new Notification(`🔔 ${w.symbol} atingiu alvo!`, {
        body: `${w.symbol} ${dir} de ${formatBRL(w.target_price)} — Atual: ${formatBRL(w.current_price)}`,
        icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>💰</text></svg>",
      });
  });
  localStorage.setItem("fin_notified_alerts", JSON.stringify(notified));
}

// ══════════════════════════════════════════════════════════
// Finance Settings
// ══════════════════════════════════════════════════════════

async function openFinanceSettingsModal() {
  try {
    const resp = await finFetch("/api/finance/settings");
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Erro ao carregar configurações", "error");
      return;
    }

    openFinModal("Configurações Financeiras", `
      <form data-form-action="submitFinanceSettings">
        <p class="fin-empty" style="text-align:left;margin-bottom:12px">
          Ajuste API keys e provedores do módulo financeiro. Para campos de chave,
          deixe em branco para manter o valor atual.
        </p>

        <div class="fin-form-group">
          <label>BRAPI Token</label>
          <input type="password" id="finSetBrapiToken" placeholder="${data.brapi_token_set ? "•••••••• (já configurado)" : "cole seu token aqui"}" autocomplete="off" />
        </div>

        <div class="fin-form-group">
          <label>Finance API Key</label>
          <input type="password" id="finSetFinanceApiKey" placeholder="${data.finance_api_key_set ? "•••••••• (já configurado)" : "opcional"}" autocomplete="off" />
        </div>

        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>IA local habilitada</label>
            <select id="finSetAiEnabled">
              <option value="1" ${String(data.ai_local_enabled) === "1" ? "selected" : ""}>Sim</option>
              <option value="0" ${String(data.ai_local_enabled) === "0" ? "selected" : ""}>Não</option>
            </select>
          </div>
          <div class="fin-form-group">
            <label>Timeout IA (segundos)</label>
            <input type="number" id="finSetAiTimeout" min="5" max="300" value="${escapeHtml(data.ai_local_timeout_seconds || "45")}" />
          </div>
        </div>

        <div class="fin-form-group">
          <label>URL IA Local</label>
          <input type="url" id="finSetAiUrl" value="${escapeHtml(data.ai_local_url || "")}" />
        </div>

        <div class="fin-form-group">
          <label>Modelo IA</label>
          <input type="text" id="finSetAiModel" value="${escapeHtml(data.ai_local_model || "")}" />
        </div>

        <div class="fin-form-group">
          <label>URL API de Câmbio</label>
          <input type="url" id="finSetCurrencyApi" value="${escapeHtml(data.currency_api_url || "")}" />
        </div>

        <div class="fin-form-group">
          <label>Atualização de câmbio (min)</label>
          <input type="number" id="finSetCurrencyUpdate" min="1" max="1440" value="${escapeHtml(data.currency_update_minutes || "15")}" />
        </div>

        <button type="submit" class="fin-form-submit">💾 Salvar configurações</button>
      </form>
    `);
  } catch {
    showToast("Erro de rede ao carregar configurações", "error");
  }
}

async function submitFinanceSettings() {
  const payload = {
    ai_local_enabled: byId("finSetAiEnabled")?.value || "1",
    ai_local_timeout_seconds: byId("finSetAiTimeout")?.value || "45",
    ai_local_url: byId("finSetAiUrl")?.value?.trim() || "",
    ai_local_model: byId("finSetAiModel")?.value?.trim() || "",
    currency_api_url: byId("finSetCurrencyApi")?.value?.trim() || "",
    currency_update_minutes: byId("finSetCurrencyUpdate")?.value || "15",
  };

  const brapiToken = byId("finSetBrapiToken")?.value?.trim() || "";
  const financeApiKey = byId("finSetFinanceApiKey")?.value?.trim() || "";
  if (brapiToken) payload.brapi_token = brapiToken;
  if (financeApiKey) payload.finance_api_key = financeApiKey;

  try {
    const resp = await finFetch("/api/finance/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();

    if (!resp.ok) {
      showToast(data.error || "Erro ao salvar configurações", "error");
      return;
    }

    showToast("Configurações salvas com sucesso!", "success");
    closeFinModal();
    loadAll();
  } catch {
    showToast("Erro de rede ao salvar configurações", "error");
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
    const resp = await finFetch("/api/finance/ai-analysis", {
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
    const resp = await finFetch("/api/finance/ai-chat", {
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
  initFinanceKeyboardShortcuts();
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
  bind("btnFinanceSettings", openFinanceSettingsModal);
  bind("btnNotifications", setupNotifications);
  bind("finAIChatSend", sendFinAIChat);
  bind("finModalClose", closeFinModal);
  bind("btnRunRebalanceSim", renderRebalance);
  bind("btnRunProjection", renderProjection);

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
  const histPeriodSel = byId("historyPeriodSelect");
  const histBenchmarkSel = byId("historyBenchmarkSelect");
  const histInvested = byId("historyShowInvested");
  const histCompare = byId("historyCompareTotal");
  if (histSel) {
    histSel.addEventListener("change", loadHistoryFromControls);
  }
  if (histPeriodSel) histPeriodSel.addEventListener("change", loadHistoryFromControls);
  if (histBenchmarkSel) histBenchmarkSel.addEventListener("change", loadHistoryFromControls);
  if (histInvested) histInvested.addEventListener("change", loadHistoryFromControls);
  if (histCompare) histCompare.addEventListener("change", loadHistoryFromControls);

  const rebalAporteInput = byId("rebalAporteInput");
  const projectionMonthsInput = byId("projectionMonthsInput");
  const projectionAporteMensalInput = byId("projectionAporteMensalInput");
  if (rebalAporteInput) rebalAporteInput.addEventListener("change", renderRebalance);
  if (projectionMonthsInput) projectionMonthsInput.addEventListener("change", renderProjection);
  if (projectionAporteMensalInput) projectionAporteMensalInput.addEventListener("change", renderProjection);

  // IR report: year select
  const irSel = byId("irYearSelect");
  if (irSel) {
    irSel.addEventListener("change", () => loadIRReport(irSel.value));
  }

  // ── Event delegation for dynamic buttons (CSP-safe) ──
  const actionMap = {
    deleteAsset,
    deleteTransaction,
    deleteWatchlistItem,
    deleteGoal,
    openEditGoalModal,
    deleteDividend,
    openEditTransactionModal,
    openEditWatchlistModal,
    addTxForAsset,
  };
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;

    // Pagination actions
    if (action === "txPagePrev") { _txPage = Math.max(0, _txPage - 1); renderTransactions(FIN.transactions); return; }
    if (action === "txPageNext") { _txPage++; renderTransactions(FIN.transactions); return; }

    const fn = actionMap[action];
    if (fn) fn(Number(btn.dataset.id));
  });

  // ── Form delegation (data-form-action) ──────────────
  const formMap = {
    submitEditTransaction,
    submitEditWatchlist,
  };
  document.addEventListener("submit", (e) => {
    const fa = e.target.dataset.formAction;
    if (!fa) return;
    const fn = formMap[fa];
    if (fn) fn(e);
  });

  initAutoRefresh();
});

// ── Auto-refresh ──────────────────────────────────────
function initAutoRefresh() {
  const sel = byId("autoRefreshSelect");
  if (!sel) return;
  const saved = localStorage.getItem("fin_auto_refresh") ?? "300";
  sel.value = saved;
  _startAutoRefresh(Number(saved));
  sel.addEventListener("change", () => {
    localStorage.setItem("fin_auto_refresh", sel.value);
    _startAutoRefresh(Number(sel.value));
  });
}

function _startAutoRefresh(seconds) {
  if (FIN._autoRefreshInterval) clearInterval(FIN._autoRefreshInterval);
  FIN._autoRefreshInterval = null;
  if (seconds > 0) {
    FIN._autoRefreshInterval = setInterval(loadAll, seconds * 1000);
  }
}

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
  passiveIncomeGoal: null,
  allocationTargets: [],
  charts: {},
  // auto-refresh
  _autoRefreshInterval: null,
  // portfolio sort
  _portfolioSort: { col: null, dir: 1 },
  _portfolioPage: 0,
  // transactions sort + filter
  _txSort: { col: null, dir: 1 },
  _txFilter: { asset: "", type: "", dateFrom: "", dateTo: "", minTotal: "", maxTotal: "" },
  _txSelected: {},
  performanceMetrics: null,
  _rebalanceLoaded: false,
  _secondaryCache: { ts: 0, payload: null },
  _marketStaleNotified: false,
  _perf: { seq: 0, lastRunId: 0, runs: {}, last: null, history: [] },
  flags: {},
};

const SECONDARY_CACHE_TTL_MS = 25000;
const MARKET_SNAPSHOT_KEY = "fin_market_snapshot_v1";
const MARKET_SNAPSHOT_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const FIN_FLAGS_STORAGE_KEY = "fin_feature_flags";
const FIN_FLAGS_DEFAULT = {
  a11yEnhancements: true,
  keyboardShortcuts: true,
  sectionQuickNav: true,
  featureFlagsUI: true,
  perfTelemetry: true,
  lazyRebalanceLoad: true,
  secondaryPanelCache: true,
};

const FIN_FLAG_LABELS = {
  a11yEnhancements: "Melhorias de acessibilidade",
  keyboardShortcuts: "Atalhos globais de teclado",
  sectionQuickNav: "Navegação por seções (Alt+1..9)",
  featureFlagsUI: "Painel de feature flags",
  perfTelemetry: "Métricas de performance no carregamento",
  lazyRebalanceLoad: "Lazy load de rebalanceamento/projeção",
  secondaryPanelCache: "Cache dos painéis secundários no auto-refresh",
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

async function fetchFinanceJson(url, fallbackValue) {
  try {
    const response = await finFetch(url);
    if (!response.ok) {
      console.warn("Finance endpoint returned non-OK status", { url, status: response.status });
      return fallbackValue;
    }
    return await response.json();
  } catch (err) {
    console.warn("Finance endpoint request failed", { url, err });
    return fallbackValue;
  }
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

function _readFinFlagsFromMeta() {
  const meta = document.querySelector('meta[name="finance-flags"]');
  const raw = meta ? String(meta.getAttribute("content") || "").trim() : "";
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function _readFinFlagsFromStorage() {
  try {
    const raw = localStorage.getItem(FIN_FLAGS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function resolveFinanceFlags() {
  const metaFlags = _readFinFlagsFromMeta();
  const storedFlags = _readFinFlagsFromStorage();
  const merged = { ...FIN_FLAGS_DEFAULT, ...metaFlags, ...storedFlags };
  return Object.fromEntries(Object.entries(merged).map(([k, v]) => [k, Boolean(v)]));
}

function isFinFlagOn(flagName) {
  if (!flagName) return false;
  if (!FIN.flags || typeof FIN.flags !== "object") return Boolean(FIN_FLAGS_DEFAULT[flagName]);
  if (Object.prototype.hasOwnProperty.call(FIN.flags, flagName)) return Boolean(FIN.flags[flagName]);
  return Boolean(FIN_FLAGS_DEFAULT[flagName]);
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
  if (!isFinFlagOn("keyboardShortcuts")) return;
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

function initSectionQuickNav() {
  if (!isFinFlagOn("sectionQuickNav")) return;
  const sectionMap = {
    "1": "finPortfolioCard",
    "2": "finTransactionsCard",
    "3": "finDividendsCard",
    "4": "finHistoryCard",
    "5": "finRebalanceCard",
    "6": "finPerformanceCard",
    "7": "finWatchlistCard",
    "8": "finGoalsCard",
    "9": "finAICard",
  };

  document.addEventListener("keydown", (e) => {
    const tag = document.activeElement && document.activeElement.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const targetId = sectionMap[e.key];
    if (!targetId) return;

    const target = byId(targetId);
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    target.focus({ preventScroll: true });
    target.classList.add("fin-quick-focus");
    setTimeout(() => target.classList.remove("fin-quick-focus"), 1200);
  });
}

function initA11yEnhancements() {
  if (!isFinFlagOn("a11yEnhancements")) return;

  document.querySelectorAll(".fin-card[id]").forEach((card) => {
    if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
    const title = card.querySelector("h2");
    if (title && !card.getAttribute("aria-label")) {
      card.setAttribute("aria-label", title.textContent.trim().replace(/\s+/g, " "));
    }
  });

  const updated = byId("finLastUpdated");
  if (updated) {
    updated.setAttribute("role", "status");
    updated.setAttribute("aria-live", "polite");
    updated.setAttribute("aria-atomic", "true");
  }
}

function showKeyboardShortcutsHelp() {
  openFinModal("Atalhos de Teclado", `
    <div class="fin-shortcuts-list">
      <div class="fin-shortcut-row"><kbd>Ctrl+R</kbd><span>Atualizar dados</span></div>
      <div class="fin-shortcut-row"><kbd>Ctrl+I</kbd><span>Importar Excel/CSV</span></div>
      <div class="fin-shortcut-row"><kbd>Ctrl+E</kbd><span>Exportar dados</span></div>
      <div class="fin-shortcut-row"><kbd>Alt+1..9</kbd><span>Navegar para cards principais</span></div>
      <div class="fin-shortcut-row"><kbd>?</kbd><span>Mostrar atalhos</span></div>
      <div class="fin-shortcut-row"><kbd>Esc</kbd><span>Fechar modal</span></div>
    </div>
  `);
}

function openFeatureFlagsModal() {
  const rows = Object.keys(FIN_FLAGS_DEFAULT).map((key) => `
    <label class="fin-shortcut-row" style="justify-content:space-between;gap:14px;align-items:center;">
      <span>${escapeHtml(FIN_FLAG_LABELS[key] || key)}</span>
      <input type="checkbox" class="fin-flag-check" data-flag="${key}" ${isFinFlagOn(key) ? "checked" : ""} />
    </label>
  `).join("");

  openFinModal("Feature Flags", `
    <form id="finFeatureFlagsForm">
      <p class="fin-empty" style="text-align:left;margin-bottom:10px;">Controle de recursos por ambiente. Alterações são salvas no navegador atual.</p>
      <div class="fin-shortcuts-list">${rows}</div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
        <button type="button" id="finFlagsReset" class="btn-text">Restaurar padrão</button>
        <button type="submit" class="fin-form-submit">Salvar e aplicar</button>
      </div>
    </form>
  `);

  const form = byId("finFeatureFlagsForm");
  const resetBtn = byId("finFlagsReset");

  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      localStorage.removeItem(FIN_FLAGS_STORAGE_KEY);
      closeFinModal();
      showToast("Feature flags restauradas para o padrão.", "success");
      window.location.reload();
    });
  }

  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const nextFlags = { ...FIN_FLAGS_DEFAULT };
      form.querySelectorAll(".fin-flag-check[data-flag]").forEach((el) => {
        nextFlags[el.dataset.flag] = el.checked;
      });
      localStorage.setItem(FIN_FLAGS_STORAGE_KEY, JSON.stringify(nextFlags));
      closeFinModal();
      showToast("Feature flags atualizadas. Recarregando...", "info");
      window.location.reload();
    });
  }
}

// ══════════════════════════════════════════════════════════
// Data Loading
// ══════════════════════════════════════════════════════════

async function loadAll(options = {}) {
  const useSecondaryCache = options.useSecondaryCache === true;
  const perfEnabled = isFinFlagOn("perfTelemetry");
  const perfRunId = perfEnabled ? ++FIN._perf.seq : 0;
  if (perfEnabled) {
    FIN._perf.lastRunId = perfRunId;
    FIN._perf.runs[perfRunId] = {
    runId: perfRunId,
    source: useSecondaryCache ? "auto" : "manual",
    startedAt: performance.now(),
    criticalFetchMs: null,
    criticalRenderMs: null,
    deferredChartsMs: null,
    secondaryMs: null,
    secondaryCacheHit: false,
  };
  }
  try {
    const criticalFetchStart = perfEnabled ? performance.now() : 0;
    const [summary, transactions, watchlist, goals, assets, dividends, allocTargets, passiveGoal] = await Promise.all([
      fetchFinanceJson("/api/finance/summary", { portfolio: [], currency_rates: [] }),
      fetchFinanceJson("/api/finance/transactions", []),
      fetchFinanceJson("/api/finance/watchlist", []),
      fetchFinanceJson("/api/finance/goals", []),
      fetchFinanceJson("/api/finance/assets", []),
      fetchFinanceJson("/api/finance/dividends", []),
      fetchFinanceJson("/api/finance/allocation-targets", []),
      fetchFinanceJson("/api/finance/goals/passive-income", { target_monthly: 0, note: "" }),
    ]);
    if (perfEnabled) _setPerfRunPatch(perfRunId, { criticalFetchMs: _ms(performance.now() - criticalFetchStart) });

    FIN.summary = summary || { portfolio: [], currency_rates: [] };
    FIN.portfolio = FIN.summary.portfolio || [];
    FIN.transactions = Array.isArray(transactions) ? transactions : [];
    FIN.watchlist = Array.isArray(watchlist) ? watchlist : [];
    FIN.goals = Array.isArray(goals) ? goals : [];
    FIN.assets = (Array.isArray(assets) ? assets : []).map((a) => ({
      id: a.id,
      symbol: a.symbol,
      name: a.name || a.symbol,
      asset_type: a.asset_type,
    }));
    FIN.dividends = Array.isArray(dividends) ? dividends : [];
    FIN.passiveIncomeGoal = passiveGoal || { target_monthly: 0, note: "" };
    FIN.allocationTargets = Array.isArray(allocTargets) ? allocTargets : [];

    const criticalRenderStart = perfEnabled ? performance.now() : 0;
    renderSummary(summary);
    renderCurrency(summary.currency_rates || []);
    renderPortfolio(FIN.portfolio);
    renderTransactions(transactions);
    renderWatchlist(watchlist);
    renderGoals(goals);
    renderDividends(FIN.dividends);
    if (FIN._rebalanceLoaded) {
      renderRebalance();
      renderProjection();
      renderDividendCeiling();
      renderIndependenceScenario();
    }
    populateHistorySelect();
    applyHistoryPrefs();
    loadHistoryFromControls();
    populateIRYears();
    checkWatchlistAlerts();
    checkDividendAlerts();
    checkGoalsMilestones(goals);
    if (perfEnabled) {
      _setPerfRunPatch(perfRunId, { criticalRenderMs: _ms(performance.now() - criticalRenderStart) });
      _commitPerf(perfRunId);
    }
    updateLastUpdated();

    // Defer chart creation to keep first paint responsive.
    _scheduleDeferred(() => {
      const deferredChartsStart = perfEnabled ? performance.now() : 0;
      renderAllocationChart(summary);
      renderPnLChart(FIN.portfolio);
      renderPerformanceChart(FIN.portfolio);
      if (perfEnabled) {
        _setPerfRunPatch(perfRunId, { deferredChartsMs: _ms(performance.now() - deferredChartsStart) });
        _commitPerf(perfRunId);
      }
    });

    // Fetch non-critical widgets in background.
    _loadSecondaryPanels({ useCache: useSecondaryCache }).then((meta) => {
      if (perfEnabled) {
        _setPerfRunPatch(perfRunId, {
          secondaryMs: meta?.durationMs ?? null,
          secondaryCacheHit: meta?.cacheHit === true,
        });
        _commitPerf(perfRunId);
      }
      updateLastUpdated();
    });
  } catch (err) {
    console.error("Finance load error:", err);
    if (perfEnabled) {
      _setPerfRunPatch(perfRunId, { error: true });
      _commitPerf(perfRunId);
    }
  }
}

function _ms(v) {
  return Number(v.toFixed(1));
}

function _setPerfRunPatch(runId, patch) {
  const run = FIN._perf.runs[runId];
  if (!run) return;
  Object.assign(run, patch || {});
}

function _commitPerf(runId) {
  const run = FIN._perf.runs[runId];
  if (!run) return;
  if (runId !== FIN._perf.lastRunId) {
    delete FIN._perf.runs[runId];
    return;
  }

  const committed = {
    runId,
    source: run.source,
    totalMs: _ms(performance.now() - run.startedAt),
    criticalFetchMs: run.criticalFetchMs,
    criticalRenderMs: run.criticalRenderMs,
    deferredChartsMs: run.deferredChartsMs,
    secondaryMs: run.secondaryMs,
    secondaryCacheHit: !!run.secondaryCacheHit,
    error: !!run.error,
    at: new Date().toISOString(),
  };
  FIN._perf.last = committed;
  FIN._perf.history.push(committed);
  if (FIN._perf.history.length > 30) FIN._perf.history.splice(0, FIN._perf.history.length - 30);

  // Keep an observable trace for before/after comparison in DevTools.
  console.info("[finance-perf]", committed);
}

function _scheduleDeferred(fn) {
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(fn, { timeout: 1200 });
    return;
  }
  setTimeout(fn, 0);
}

function _readMarketSnapshot() {
  try {
    const raw = localStorage.getItem(MARKET_SNAPSHOT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return {
      market: parsed.market || {},
      ts: Number(parsed.ts || 0) || 0,
      ageMs: Math.max(0, Date.now() - (Number(parsed.ts || 0) || 0)),
      isExpired: (Date.now() - (Number(parsed.ts || 0) || 0)) > MARKET_SNAPSHOT_MAX_AGE_MS,
    };
  } catch {
    return null;
  }
}

function _saveMarketSnapshot(market) {
  if (!market || typeof market !== "object") return;
  const hasIndices = Object.keys(market.indices || {}).length > 0;
  if (!hasIndices) return;
  try {
    localStorage.setItem(MARKET_SNAPSHOT_KEY, JSON.stringify({ market, ts: Date.now() }));
  } catch {
    // ignore storage issues
  }
}

function renderMarketDataHealth(meta = {}) {
  const card = byId("finIndicesCard");
  if (!card) return;
  const title = card.querySelector("h2");
  if (!title) return;
  let chip = byId("finMarketDataHealth");
  if (!chip) {
    chip = document.createElement("span");
    chip.id = "finMarketDataHealth";
    chip.className = "fin-market-health fin-market-health--ok";
    title.appendChild(chip);
  }

  const stale = !!meta.stale;
  if (!stale) {
    chip.className = "fin-market-health fin-market-health--ok";
    chip.textContent = "ao vivo";
    chip.title = "Dados de mercado em tempo real";
    FIN._marketStaleNotified = false;
    return;
  }

  const expired = !!meta.snapshotExpired;
  chip.className = `fin-market-health ${expired ? "fin-market-health--expired" : "fin-market-health--stale"}`;
  chip.textContent = expired ? "snapshot antigo" : "dados defasados";
  chip.title = meta.snapshotAt
    ? `Usando snapshot local de ${new Date(meta.snapshotAt).toLocaleString("pt-BR")}`
    : "Sem snapshot local disponível";

  if (meta.snapshotAt && expired) {
    const ageHours = Math.floor((Number(meta.snapshotAgeMs || 0) || 0) / 3600000);
    chip.title += ` (idade aproximada: ${ageHours}h)`;
  }

  if (meta.snapshotAt && !FIN._marketStaleNotified) {
    FIN._marketStaleNotified = true;
    showToast(
      expired
        ? "Mercado indisponível. Snapshot antigo (>24h), valide os dados quando o feed voltar."
        : "Mercado indisponível no momento. Exibindo último snapshot salvo.",
      expired ? "error" : "info",
    );
  }
}

async function refreshPortfolioPanels() {
  const [summary, transactions, assets, allocTargets] = await Promise.all([
    finFetch("/api/finance/summary").then((r) => r.json()),
    finFetch("/api/finance/transactions").then((r) => r.json()),
    finFetch("/api/finance/assets").then((r) => r.json()),
    finFetch("/api/finance/allocation-targets").then((r) => r.json()),
  ]);

  FIN.summary = summary;
  FIN.portfolio = summary.portfolio || [];
  FIN.transactions = transactions || [];
  FIN.assets = (assets || []).map((a) => ({
    id: a.id,
    symbol: a.symbol,
    name: a.name || a.symbol,
    asset_type: a.asset_type,
  }));
  FIN.allocationTargets = allocTargets || [];

  renderSummary(summary);
  renderCurrency(summary.currency_rates || []);
  renderPortfolio(FIN.portfolio);
  renderTransactions(FIN.transactions);
  populateHistorySelect();
  applyHistoryPrefs();
  await loadHistoryFromControls();

  _scheduleDeferred(() => {
    renderAllocationChart(summary);
    renderPnLChart(FIN.portfolio);
    renderPerformanceChart(FIN.portfolio);
  });

  if (FIN._rebalanceLoaded) {
    renderRebalance();
    renderProjection();
    renderDividendCeiling();
    renderIndependenceScenario();
  }
  updateLastUpdated();
}

async function refreshWatchlistPanel() {
  FIN.watchlist = await finFetch("/api/finance/watchlist").then((r) => r.json());
  renderWatchlist(FIN.watchlist);
  checkWatchlistAlerts();
  updateLastUpdated();
}

async function refreshGoalsPanel() {
  const [goals, passiveGoal] = await Promise.all([
    finFetch("/api/finance/goals").then((r) => r.json()),
    finFetch("/api/finance/goals/passive-income").then((r) => r.json()),
  ]);
  FIN.goals = goals;
  FIN.passiveIncomeGoal = passiveGoal || { target_monthly: 0, note: "" };
  renderGoals(FIN.goals);
  checkGoalsMilestones(FIN.goals);
  updateLastUpdated();
}

async function refreshDividendsPanels() {
  const [summary, dividends] = await Promise.all([
    finFetch("/api/finance/summary").then((r) => r.json()),
    finFetch("/api/finance/dividends").then((r) => r.json()),
  ]);
  FIN.summary = summary;
  FIN.dividends = dividends || [];
  renderSummary(summary);
  renderDividends(FIN.dividends);
  renderGoals(FIN.goals || []);
  if (FIN._rebalanceLoaded) {
    renderDividendCeiling();
  }
  checkDividendAlerts();
  updateLastUpdated();
}

async function refreshImportPanels() {
  const [summary, transactions, assets, allocTargets, dividends] = await Promise.all([
    finFetch("/api/finance/summary").then((r) => r.json()),
    finFetch("/api/finance/transactions").then((r) => r.json()),
    finFetch("/api/finance/assets").then((r) => r.json()),
    finFetch("/api/finance/allocation-targets").then((r) => r.json()),
    finFetch("/api/finance/dividends").then((r) => r.json()),
  ]);

  FIN.summary = summary;
  FIN.portfolio = summary.portfolio || [];
  FIN.transactions = transactions || [];
  FIN.assets = (assets || []).map((a) => ({
    id: a.id,
    symbol: a.symbol,
    name: a.name || a.symbol,
    asset_type: a.asset_type,
  }));
  FIN.allocationTargets = allocTargets || [];
  FIN.dividends = dividends || [];

  renderSummary(summary);
  renderCurrency(summary.currency_rates || []);
  renderPortfolio(FIN.portfolio);
  renderTransactions(FIN.transactions);
  renderDividends(FIN.dividends);
  renderGoals(FIN.goals || []);
  checkDividendAlerts();

  populateHistorySelect();
  applyHistoryPrefs();
  await loadHistoryFromControls();

  _scheduleDeferred(() => {
    renderAllocationChart(summary);
    renderPnLChart(FIN.portfolio);
    renderPerformanceChart(FIN.portfolio);
  });

  if (FIN._rebalanceLoaded) {
    renderRebalance();
    renderProjection();
    renderDividendCeiling();
    renderIndependenceScenario();
  }
  updateLastUpdated();
}

async function refreshByDomains(domains) {
  const requested = Array.isArray(domains) ? domains : [];
  const normalized = [...new Set(requested.map((d) => String(d || "").trim()).filter(Boolean))];
  if (!normalized.length) return;

  if (normalized.includes("full")) {
    await loadAll();
    return;
  }

  if (normalized.includes("import")) {
    await refreshImportPanels();
    return;
  }

  const handlers = {
    portfolio: refreshPortfolioPanels,
    watchlist: refreshWatchlistPanel,
    goals: refreshGoalsPanel,
    dividends: refreshDividendsPanels,
  };

  for (const domain of normalized) {
    const handler = handlers[domain];
    if (!handler) continue;
    await handler();
  }
}

function inferDomainsFromAiActions(actions) {
  const list = Array.isArray(actions) ? actions : [];
  if (!list.length) return [];

  const domains = new Set();
  for (const act of list) {
    if (!act || act.ok === false) continue;
    const action = String(act.action || "").toLowerCase();

    if (["buy", "sell", "add_transaction", "update_transaction", "delete_transaction", "add_asset", "delete_asset"].includes(action)) {
      domains.add("portfolio");
      continue;
    }
    if (["add_watchlist", "update_watchlist", "delete_watchlist", "remove_watchlist"].includes(action)) {
      domains.add("watchlist");
      continue;
    }
    if (["add_goal", "update_goal", "delete_goal"].includes(action)) {
      domains.add("goals");
      continue;
    }
    if (["add_dividend", "update_dividend", "delete_dividend"].includes(action)) {
      domains.add("dividends");
      continue;
    }

    // Unknown action: safer fallback.
    domains.add("full");
  }

  return [...domains];
}

async function _loadSecondaryPanels(options = {}) {
  const started = performance.now();
  const useCache = options.useCache === true && isFinFlagOn("secondaryPanelCache");
  const now = Date.now();
  if (
    useCache
    && FIN._secondaryCache
    && FIN._secondaryCache.payload
    && (now - Number(FIN._secondaryCache.ts || 0) <= SECONDARY_CACHE_TTL_MS)
  ) {
    const cached = FIN._secondaryCache.payload;
    FIN.marketData = cached.market || {};
    FIN.performanceMetrics = cached.metrics && !cached.metrics.error ? cached.metrics : null;
    renderIndices((FIN.marketData && FIN.marketData.indices) || {});
    renderMarketDataHealth({
      stale: !!cached.marketStale,
      snapshotAt: cached.marketSnapshotAt || null,
      snapshotAgeMs: cached.marketSnapshotAgeMs || 0,
      snapshotExpired: !!cached.marketSnapshotExpired,
    });
    renderPerformanceMetrics(FIN.performanceMetrics);
    renderAuditTrail(Array.isArray(cached.audit) ? cached.audit : []);
    return { cacheHit: true, durationMs: _ms(performance.now() - started) };
  }

  const [marketMeta, metrics, audit] = await Promise.all([
    (async () => {
      try {
        const resp = await finFetch("/api/finance/market-data");
        if (!resp.ok) throw new Error(`market status ${resp.status}`);
        const live = await resp.json();
        _saveMarketSnapshot(live);
        return {
          market: live || {},
          stale: false,
          snapshotAt: null,
          snapshotAgeMs: 0,
          snapshotExpired: false,
        };
      } catch {
        const snap = _readMarketSnapshot();
        if (snap && snap.market) {
          return {
            market: snap.market,
            stale: true,
            snapshotAt: snap.ts || null,
            snapshotAgeMs: snap.ageMs || 0,
            snapshotExpired: !!snap.isExpired,
          };
        }
        return {
          market: {},
          stale: true,
          snapshotAt: null,
          snapshotAgeMs: 0,
          snapshotExpired: true,
        };
      }
    })(),
    finFetch("/api/finance/metrics/performance").then((r) => r.json()).catch(() => null),
    finFetch("/api/finance/audit?limit=15").then((r) => r.json()).catch(() => []),
  ]);

  FIN.marketData = marketMeta.market || {};
  FIN.performanceMetrics = metrics && !metrics.error ? metrics : null;
  FIN._secondaryCache = {
    ts: Date.now(),
    payload: {
      market: FIN.marketData,
      marketStale: !!marketMeta.stale,
      marketSnapshotAt: marketMeta.snapshotAt || null,
      marketSnapshotAgeMs: marketMeta.snapshotAgeMs || 0,
      marketSnapshotExpired: !!marketMeta.snapshotExpired,
      metrics,
      audit,
    },
  };

  renderIndices((FIN.marketData && FIN.marketData.indices) || {});
  renderMarketDataHealth(marketMeta);
  renderPerformanceMetrics(FIN.performanceMetrics);
  renderAuditTrail(Array.isArray(audit) ? audit : []);
  return { cacheHit: false, durationMs: _ms(performance.now() - started) };
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

function renderPerformanceMetrics(metrics) {
  const el = byId("finPerformanceMetrics");
  if (!el) return;
  if (!metrics) {
    el.innerHTML = "";
    return;
  }
  const irr = metrics.irr_pct == null ? "—" : `${formatNumber(metrics.irr_pct, 2)}%`;
  el.innerHTML = `
    <div class="fin-mini-metric">
      <span>Retorno simples</span>
      <strong class="${changeClass(metrics.simple_return_pct)}">${formatNumber(metrics.simple_return_pct, 2)}%</strong>
    </div>
    <div class="fin-mini-metric">
      <span>IRR (anualizada)</span>
      <strong>${irr}</strong>
    </div>
    <div class="fin-mini-metric">
      <span>Patrimônio</span>
      <strong>${formatBRL(metrics.current_value)}</strong>
    </div>
  `;
}

function renderAuditTrail(entries) {
  const el = byId("finAuditContent");
  if (!el) return;
  if (!entries || !entries.length) {
    el.innerHTML = '<p class="fin-empty">Sem eventos recentes.</p>';
    return;
  }
  el.innerHTML = entries.map((e) => {
    const ts = String(e.created_at || "").replace("T", " ").slice(0, 19);
    return `
      <div class="fin-audit-item">
        <span class="fin-audit-time">${escapeHtml(ts)}</span>
        <span class="fin-audit-action">${escapeHtml(e.action || "")}</span>
        <span class="fin-audit-target">${escapeHtml(e.target_type || "")} #${escapeHtml(String(e.target_id || "-"))}</span>
      </div>
    `;
  }).join("");
}

function checkDividendAlerts() {
  const total = (FIN.dividends || []).reduce((sum, d) => sum + (d.total_amount || 0), 0);
  const key = "fin_last_dividend_total";
  const prev = Number(localStorage.getItem(key) || "0");
  if (total > prev && prev > 0) {
    showToast(`Novo provento detectado. Total acumulado: ${formatBRL(total)}`, "info");
  }
  localStorage.setItem(key, String(total));
}

function updateLastUpdated() {
  const el = byId("finLastUpdated");
  if (!el) return;
  const now = new Date();
  const perf = FIN._perf.last;
  const perfLabel = perf ? ` • ${perf.totalMs.toFixed(0)}ms` : "";
  el.textContent = `Atualizado: ${now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}${perfLabel}`;
  if (!perf) {
    el.title = now.toLocaleString("pt-BR");
    return;
  }
  const sourceLabel = perf.source === "auto" ? "auto-refresh" : "manual";
  const cacheLabel = perf.secondaryCacheHit ? "cache" : "rede";
  el.title = `${now.toLocaleString("pt-BR")}\n` +
    `Total: ${perf.totalMs}ms (${sourceLabel})\n` +
    `Fetch crítico: ${perf.criticalFetchMs ?? "—"}ms\n` +
    `Render crítico: ${perf.criticalRenderMs ?? "—"}ms\n` +
    `Gráficos deferidos: ${perf.deferredChartsMs ?? "—"}ms\n` +
    `Secundário: ${perf.secondaryMs ?? "—"}ms (${cacheLabel})`;
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

  const dividendTotalsBySymbol = (FIN.dividends || []).reduce((acc, d) => {
    const key = d.symbol || "";
    if (!key) return acc;
    acc[key] = (acc[key] || 0) + (d.total_amount || 0);
    return acc;
  }, {});

  const totalValue = portfolio.reduce((sum, p) => sum + (p.current_price || 0) * p.quantity, 0);

  const sortIcon = (col) => {
    if (FIN._portfolioSort.col !== col) return '<span class="fin-sort-icon">⇅</span>';
    return `<span class="fin-sort-icon active">${FIN._portfolioSort.dir === 1 ? "↑" : "↓"}</span>`;
  };

  const totalPages = Math.max(1, Math.ceil(sorted.length / _PORTFOLIO_PER_PAGE));
  if (FIN._portfolioPage >= totalPages) FIN._portfolioPage = totalPages - 1;
  if (FIN._portfolioPage < 0) FIN._portfolioPage = 0;
  const start = FIN._portfolioPage * _PORTFOLIO_PER_PAGE;
  const currentPageRows = sorted.slice(start, start + _PORTFOLIO_PER_PAGE);

  const rows = currentPageRows
    .map((p) => {
      const currentVal = (p.current_price || 0) * p.quantity;
      const pnl = currentVal - p.total_invested;
      const pnlPct = p.total_invested ? (pnl / p.total_invested * 100) : 0;
      const pnlCls = changeClass(pnl);
      const typeCls = badgeClass(p.asset_type);
      const weightPct = totalValue > 0 ? (currentVal / totalValue * 100) : 0;

      // Dividend yield for this asset
      const totalDiv = dividendTotalsBySymbol[p.symbol] || 0;
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
    ${totalPages > 1 ? `<div class="fin-pagination">
      <button class="fin-page-btn" data-action="portfolioPagePrev" ${FIN._portfolioPage === 0 ? "disabled" : ""}>◀</button>
      <span class="fin-page-info">${FIN._portfolioPage + 1} / ${totalPages} (${sorted.length} ativos)</span>
      <button class="fin-page-btn" data-action="portfolioPageNext" ${FIN._portfolioPage >= totalPages - 1 ? "disabled" : ""}>▶</button>
    </div>` : ""}
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
      FIN._portfolioPage = 0;
      renderPortfolio(FIN.portfolio);
    });
  });
}

let _txPage = 0;
const _TX_PER_PAGE = 20;
const _PORTFOLIO_PER_PAGE = 12;

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
  if (FIN._txFilter.dateFrom) {
    filtered = filtered.filter((t) => String(t.tx_date || "").slice(0, 10) >= FIN._txFilter.dateFrom);
  }
  if (FIN._txFilter.dateTo) {
    filtered = filtered.filter((t) => String(t.tx_date || "").slice(0, 10) <= FIN._txFilter.dateTo);
  }
  if (FIN._txFilter.minTotal !== "") {
    filtered = filtered.filter((t) => Number(t.total || 0) >= Number(FIN._txFilter.minTotal));
  }
  if (FIN._txFilter.maxTotal !== "") {
    filtered = filtered.filter((t) => Number(t.total || 0) <= Number(FIN._txFilter.maxTotal));
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
      <input id="txFilterDateFrom" class="fin-inline-select" type="date" title="Data inicial" value="${escapeHtml(FIN._txFilter.dateFrom || "")}" />
      <input id="txFilterDateTo" class="fin-inline-select" type="date" title="Data final" value="${escapeHtml(FIN._txFilter.dateTo || "")}" />
      <input id="txFilterMinTotal" class="fin-inline-select" type="number" step="0.01" placeholder="Total min" value="${escapeHtml(FIN._txFilter.minTotal || "")}" />
      <input id="txFilterMaxTotal" class="fin-inline-select" type="number" step="0.01" placeholder="Total max" value="${escapeHtml(FIN._txFilter.maxTotal || "")}" />
      <button id="btnTxFilterClear" class="btn-text" type="button">Limpar</button>
      <button id="btnBatchEditTx" class="btn-text" type="button">✏️ Lote</button>
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
          <td class="text-center"><input type="checkbox" class="fin-tx-select" data-tx-id="${t.id}" ${FIN._txSelected[t.id] ? "checked" : ""} /></td>
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
            <th class="text-center" style="width:34px"><input id="txSelectAll" type="checkbox" /></th>
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
  const fromSel = byId("txFilterDateFrom");
  const toSel = byId("txFilterDateTo");
  const minSel = byId("txFilterMinTotal");
  const maxSel = byId("txFilterMaxTotal");
  const clearBtn = byId("btnTxFilterClear");
  const batchBtn = byId("btnBatchEditTx");

  const saveFilters = () => {
    localStorage.setItem("fin_tx_filter", JSON.stringify(FIN._txFilter));
  };

  const applyAndRender = () => {
    _txPage = 0;
    saveFilters();
    renderTransactions(FIN.transactions);
  };

  if (assetSel) {
    assetSel.addEventListener("change", () => {
      FIN._txFilter.asset = assetSel.value;
      applyAndRender();
    });
  }
  if (typeSel) {
    typeSel.addEventListener("change", () => {
      FIN._txFilter.type = typeSel.value;
      applyAndRender();
    });
  }
  if (fromSel) {
    fromSel.addEventListener("change", () => {
      FIN._txFilter.dateFrom = fromSel.value;
      applyAndRender();
    });
  }
  if (toSel) {
    toSel.addEventListener("change", () => {
      FIN._txFilter.dateTo = toSel.value;
      applyAndRender();
    });
  }
  if (minSel) {
    minSel.addEventListener("change", () => {
      FIN._txFilter.minTotal = minSel.value;
      applyAndRender();
    });
  }
  if (maxSel) {
    maxSel.addEventListener("change", () => {
      FIN._txFilter.maxTotal = maxSel.value;
      applyAndRender();
    });
  }
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      FIN._txFilter = { asset: "", type: "", dateFrom: "", dateTo: "", minTotal: "", maxTotal: "" };
      localStorage.setItem("fin_tx_filter", JSON.stringify(FIN._txFilter));
      _txPage = 0;
      renderTransactions(FIN.transactions);
    });
  }
  if (batchBtn) {
    batchBtn.addEventListener("click", openBatchEditTransactionsModal);
  }

  _bindTxSelection();
}

function _bindTxSelection() {
  const allSel = byId("txSelectAll");
  const checks = Array.from(document.querySelectorAll(".fin-tx-select"));
  checks.forEach((ck) => {
    ck.addEventListener("change", () => {
      const id = Number(ck.dataset.txId);
      FIN._txSelected[id] = ck.checked;
      localStorage.setItem("fin_tx_selected", JSON.stringify(FIN._txSelected));
    });
  });
  if (allSel) {
    allSel.addEventListener("change", () => {
      checks.forEach((ck) => {
        ck.checked = allSel.checked;
        FIN._txSelected[Number(ck.dataset.txId)] = allSel.checked;
      });
      localStorage.setItem("fin_tx_selected", JSON.stringify(FIN._txSelected));
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
  renderPassiveIncomeGoalSummary();
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

function getPassiveIncomeProgress() {
  const monthTotals = {};
  (FIN.dividends || []).forEach((d) => {
    const monthKey = String(d.pay_date || d.ex_date || d.created_at || "").slice(0, 7);
    if (!monthKey) return;
    monthTotals[monthKey] = (monthTotals[monthKey] || 0) + (d.total_amount || 0);
  });

  const monthEntries = Object.entries(monthTotals).sort(([a], [b]) => a.localeCompare(b));
  const last12 = monthEntries.slice(-12);
  const last12Total = last12.reduce((sum, [, val]) => sum + val, 0);
  const averageLast12 = last12.length ? (last12Total / last12.length) : 0;
  const now = new Date();
  const currentMonthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const currentMonthIncome = monthTotals[currentMonthKey] || 0;
  const targetMonthly = Number(FIN.passiveIncomeGoal?.target_monthly || 0);
  const progressPct = targetMonthly > 0 ? Math.min(100, (averageLast12 / targetMonthly) * 100) : 0;

  const nowMonthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const series = [];
  for (let i = 5; i >= 0; i -= 1) {
    const d = new Date(nowMonthStart.getFullYear(), nowMonthStart.getMonth() - i, 1);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    series.push({
      date: d,
      key,
      value: Number(monthTotals[key] || 0),
    });
  }

  // Linear trend over recent 6 months (including months with zero provents).
  let slope = 0;
  if (series.length >= 2) {
    const n = series.length;
    const xs = series.map((_, idx) => idx);
    const ys = series.map((p) => p.value);
    const sumX = xs.reduce((a, b) => a + b, 0);
    const sumY = ys.reduce((a, b) => a + b, 0);
    const sumXY = xs.reduce((acc, x, idx) => acc + x * ys[idx], 0);
    const sumXX = xs.reduce((acc, x) => acc + (x * x), 0);
    const den = (n * sumXX) - (sumX * sumX);
    slope = den !== 0 ? ((n * sumXY) - (sumX * sumY)) / den : 0;
  }

  const baseline = series.length
    ? (series.reduce((acc, p) => acc + p.value, 0) / series.length)
    : averageLast12;

  let projectedDate = null;
  let monthsToTarget = null;
  if (targetMonthly > 0 && baseline < targetMonthly && slope > 0.01) {
    monthsToTarget = Math.max(1, Math.ceil((targetMonthly - baseline) / slope));
    projectedDate = new Date(nowMonthStart.getFullYear(), nowMonthStart.getMonth() + monthsToTarget, 1);
  } else if (targetMonthly > 0 && baseline >= targetMonthly) {
    monthsToTarget = 0;
    projectedDate = nowMonthStart;
  }

  return {
    monthCount: monthEntries.length,
    averageLast12,
    currentMonthIncome,
    targetMonthly,
    progressPct,
    trendSlope: slope,
    projectedDate,
    monthsToTarget,
  };
}

function formatMonthYear(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("pt-BR", {
    month: "short",
    year: "numeric",
  });
}

function checkPassiveIncomeGoalMilestone(stats) {
  if (!stats || !Number.isFinite(stats.targetMonthly) || stats.targetMonthly <= 0) return;

  const targetKey = Number(stats.targetMonthly).toFixed(2);
  const storeKey = "fin_passive_income_goal_notified_v1";
  let stored = { target: "", reached: false };
  try {
    stored = JSON.parse(localStorage.getItem(storeKey) || "{}") || stored;
  } catch {
    stored = { target: "", reached: false };
  }

  if (stored.target !== targetKey) {
    stored = { target: targetKey, reached: false };
  }

  const reachedNow = stats.progressPct >= 100;
  if (reachedNow && !stored.reached) {
    showToast("🎉 Meta de renda passiva atingida!", "success");
    if (Notification.permission === "granted") {
      new Notification("Meta de renda passiva atingida", {
        body: `Média mensal: ${formatBRL(stats.averageLast12)} | Meta: ${formatBRL(stats.targetMonthly)}`,
        icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>💸</text></svg>",
      });
    }
    stored.reached = true;
  }

  if (!reachedNow && stored.reached) {
    stored.reached = false;
  }
  localStorage.setItem(storeKey, JSON.stringify(stored));
}

function renderPassiveIncomeGoalSummary() {
  const el = byId("finPassiveIncomeGoalSummary");
  if (!el) return;

  const stats = getPassiveIncomeProgress();
  const targetSet = stats.targetMonthly > 0;
  const note = String(FIN.passiveIncomeGoal?.note || "").trim();

  if (!targetSet) {
    el.innerHTML = `
      <div class="fin-passive-goal-card fin-passive-goal-card--empty">
        <div>
          <strong>Meta de renda passiva ainda não definida.</strong>
          <p>Defina uma meta mensal para acompanhar sua evolução em proventos.</p>
        </div>
        <button id="btnSetPassiveIncomeGoalInline" class="btn-text" type="button">Definir meta</button>
      </div>
    `;
    const inlineBtn = byId("btnSetPassiveIncomeGoalInline");
    if (inlineBtn) inlineBtn.addEventListener("click", openPassiveIncomeGoalModal);
    return;
  }

  const remaining = Math.max(0, stats.targetMonthly - stats.averageLast12);
  const complete = stats.progressPct >= 100;
  let projectionText = "Sem tendência suficiente para projetar";
  if (stats.projectedDate && stats.monthsToTarget === 0) {
    projectionText = "Meta já atingida";
  } else if (stats.projectedDate && Number.isFinite(stats.monthsToTarget)) {
    projectionText = `Estimativa: ${formatMonthYear(stats.projectedDate)} (${stats.monthsToTarget} mês(es))`;
  }
  el.innerHTML = `
    <div class="fin-passive-goal-card">
      <div class="fin-passive-goal-top">
        <span class="fin-passive-goal-title">💸 Meta de Renda Passiva (média mensal)</span>
        <button id="btnEditPassiveIncomeGoalInline" class="btn-text" type="button">Editar</button>
      </div>
      <div class="fin-passive-goal-values">
        <strong>${formatBRL(stats.averageLast12)}</strong>
        <span>/ ${formatBRL(stats.targetMonthly)}</span>
      </div>
      <div class="fin-goal-bar">
        <div class="fin-goal-fill ${complete ? "complete" : ""}" style="width:${stats.progressPct.toFixed(1)}%"></div>
      </div>
      <div class="fin-passive-goal-meta">
        <span>${stats.progressPct.toFixed(1)}% da meta</span>
        <span>Mês atual: ${formatBRL(stats.currentMonthIncome)}</span>
        <span>${complete ? "Meta atingida" : `Faltam ${formatBRL(remaining)}/mês`}</span>
      </div>
      <div class="fin-passive-goal-projection">${escapeHtml(projectionText)}</div>
      ${note ? `<p class="fin-passive-goal-note">${escapeHtml(note)}</p>` : ""}
    </div>
  `;
  const editBtn = byId("btnEditPassiveIncomeGoalInline");
  if (editBtn) editBtn.addEventListener("click", openPassiveIncomeGoalModal);
  checkPassiveIncomeGoalMilestone(stats);
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
    submitPassiveIncomeGoal,
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
      await refreshByDomains(["import"]);
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
      await refreshByDomains(["import"]);
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
      await refreshByDomains(["import"]);
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
      await refreshByDomains(["portfolio"]);
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
    await refreshByDomains(["portfolio"]);
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
      await refreshByDomains(["portfolio"]);
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
    await refreshByDomains(["portfolio"]);
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
      await refreshByDomains(["portfolio"]);
      showToast("Transação atualizada!", "success");
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao atualizar transação");
    }
  } catch {
    showToast("Erro de rede");
  }
}

function openBatchEditTransactionsModal() {
  const selectedIds = Object.entries(FIN._txSelected)
    .filter(([_, v]) => !!v)
    .map(([k]) => Number(k));
  if (!selectedIds.length) {
    showToast("Selecione ao menos uma transação.");
    return;
  }
  openFinModal("Editar Transações em Lote", `
    <form data-form-action="submitBatchEditTransactions">
      <p>${selectedIds.length} transação(ões) selecionada(s).</p>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo (opcional)</label>
          <select id="fmBatchTxType">
            <option value="">Não alterar</option>
            <option value="buy">Compra</option>
            <option value="sell">Venda</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Taxas (opcional)</label>
          <input id="fmBatchTxFees" type="number" step="0.01" min="0" placeholder="Não alterar" />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Notas</label>
          <input id="fmBatchTxNotes" placeholder="Opcional" />
        </div>
        <div class="fin-form-group">
          <label>Modo notas</label>
          <select id="fmBatchTxNotesMode">
            <option value="append">Acrescentar</option>
            <option value="replace">Substituir</option>
          </select>
        </div>
      </div>
      <button type="submit" class="fin-form-submit">💾 Aplicar em Lote</button>
    </form>
  `);
}

async function submitBatchEditTransactions(e) {
  e.preventDefault();
  const selectedIds = Object.entries(FIN._txSelected)
    .filter(([_, v]) => !!v)
    .map(([k]) => Number(k));
  if (!selectedIds.length) {
    showToast("Nenhuma transação selecionada");
    return;
  }
  const updates = {};
  const txType = byId("fmBatchTxType")?.value || "";
  const feesRaw = byId("fmBatchTxFees")?.value || "";
  const notes = byId("fmBatchTxNotes")?.value?.trim() || "";
  const notesMode = byId("fmBatchTxNotesMode")?.value || "append";
  if (txType) updates.tx_type = txType;
  if (feesRaw !== "") updates.fees = Number(feesRaw);
  if (notes) {
    updates.notes = notes;
    updates.notes_mode = notesMode;
  }
  if (!Object.keys(updates).length) {
    showToast("Informe ao menos um campo para alterar.");
    return;
  }

  try {
    const resp = await finFetch("/api/finance/transactions/batch", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tx_ids: selectedIds, updates }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || "Erro ao atualizar em lote");
      return;
    }
    FIN._txSelected = {};
    localStorage.removeItem("fin_tx_selected");
    closeFinModal();
    showToast(`${data.updated || 0} transação(ões) atualizada(s)!`, "success");
    await refreshByDomains(["portfolio"]);
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
      await refreshByDomains(["watchlist"]);
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
    await refreshByDomains(["watchlist"]);
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
      await refreshByDomains(["watchlist"]);
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

function openPassiveIncomeGoalModal() {
  const currentTarget = Number(FIN.passiveIncomeGoal?.target_monthly || 0);
  const currentNote = String(FIN.passiveIncomeGoal?.note || "");
  const stats = getPassiveIncomeProgress();
  let projectionText = "Sem tendência suficiente para projetar";
  if (stats.projectedDate && stats.monthsToTarget === 0) {
    projectionText = "Meta já atingida";
  } else if (stats.projectedDate && Number.isFinite(stats.monthsToTarget)) {
    projectionText = `Estimativa atual: ${formatMonthYear(stats.projectedDate)} (${stats.monthsToTarget} mês(es))`;
  }
  openFinModal("Meta de Renda Passiva", `
    <form data-form-action="submitPassiveIncomeGoal">
      <div class="fin-form-group">
        <label>Meta mensal de proventos (R$)</label>
        <input id="fmPassiveIncomeTarget" type="number" min="0" step="0.01" value="${Number.isFinite(currentTarget) ? currentTarget : 0}" required />
      </div>
      <div class="fin-form-group">
        <label>Observação (opcional)</label>
        <textarea id="fmPassiveIncomeNote" rows="3" maxlength="500" placeholder="Ex.: Alvo para cobrir custos fixos com dividendos.">${escapeHtml(currentNote)}</textarea>
      </div>
      <div class="fin-inline-info">Média últimos 12 meses: <strong>${formatBRL(stats.averageLast12)}</strong></div>
      <div class="fin-inline-info">${escapeHtml(projectionText)}</div>
      <button type="submit" class="fin-form-submit">💾 Salvar Meta</button>
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
      await refreshByDomains(["goals"]);
    } else {
      const data = await resp.json();
      showToast(data.error || "Erro ao criar meta");
    }
  } catch {
    showToast("Erro de rede");
  }
}

async function submitPassiveIncomeGoal(e) {
  e.preventDefault();
  const targetMonthly = Number(byId("fmPassiveIncomeTarget")?.value || 0);
  const note = String(byId("fmPassiveIncomeNote")?.value || "").trim();
  if (!Number.isFinite(targetMonthly) || targetMonthly < 0) {
    showToast("Informe um valor de meta mensal válido");
    return;
  }
  try {
    const resp = await finFetch("/api/finance/goals/passive-income", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_monthly: targetMonthly, note }),
    });
    if (!resp.ok) {
      const data = await resp.json();
      showToast(data.error || "Erro ao salvar meta de renda passiva");
      return;
    }
    closeFinModal();
    await refreshGoalsPanel();
    showToast("Meta de renda passiva atualizada", "success");
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
      await refreshByDomains(["goals"]);
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
    await refreshByDomains(["goals"]);
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
    _destroyDividendCharts();
    return;
  }

  // Summary totals by type
  const totals = {};
  const assetTotals = {};
  const monthTotals = {};
  let grandTotal = 0;
  divs.forEach((d) => {
    const t = d.div_type || "dividend";
    const symbol = d.symbol || "—";
    const monthKey = (d.pay_date || d.ex_date || d.created_at || "").slice(0, 7);
    totals[t] = (totals[t] || 0) + (d.total_amount || 0);
    assetTotals[symbol] = (assetTotals[symbol] || 0) + (d.total_amount || 0);
    if (monthKey) monthTotals[monthKey] = (monthTotals[monthKey] || 0) + (d.total_amount || 0);
    grandTotal += d.total_amount || 0;
  });

  const monthEntries = Object.entries(monthTotals).sort(([a], [b]) => a.localeCompare(b));
  const last12 = monthEntries.slice(-12);
  const last12Total = last12.reduce((sum, [, value]) => sum + value, 0);
  const averageMonth = monthEntries.length ? grandTotal / monthEntries.length : 0;
  const bestMonth = last12.length ? [...last12].sort((a, b) => b[1] - a[1])[0] : null;
  const bestAsset = Object.entries(assetTotals).sort((a, b) => b[1] - a[1])[0] || null;
  const totalCount = divs.length;

  const typeLabels = { dividend: "Dividendos", jcp: "JCP", rendimento: "Rendimentos", bonus: "Bonificação" };
  if (summaryEl) {
    summaryEl.innerHTML = `
      <div class="fin-div-totals">
        <div class="fin-div-total-item fin-div-grand"><span>Total Geral</span><strong>${formatBRL(grandTotal)}</strong><em>${totalCount} lançamento(s)</em></div>
        <div class="fin-div-total-item"><span>Média Mensal</span><strong>${formatBRL(averageMonth)}</strong><em>${monthEntries.length || 0} mês(es)</em></div>
        <div class="fin-div-total-item"><span>Últimos 12 Meses</span><strong>${formatBRL(last12Total)}</strong><em>${last12.length || 0} competência(s)</em></div>
        <div class="fin-div-total-item"><span>Melhor Mês</span><strong>${bestMonth ? formatBRL(bestMonth[1]) : "—"}</strong><em>${bestMonth ? escapeHtml(bestMonth[0]) : "sem dados"}</em></div>
        <div class="fin-div-total-item"><span>Maior Pagador</span><strong>${bestAsset ? formatBRL(bestAsset[1]) : "—"}</strong><em>${bestAsset ? escapeHtml(bestAsset[0]) : "sem dados"}</em></div>
        ${Object.entries(totals).map(([k, v]) =>
          `<div class="fin-div-total-item"><span>${typeLabels[k] || k}</span><strong>${formatBRL(v)}</strong></div>`
        ).join("")}
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
    <div class="fin-div-table-toolbar">
      <div class="fin-div-table-caption">Lista recente de proventos, com foco em consulta rápida dos últimos registros.</div>
      <button type="button" id="btnBrowseDividendsInline" class="btn-text">Ver todos e filtrar</button>
    </div>
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

  const browseBtn = byId("btnBrowseDividendsInline");
  if (browseBtn) browseBtn.addEventListener("click", () => openCadastroBrowserModal("dividends"));

  renderDividendsChart(divs);
  renderDividendsTypeChart(totals, typeLabels);
  renderDividendsAssetChart(assetTotals);
}

function _destroyDividendCharts() {
  ["dividends", "dividendsType", "dividendsAsset"].forEach((key) => {
    if (FIN.charts[key]) {
      FIN.charts[key].destroy();
      delete FIN.charts[key];
    }
  });
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

  if (FIN.charts.dividends) FIN.charts.dividends.destroy();

  FIN.charts.dividends = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Dividendos por mês (R$)",
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
        title: {
          display: true,
          text: "Fluxo mensal de dividendos",
          color: getComputedStyle(document.body).getPropertyValue("--text") || "#e2e8f0",
          padding: { bottom: 14 },
          font: { size: 15, weight: "700" },
        },
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

function renderDividendsTypeChart(totals, typeLabels) {
  const canvas = byId("dividendsTypeChart");
  if (!canvas || !window.Chart) return;
  const labels = Object.keys(totals);
  const values = labels.map((key) => totals[key]);
  if (FIN.charts.dividendsType) FIN.charts.dividendsType.destroy();
  if (!labels.length) return;

  FIN.charts.dividendsType = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: labels.map((key) => typeLabels[key] || key),
      datasets: [{
        data: values,
        backgroundColor: ["#10b981", "#0ea5e9", "#f59e0b", "#8b5cf6", "#ef4444"],
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: getComputedStyle(document.body).getPropertyValue("--text") || "#e2e8f0" },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.label}: ${formatBRL(ctx.raw)}`,
          },
        },
      },
    },
  });
}

function renderDividendsAssetChart(assetTotals) {
  const canvas = byId("dividendsAssetChart");
  if (!canvas || !window.Chart) return;
  const topAssets = Object.entries(assetTotals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  if (FIN.charts.dividendsAsset) FIN.charts.dividendsAsset.destroy();
  if (!topAssets.length) return;

  FIN.charts.dividendsAsset = new Chart(canvas, {
    type: "bar",
    data: {
      labels: topAssets.map(([symbol]) => symbol),
      datasets: [{
        label: "Total recebido",
        data: topAssets.map(([, value]) => value),
        backgroundColor: "rgba(59, 130, 246, 0.78)",
        borderRadius: 8,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
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
          ticks: {
            callback: (v) => `R$ ${Number(v).toLocaleString("pt-BR")}`,
          },
        },
      },
    },
  });
}

function getCadastroCollections() {
  return {
    assets: FIN.assets.map((a) => ({
      title: `${a.symbol} — ${a.name || a.symbol}`,
      subtitle: a.asset_type || "ativo",
      meta: [
        `ID ${a.id}`,
        a.asset_type || "sem tipo",
      ],
      search: `${a.symbol} ${a.name || ""} ${a.asset_type || ""}`.toLowerCase(),
    })),
    watchlist: FIN.watchlist.map((w) => ({
      title: `${w.symbol} — ${w.name || w.symbol}`,
      subtitle: "watchlist",
      meta: [
        w.asset_type || "sem tipo",
        w.target_price ? `Alvo ${formatBRL(w.target_price)}` : "sem alvo",
        w.alert_above ? "alerta acima" : "alerta abaixo",
      ],
      search: `${w.symbol} ${w.name || ""} ${w.asset_type || ""} ${w.notes || ""}`.toLowerCase(),
    })),
    goals: FIN.goals.map((g) => ({
      title: g.name,
      subtitle: "meta",
      meta: [
        `Atual ${formatBRL(g.current_amount)}`,
        `Meta ${formatBRL(g.target_amount)}`,
        g.category || "sem categoria",
      ],
      search: `${g.name} ${g.category || ""} ${g.notes || ""}`.toLowerCase(),
    })),
    dividends: FIN.dividends.map((d) => ({
      title: `${d.symbol || "—"} — ${formatBRL(d.total_amount)}`,
      subtitle: d.div_type || "provento",
      meta: [
        (d.pay_date || d.ex_date || d.created_at || "").slice(0, 10),
        `Qtd ${formatNumber(d.quantity, 0)}`,
        `$/ação ${formatBRL(d.amount_per_share)}`,
      ],
      search: `${d.symbol || ""} ${d.div_type || ""} ${d.notes || ""}`.toLowerCase(),
    })),
  };
}

function renderCadastroBrowserResults() {
  const typeEl = byId("fmCadastroType");
  const searchEl = byId("fmCadastroSearch");
  const resultsEl = byId("finCadastroResults");
  const countEl = byId("finCadastroCount");
  if (!typeEl || !searchEl || !resultsEl || !countEl) return;

  const collections = getCadastroCollections();
  const type = typeEl.value;
  const term = searchEl.value.trim().toLowerCase();
  const items = (collections[type] || []).filter((item) => !term || item.search.includes(term));
  countEl.textContent = `${items.length} registro(s)`;

  if (!items.length) {
    resultsEl.innerHTML = '<div class="fin-cadastro-empty">Nenhum cadastro encontrado com esse filtro.</div>';
    return;
  }

  resultsEl.innerHTML = items.map((item) => `
    <div class="fin-cadastro-card">
      <div class="fin-cadastro-title">
        <strong>${escapeHtml(item.title)}</strong>
        <span class="fin-badge fin-badge-stock">${escapeHtml(item.subtitle)}</span>
      </div>
      <div class="fin-cadastro-meta">
        ${item.meta.map((meta) => `<span>${escapeHtml(meta)}</span>`).join("")}
      </div>
    </div>
  `).join("");
}

function openCadastroBrowserModal(initialType = "assets") {
  openFinModal("Consultar Cadastros", `
    <div class="fin-cadastro-toolbar">
      <select id="fmCadastroType" class="fin-inline-select">
        <option value="assets" ${initialType === "assets" ? "selected" : ""}>Ativos</option>
        <option value="watchlist" ${initialType === "watchlist" ? "selected" : ""}>Watchlist</option>
        <option value="goals" ${initialType === "goals" ? "selected" : ""}>Metas</option>
        <option value="dividends" ${initialType === "dividends" ? "selected" : ""}>Dividendos</option>
      </select>
      <input id="fmCadastroSearch" class="fin-cadastro-search" placeholder="Filtrar por nome, símbolo, nota, categoria..." />
      <span id="finCadastroCount" class="fin-div-table-caption">0 registro(s)</span>
    </div>
    <div id="finCadastroResults" class="fin-cadastro-results"></div>
  `);

  const typeEl = byId("fmCadastroType");
  const searchEl = byId("fmCadastroSearch");
  typeEl?.addEventListener("change", renderCadastroBrowserResults);
  searchEl?.addEventListener("input", renderCadastroBrowserResults);
  renderCadastroBrowserResults();
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
      await refreshByDomains(["dividends"]);
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
    await refreshByDomains(["dividends"]);
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

    const results = await Promise.all(reqs);
    let resultIdx = 0;
    const primaryData = results[resultIdx++] || [];
    const totalData = (!isTotal && compareTotal) ? (results[resultIdx++] || []) : [];
    const investedData = showInvested ? (results[resultIdx++] || []) : [];
    const benchmarkData = benchmark ? (results[resultIdx++] || []) : [];

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

async function renderDividendCeiling() {
  const el = byId("finDividendCeilingContent");
  if (!el) return;

  const targetDyInput = byId("dyTargetInput");
  const monthsInput = byId("dyMonthsInput");
  const targetDy = Math.min(30, Math.max(0.1, Number((targetDyInput && targetDyInput.value) || 8)));
  const months = Math.min(60, Math.max(3, Number((monthsInput && monthsInput.value) || 12)));

  try {
    const resp = await finFetch(
      `/api/finance/dividend-ceiling?target_dy=${encodeURIComponent(targetDy)}&months=${months}`,
    );
    const data = await resp.json();
    const rows = data.rows || [];
    if (!rows.length) {
      el.innerHTML = `<p class="fin-empty">${escapeHtml(data.message || "Sem dados suficientes para simular.")}</p>`;
      return;
    }

    const body = rows.map((r) => {
      const signal = String(r.signal || "neutro").toLowerCase();
      const signalClass = signal === "atrativo"
        ? "fin-badge-buy"
        : signal === "caro"
          ? "fin-badge-sell"
          : "fin-badge-stock";
      const upsideCls = Number(r.upside_pct || 0) >= 0 ? "fin-up" : "fin-down";
      return `
        <tr>
          <td><strong>${escapeHtml(r.symbol)}</strong></td>
          <td class="text-right mono">${formatBRL(r.current_price)}</td>
          <td class="text-right mono">${formatNumber(r.dps_ttm, 4)}</td>
          <td class="text-right mono">${formatBRL(r.ceiling_price)}</td>
          <td class="text-right mono">${formatPct(r.implied_dy)}</td>
          <td class="text-right mono ${upsideCls}">${r.upside_pct == null ? "—" : formatPct(r.upside_pct)}</td>
          <td><span class="fin-badge ${signalClass}">${escapeHtml(signal)}</span></td>
        </tr>
      `;
    }).join("");

    el.innerHTML = `
      <div class="fin-mini-summary">
        <span>DY alvo: <strong>${formatPct(data.target_dy)}</strong></span>
        <span>Janela: <strong>${Number(data.months)} meses</strong></span>
      </div>
      <div class="fin-table-wrap">
        <table class="fin-table" style="margin-top:0;">
          <thead>
            <tr>
              <th>Ativo</th>
              <th class="text-right">Preço atual</th>
              <th class="text-right">DPA TTM</th>
              <th class="text-right">Preço teto</th>
              <th class="text-right">DY implícito</th>
              <th class="text-right">Margem vs teto</th>
              <th>Sinal</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    `;
  } catch (err) {
    console.error("Dividend ceiling error:", err);
    el.innerHTML = '<p class="fin-empty">Erro ao calcular preço teto por DY.</p>';
  }
}

async function renderIndependenceScenario() {
  const el = byId("finIndependenceContent");
  if (!el) return;

  const targetInput = byId("indTargetIncomeInput");
  const yearsInput = byId("indYearsInput");
  const aporteInput = byId("indAporteInput");
  const safeInput = byId("indSafeRateInput");

  const targetIncome = Math.max(0, Number((targetInput && targetInput.value) || 5000));
  const years = Math.min(60, Math.max(1, Number((yearsInput && yearsInput.value) || 20)));
  const aporteMensal = Math.max(0, Number((aporteInput && aporteInput.value) || 0));
  const safeRate = Math.min(12, Math.max(1, Number((safeInput && safeInput.value) || 4)));

  try {
    const resp = await finFetch(
      "/api/finance/independence-scenario"
      + `?target_monthly_income=${encodeURIComponent(targetIncome)}`
      + `&years=${years}`
      + `&aporte_mensal=${encodeURIComponent(aporteMensal)}`
      + `&safe_rate_pct=${encodeURIComponent(safeRate)}`,
    );
    const data = await resp.json();
    const scenarios = data.scenarios || {};
    const rows = [
      ["conservador", "Conservador"],
      ["base", "Base"],
      ["otimista", "Otimista"],
    ].map(([key, label]) => {
      const item = scenarios[key] || {};
      const reached = Boolean(item.reached);
      const status = reached
        ? `Atinge em ${item.reached_month || 0} mês(es)`
        : `Gap ${formatBRL(item.gap || 0)}`;
      return `
        <tr>
          <td>${label}</td>
          <td>${formatNumber(Number(item.annual_rate || 0) * 100, 1)}% a.a.</td>
          <td>${formatBRL(item.final_value || 0)}</td>
          <td><span class="fin-badge ${reached ? "fin-badge-buy" : "fin-badge-sell"}">${reached ? "atinge" : "não atinge"}</span></td>
          <td>${status}</td>
        </tr>
      `;
    }).join("");

    const chance = Number(data.chance_percent || 0);
    const chanceClass = chance >= 70 ? "fin-up" : chance >= 40 ? "" : "fin-down";
    el.innerHTML = `
      <div class="fin-mini-summary">
        <span>Patrimônio atual: <strong>${formatBRL(data.current_value || 0)}</strong></span>
        <span>Patrimônio alvo: <strong>${formatBRL(data.target_patrimony || 0)}</strong></span>
        <span class="${chanceClass}">Chance estimada: <strong>${formatNumber(chance, 1)}%</strong></span>
      </div>
      <table class="fin-table" style="margin-top:0;">
        <thead>
          <tr>
            <th>Cenário</th>
            <th>Retorno</th>
            <th>Patrimônio final</th>
            <th>Status</th>
            <th>Detalhe</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  } catch (err) {
    console.error("Independence scenario error:", err);
    el.innerHTML = '<p class="fin-empty">Erro ao calcular independência financeira.</p>';
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
      renderDividendCeiling();
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
          // Refresh only impacted sections from AI actions.
          const domains = inferDomainsFromAiActions(data.actions);
          await refreshByDomains(domains);
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
  FIN.flags = resolveFinanceFlags();
  try {
    FIN._txFilter = {
      ...FIN._txFilter,
      ...(JSON.parse(localStorage.getItem("fin_tx_filter") || "{}") || {}),
    };
  } catch {
    // ignore malformed storage
  }
  try {
    FIN._txSelected = JSON.parse(localStorage.getItem("fin_tx_selected") || "{}") || {};
  } catch {
    FIN._txSelected = {};
  }

  initTheme();
  initA11yEnhancements();
  initFinanceKeyboardShortcuts();
  initSectionQuickNav();
  if (isFinFlagOn("lazyRebalanceLoad")) {
    initRebalanceLazyLoad();
  } else {
    FIN._rebalanceLoaded = true;
  }
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
  bind("btnPassiveIncomeGoal", openPassiveIncomeGoalModal);
  bind("btnAddDividend", openAddDividendModal);
  bind("btnBrowseDividends", () => openCadastroBrowserModal("dividends"));
  bind("btnEditAllocation", openAllocationModal);
  bind("btnExportData", openExportModal);
  bind("btnFinanceSettings", openFinanceSettingsModal);
  bind("btnFeatureFlags", openFeatureFlagsModal);
  bind("btnNotifications", setupNotifications);
  bind("finAIChatSend", sendFinAIChat);
  bind("finModalClose", closeFinModal);
  bind("btnRunRebalanceSim", renderRebalance);
  bind("btnRunProjection", renderProjection);
  bind("btnRunDividendCeiling", renderDividendCeiling);
  bind("btnRunIndependence", renderIndependenceScenario);

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
  const dyTargetInput = byId("dyTargetInput");
  const dyMonthsInput = byId("dyMonthsInput");
  const indTargetIncomeInput = byId("indTargetIncomeInput");
  const indYearsInput = byId("indYearsInput");
  const indAporteInput = byId("indAporteInput");
  const indSafeRateInput = byId("indSafeRateInput");
  if (rebalAporteInput) rebalAporteInput.addEventListener("change", renderRebalance);
  if (projectionMonthsInput) projectionMonthsInput.addEventListener("change", renderProjection);
  if (projectionAporteMensalInput) projectionAporteMensalInput.addEventListener("change", renderProjection);
  if (dyTargetInput) dyTargetInput.addEventListener("change", renderDividendCeiling);
  if (dyMonthsInput) dyMonthsInput.addEventListener("change", renderDividendCeiling);
  if (indTargetIncomeInput) indTargetIncomeInput.addEventListener("change", renderIndependenceScenario);
  if (indYearsInput) indYearsInput.addEventListener("change", renderIndependenceScenario);
  if (indAporteInput) indAporteInput.addEventListener("change", renderIndependenceScenario);
  if (indSafeRateInput) indSafeRateInput.addEventListener("change", renderIndependenceScenario);

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
    if (action === "portfolioPagePrev") { FIN._portfolioPage = Math.max(0, FIN._portfolioPage - 1); renderPortfolio(FIN.portfolio); return; }
    if (action === "portfolioPageNext") { FIN._portfolioPage++; renderPortfolio(FIN.portfolio); return; }

    const fn = actionMap[action];
    if (fn) fn(Number(btn.dataset.id));
  });

  // ── Form delegation (data-form-action) ──────────────
  const formMap = {
    submitEditTransaction,
    submitEditWatchlist,
    submitBatchEditTransactions,
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
    FIN._autoRefreshInterval = setInterval(
      () => loadAll({ useSecondaryCache: isFinFlagOn("secondaryPanelCache") }),
      seconds * 1000,
    );
  }
}

function initRebalanceLazyLoad() {
  const card = byId("finRebalanceCard");
  if (!card || typeof IntersectionObserver !== "function") return;

  const io = new IntersectionObserver((entries) => {
    const visible = entries.some((entry) => entry.isIntersecting);
    if (!visible || FIN._rebalanceLoaded) return;
    FIN._rebalanceLoaded = true;
    renderRebalance();
    renderProjection();
    renderDividendCeiling();
    renderIndependenceScenario();
    io.disconnect();
  }, { rootMargin: "150px 0px" });

  io.observe(card);
}

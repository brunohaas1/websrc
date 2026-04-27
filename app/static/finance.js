/* ══════════════════════════════════════════════════════════
   Finance Dashboard JavaScript
   ══════════════════════════════════════════════════════════ */

/* eslint-disable no-unused-vars */

const FIN = {
  summary: null,
  portfolio: [],
  transactions: [],
  cashflowEntries: [],
  cashflowSummary: null,
  cashflowAnalytics: null,
  cashflowBudget: {},
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
  opsHealth: null,
  auditEntries: [],
  _rebalanceLoaded: false,
  _secondaryCache: { ts: 0, payload: null },
  _widgetCache: {},
  _marketStaleNotified: false,
  _perf: { seq: 0, lastRunId: 0, runs: {}, last: null, history: [] },
  flags: {},
  layoutEditMode: false,
  layoutObserver: null,
  layoutSaveTimer: null,
  defaultCardOrder: [],
};

function _healthStatusClass(status) {
  const s = String(status || "").toLowerCase();
  if (s === "ok") return "fin-health-chip fin-health-chip--ok";
  if (s === "degraded") return "fin-health-chip fin-health-chip--warn";
  return "fin-health-chip fin-health-chip--neutral";
}

const SECONDARY_CACHE_TTL_MS = 25000;
const MARKET_SNAPSHOT_KEY = "fin_market_snapshot_v1";
const MARKET_SNAPSHOT_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const FIN_ACTIVE_TAB_KEY = "fin_active_tab_v1";

const FIN_THEME_KEY = "fin-theme";
const FIN_LAYOUT_KEY = "fin_layout_v1";
const FIN_THEME_ORDER = ["dark", "light", "ocean", "sunset"];
const FIN_DENSITY_KEY = "fin-density";
const FIN_ONBOARDING_SEEN_KEY = "fin_onboarding_seen_v1";

const byId = (id) => document.getElementById(id);
let _deferredInstallPrompt = null;

function assetTypeLabelPt(type) {
  const key = String(type || "").trim().toLowerCase();
  const map = {
    stock: "Ação",
    fii: "FII",
    etf: "ETF",
    crypto: "Cripto",
    fund: "Fundo",
    "renda-fixa": "Renda Fixa",
  };
  return map[key] || (type || "Ativo");
}

function detectAssetDisplayType(asset) {
  const rawType = String(asset?.asset_type || "").trim().toLowerCase();
  const symbol = String(asset?.symbol || "").trim().toUpperCase();
  const rawName = String(asset?.name || "").trim();
  const nameNorm = rawName
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();

  if (["crypto", "fund", "fii", "etf", "renda-fixa", "renda_fixa"].includes(rawType)) {
    return rawType === "renda_fixa" ? "renda-fixa" : rawType;
  }

  const looksLikeEtf = symbol.endsWith("11") && (
    nameNorm.includes("etf")
    || nameNorm.includes("indice")
    || nameNorm.includes("index")
  );
  if (looksLikeEtf) return "etf";

  const mentionsFii = nameNorm.includes("fii");
  const mentionsImobFund = nameNorm.includes("fundo") && nameNorm.includes("imobili");
  const looksLikeFii = symbol.endsWith("11") && (mentionsFii || mentionsImobFund || nameNorm.includes("fundo"));
  if (mentionsFii || mentionsImobFund || looksLikeFii) return "fii";

  if (["acao", "acoes", "stock"].includes(rawType) || /^[A-Z]{4}\d$/.test(symbol)) {
    return "stock";
  }

  return rawType || "stock";
}

// ── Toast notifications (replaces alert()) ────────────────
function showToast(message, type = "error", options = {}) {
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

  const text = document.createElement("span");
  text.className = "fin-toast-message";
  text.textContent = message;
  toast.appendChild(text);

  if (options.actionLabel && typeof options.onAction === "function") {
    const actionBtn = document.createElement("button");
    actionBtn.className = "fin-toast-action";
    actionBtn.textContent = options.actionLabel;
    actionBtn.addEventListener("click", () => {
      try { options.onAction(); } catch { /* noop */ }
      toast.remove();
    });
    toast.appendChild(actionBtn);
  }

  const closeBtn = document.createElement("button");
  closeBtn.className = "fin-toast-close";
  closeBtn.setAttribute("aria-label", "Fechar notificação");
  closeBtn.textContent = "x";
  closeBtn.addEventListener("click", () => toast.remove());
  toast.appendChild(closeBtn);

  container.appendChild(toast);
  const timeout = Number(options.timeout || (type === "success" ? 2800 : 4200));
  setTimeout(() => toast.remove(), Math.max(1200, timeout));
}

function initQuickNav() {
  if (!isFinFlagOn("sectionQuickNav") && !isFinFlagOn("quickNav")) return;
  const sectionMap = {
    "1": "finSummaryCard",
    "2": "finPortfolioCard",
    "3": "finTxCard",
    "4": "finDividendsCard",
    "5": "finHistoryCard",
    "6": "finAlertsCard",
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

function _getLayoutState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(FIN_LAYOUT_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function _saveLayoutState(next) {
  localStorage.setItem(FIN_LAYOUT_KEY, JSON.stringify(next || {}));
}

function _captureLayoutState() {
  const grid = byId("financeMain");
  if (!grid) return {};
  const cards = [...grid.querySelectorAll(".fin-card[id]")];
  const hidden = [];
  const heights = {};
  cards.forEach((card) => {
    const cardId = card.id;
    const isHidden = card.style.display === "none";
    if (isHidden) hidden.push(cardId);
    if (card.style.height && card.style.height.endsWith("px")) {
      heights[cardId] = card.style.height;
    }
  });
  return {
    order: cards.map((card) => card.id),
    hidden,
    heights,
  };
}

function persistFinanceLayout() {
  _saveLayoutState(_captureLayoutState());
}

function _scheduleLayoutPersist() {
  clearTimeout(FIN.layoutSaveTimer);
  FIN.layoutSaveTimer = setTimeout(persistFinanceLayout, 180);
}

function applyFinanceLayout() {
  const grid = byId("financeMain");
  if (!grid) return;
  const state = _getLayoutState();
  const cards = [...grid.querySelectorAll(".fin-card[id]")];
  if (!cards.length) return;

  const byCardId = new Map(cards.map((card) => [card.id, card]));
  const used = new Set();
  const ordered = [];
  (state.order || []).forEach((id) => {
    const card = byCardId.get(id);
    if (!card || used.has(id)) return;
    used.add(id);
    ordered.push(card);
  });
  cards.forEach((card) => {
    if (!used.has(card.id)) ordered.push(card);
  });
  ordered.forEach((card) => grid.appendChild(card));

  const hidden = new Set(state.hidden || []);
  const heights = state.heights || {};
  cards.forEach((card) => {
    card.style.display = hidden.has(card.id) ? "none" : "";
    if (heights[card.id]) card.style.height = heights[card.id];
  });
}

function setLayoutEditMode(enabled) {
  const grid = byId("financeMain");
  if (!grid) return;
  FIN.layoutEditMode = Boolean(enabled);
  grid.classList.toggle("fin-layout-edit", FIN.layoutEditMode);

  const btn = byId("btnLayoutMode");
  if (btn) {
    if (FIN.layoutEditMode) {
      btn.classList.add("is-active");
      btn.innerHTML = '<span class="btn-glyph" aria-hidden="true">✓</span><span>Editando</span>';
    } else {
      btn.classList.remove("is-active");
      btn.innerHTML = '<span class="btn-glyph" aria-hidden="true">⤢</span><span>Layout</span>';
    }
  }

  grid.querySelectorAll(".fin-card[id]").forEach((card) => {
    card.draggable = FIN.layoutEditMode;
  });

  showToast(
    FIN.layoutEditMode
      ? "Modo layout ativado. Arraste os cards para reordenar."
      : "Modo layout desativado.",
    "info",
  );
}

function toggleLayoutEditMode() {
  setLayoutEditMode(!FIN.layoutEditMode);
}

function initFinanceLayoutTools() {
  const grid = byId("financeMain");
  if (!grid) return;

  if (!FIN.defaultCardOrder.length) {
    FIN.defaultCardOrder = [...grid.querySelectorAll(".fin-card[id]")].map((card) => card.id);
  }

  applyFinanceLayout();

  if (typeof ResizeObserver === "function") {
    FIN.layoutObserver = new ResizeObserver(() => _scheduleLayoutPersist());
    grid.querySelectorAll(".fin-card[id]").forEach((card) => FIN.layoutObserver.observe(card));
  }

  let draggedId = "";
  grid.querySelectorAll(".fin-card[id]").forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      if (!FIN.layoutEditMode) {
        e.preventDefault();
        return;
      }
      draggedId = card.id;
      card.classList.add("fin-dragging");
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.id);
      }
    });

    card.addEventListener("dragend", () => {
      card.classList.remove("fin-dragging");
      grid.querySelectorAll(".fin-drop-target").forEach((el) => el.classList.remove("fin-drop-target"));
      _scheduleLayoutPersist();
    });

    card.addEventListener("dragover", (e) => {
      if (!FIN.layoutEditMode) return;
      e.preventDefault();
      if (draggedId && draggedId !== card.id) card.classList.add("fin-drop-target");
    });

    card.addEventListener("dragleave", () => {
      card.classList.remove("fin-drop-target");
    });

    card.addEventListener("drop", (e) => {
      if (!FIN.layoutEditMode) return;
      e.preventDefault();
      card.classList.remove("fin-drop-target");
      const sourceId = draggedId || e.dataTransfer?.getData("text/plain") || "";
      if (!sourceId || sourceId === card.id) return;
      const source = byId(sourceId);
      const target = card;
      if (!source || !target || source === target) return;

      const targetRect = target.getBoundingClientRect();
      const placeAfter = e.clientY > (targetRect.top + targetRect.height / 2);
      if (placeAfter) {
        target.insertAdjacentElement("afterend", source);
      } else {
        target.insertAdjacentElement("beforebegin", source);
      }
      _scheduleLayoutPersist();
    });
  });
}

function openLayoutManagerModal() {
  const grid = byId("financeMain");
  if (!grid) return;
  const cards = [...grid.querySelectorAll(".fin-card[id]")];
  const rows = cards.map((card) => {
    const title = card.querySelector("h2")?.textContent?.trim() || card.id;
    const checked = card.style.display === "none" ? "" : "checked";
    return `
      <label class="fin-shortcut-row" style="justify-content:space-between;gap:12px;align-items:center;">
        <span>${escapeHtml(title)}</span>
        <input type="checkbox" class="fin-layout-card-check" data-card-id="${card.id}" ${checked} />
      </label>
    `;
  }).join("");

  openFinModal("Gerenciar Cards", `
    <form id="finLayoutManagerForm">
      <p class="fin-empty" style="text-align:left;margin-bottom:10px;">Ative/desative os cards visíveis e mantenha o layout salvo neste navegador.</p>
      <div class="fin-shortcuts-list">${rows}</div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
        <button type="button" id="finLayoutShowAll" class="btn-text">Mostrar todos</button>
        <button type="submit" class="fin-form-submit">Salvar visibilidade</button>
      </div>
    </form>
  `);

  const form = byId("finLayoutManagerForm");
  const showAll = byId("finLayoutShowAll");
  if (showAll) {
    showAll.addEventListener("click", () => {
      form?.querySelectorAll(".fin-layout-card-check").forEach((el) => { el.checked = true; });
    });
  }
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      form.querySelectorAll(".fin-layout-card-check").forEach((el) => {
        const cardId = el.dataset.cardId;
        const card = byId(cardId);
        if (!card) return;
        card.style.display = el.checked ? "" : "none";
      });
      persistFinanceLayout();
      closeFinModal();
      showToast("Visibilidade dos cards atualizada.", "success");
    });
  }
}

function resetFinanceLayout() {
  localStorage.removeItem(FIN_LAYOUT_KEY);
  const grid = byId("financeMain");
  if (!grid) return;
  const cards = [...grid.querySelectorAll(".fin-card[id]")];
  cards.forEach((card) => {
    card.style.display = "";
    card.style.height = "";
  });
  const byCardId = new Map(cards.map((card) => [card.id, card]));
  FIN.defaultCardOrder.forEach((id) => {
    const card = byCardId.get(id);
    if (card) grid.appendChild(card);
  });
  setLayoutEditMode(false);
  showToast("Layout resetado para o padrão.", "success");
}

function applyLayoutPreset(presetId) {
  const presets = {
    conservador: {
      hide: ["finAICard"],
      promote: ["finHistoryCard", "finPortfolioCard", "finGoalsCard", "finDividendsCard"],
    },
    dividendos: {
      hide: ["finPnLCard", "finRebalanceCard"],
      promote: ["finDividendsCard", "finDividendCeilingCard", "finGoalsCard", "finPortfolioCard"],
    },
    growth: {
      hide: ["finDividendCeilingCard"],
      promote: ["finPerformanceCard", "finHistoryCard", "finPnLCard", "finPortfolioCard"],
    },
  };
  const preset = presets[presetId];
  const grid = byId("financeMain");
  if (!preset || !grid) return;

  const cards = [...grid.querySelectorAll(".fin-card[id]")];
  const byCardId = new Map(cards.map((card) => [card.id, card]));
  cards.forEach((card) => {
    card.style.display = preset.hide.includes(card.id) ? "none" : "";
  });
  preset.promote.forEach((id) => {
    const card = byCardId.get(id);
    if (card) grid.appendChild(card);
  });
  persistFinanceLayout();
  showToast(`Preset aplicado: ${presetId}`, "success");
}

function openLayoutPresetModal() {
  openFinModal("Presets de Layout", `
    <div class="fin-shortcuts-list">
      <button class="fin-form-submit" type="button" data-layout-preset="conservador">Conservador</button>
      <button class="fin-form-submit" type="button" data-layout-preset="dividendos">Dividendos</button>
      <button class="fin-form-submit" type="button" data-layout-preset="growth">Growth</button>
    </div>
  `);
  byId("finModalBody")?.querySelectorAll("[data-layout-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      applyLayoutPreset(btn.dataset.layoutPreset || "");
      closeFinModal();
    });
  });
}

function openQuickTourModal() {
  openFinModal("Guia Rápido (1 minuto)", `
    <div class="fin-shortcuts-list">
      <div class="fin-shortcut-row"><kbd>1</kbd><span>Use <strong>Layout</strong> para arrastar e organizar cards</span></div>
      <div class="fin-shortcut-row"><kbd>2</kbd><span>Use <strong>Cards</strong> para esconder os que não usa</span></div>
      <div class="fin-shortcut-row"><kbd>3</kbd><span>Use <strong>Preset</strong> para aplicar estratégia rápida</span></div>
      <div class="fin-shortcut-row"><kbd>4</kbd><span>Use <strong>Tema</strong> e <strong>Densidade</strong> para personalizar visual</span></div>
      <div class="fin-shortcut-row"><kbd>5</kbd><span><strong>Registros</strong> abre a visão detalhada dos lançamentos</span></div>
    </div>
    <div style="display:flex;justify-content:flex-end;margin-top:12px;">
      <button type="button" id="btnTourStart" class="fin-form-submit">Começar agora</button>
    </div>
  `);
  byId("btnTourStart")?.addEventListener("click", () => {
    closeFinModal();
    byId("finPortfolioCard")?.scrollIntoView({ behavior: "smooth", block: "start" });
    showToast("Tour concluído. Aproveite seu dashboard!", "success");
  });
}

function maybeAutoOpenQuickTour() {
  const seen = localStorage.getItem(FIN_ONBOARDING_SEEN_KEY) === "1";
  if (seen) return;
  localStorage.setItem(FIN_ONBOARDING_SEEN_KEY, "1");
  setTimeout(() => openQuickTourModal(), 500);
}

function renderEmptyState(message, ctaLabel, ctaAction) {
  const buttonHtml = ctaLabel && ctaAction
    ? `<button class="btn-text fin-empty-cta" type="button" data-empty-action="${escapeHtml(ctaAction)}">${escapeHtml(ctaLabel)}</button>`
    : "";
  return `
    <div class="fin-empty-block">
      <p class="fin-empty">${escapeHtml(message)}</p>
      ${buttonHtml}
    </div>
  `;
}

function runEmptyStateAction(action) {
  const map = {
    addAsset: openAddAssetModal,
    addTransaction: openAddTransactionModal,
    addCashflow: openAddCashflowModal,
    addDividend: openAddDividendModal,
    addWatchlist: openAddWatchlistModal,
    addGoal: openAddGoalModal,
    clearTxFilters: () => {
      FIN._txFilter = { asset: "", type: "", dateFrom: "", dateTo: "", minTotal: "", maxTotal: "" };
      localStorage.removeItem("fin_tx_filter");
      renderTransactions(FIN.transactions);
    },
  };
  const fn = map[action];
  if (fn) fn();
}

function setFinanceTab(tabId) {
  const normalized = tabId === "cashflow" ? "cashflow" : "investments";
  const investmentsMain = byId("financeMain");
  const cashflowMain = byId("financeCashflowMain");
  const tabButtons = document.querySelectorAll("[data-fin-tab]");

  if (investmentsMain) {
    investmentsMain.style.display = normalized === "investments" ? "grid" : "none";
  }
  if (cashflowMain) {
    cashflowMain.style.display = normalized === "cashflow" ? "grid" : "none";
  }

  tabButtons.forEach((btn) => {
    const isActive = String(btn.getAttribute("data-fin-tab") || "") === normalized;
    btn.classList.toggle("is-active", isActive);
    btn.setAttribute("aria-selected", isActive ? "true" : "false");
  });

  localStorage.setItem(FIN_ACTIVE_TAB_KEY, normalized);
}

function initFinanceTabs() {
  const tabButtons = document.querySelectorAll("[data-fin-tab]");
  if (!tabButtons.length) return;

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const target = String(btn.getAttribute("data-fin-tab") || "investments");
      setFinanceTab(target);
      if (target === "cashflow") {
        await refreshByDomains(["cashflow"]);
      }
    });
  });

  const saved = String(localStorage.getItem(FIN_ACTIVE_TAB_KEY) || "investments");
  setFinanceTab(saved);
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
    deferredDataMs: null,
    deferredChartsMs: null,
    secondaryMs: null,
    secondaryCacheHit: false,
  };
  }
  try {
    const criticalFetchStart = perfEnabled ? performance.now() : 0;
    const [summary, transactions] = await Promise.all([
      fetchFinanceJson("/api/finance/summary", { portfolio: [], currency_rates: [] }),
      fetchFinanceJson("/api/finance/transactions?limit=5000", []),
    ]);
    if (perfEnabled) _setPerfRunPatch(perfRunId, { criticalFetchMs: _ms(performance.now() - criticalFetchStart) });

    FIN.summary = summary || { portfolio: [], currency_rates: [] };
    FIN.portfolio = FIN.summary.portfolio || [];
    FIN.transactions = Array.isArray(transactions) ? transactions : [];

    const criticalRenderStart = perfEnabled ? performance.now() : 0;
    renderSummary(summary);
    renderCurrency(summary.currency_rates || []);
    renderPortfolio(FIN.portfolio);
    renderTransactions(transactions);
    if (perfEnabled) {
      _setPerfRunPatch(perfRunId, { criticalRenderMs: _ms(performance.now() - criticalRenderStart) });
      _commitPerf(perfRunId);
    }
    updateLastUpdated();

    // Fill non-critical cards after first paint.
    _scheduleDeferred(async () => {
      const deferredDataStart = perfEnabled ? performance.now() : 0;
      const useWidgetCache = useSecondaryCache && isFinFlagOn("secondaryPanelCache");
      const [watchlist, goals, assets, dividends, allocTargets, passiveGoal] = await Promise.all([
        fetchWidgetJsonCached(
          "watchlist",
          "/api/finance/watchlist",
          [],
          { useCache: useWidgetCache },
        ),
        fetchWidgetJsonCached(
          "goals",
          "/api/finance/goals",
          [],
          { useCache: useWidgetCache },
        ),
        fetchWidgetJsonCached(
          "assets",
          "/api/finance/assets",
          [],
          { useCache: useWidgetCache },
        ),
        fetchWidgetJsonCached(
          "dividends",
          "/api/finance/dividends",
          [],
          { useCache: useWidgetCache },
        ),
        fetchWidgetJsonCached(
          "allocation-targets",
          "/api/finance/allocation-targets",
          [],
          { useCache: useWidgetCache },
        ),
        fetchWidgetJsonCached(
          "passive-income",
          "/api/finance/goals/passive-income",
          { target_monthly: 0, note: "" },
          { useCache: useWidgetCache },
        ),
      ]);

      const selectedMonth = String(byId("finCashflowMonth")?.value || "").trim();
      const effectiveMonth = selectedMonth || currentMonthKey();
      const selectedType = String(byId("finCashflowType")?.value || "").trim();
      const [cashflowEntries, cashflowSummary, cashflowAnalytics, cashflowBudgetPayload] = await Promise.all([
        fetchWidgetJsonCached(
          `cashflow-entries:${selectedMonth || "all"}:${selectedType || "all"}`,
          `/api/finance/cashflow?limit=500${selectedMonth ? `&month=${encodeURIComponent(selectedMonth)}` : ""}${selectedType ? `&type=${encodeURIComponent(selectedType)}` : ""}`,
          [],
          { useCache: useWidgetCache },
        ),
        fetchWidgetJsonCached(
          "cashflow-summary",
          "/api/finance/cashflow/summary?months=12",
          {
            current_month: "",
            current_income: 0,
            current_expense: 0,
            current_balance: 0,
            total_income: 0,
            total_expense: 0,
            total_balance: 0,
            monthly: [],
          },
          { useCache: useWidgetCache },
        ),
        fetchWidgetJsonCached(
          `cashflow-analytics:${effectiveMonth}`,
          `/api/finance/cashflow/analytics?month=${encodeURIComponent(effectiveMonth)}`,
          {
            month: effectiveMonth,
            totals: { income: 0, expense: 0, balance: 0, savings_rate_pct: 0 },
            projection: { projected_income: 0, projected_expense: 0, projected_balance: 0 },
            categories: { income: [], expense: [] },
            daily: [],
            top_expenses: [],
            budget: { items: [], total_limit: 0, total_spent: 0, total_remaining: 0 },
          },
          { useCache: useWidgetCache },
        ),
        fetchWidgetJsonCached(
          `cashflow-budget:${effectiveMonth}`,
          `/api/finance/cashflow/budget?month=${encodeURIComponent(effectiveMonth)}`,
          { month: effectiveMonth, budget: {} },
          { useCache: useWidgetCache },
        ),
      ]);

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
      FIN.cashflowEntries = Array.isArray(cashflowEntries) ? cashflowEntries : [];
      FIN.cashflowSummary = cashflowSummary || { monthly: [] };
      FIN.cashflowAnalytics = cashflowAnalytics || null;
      FIN.cashflowBudget = cashflowBudgetPayload?.budget || {};

      renderSummary(FIN.summary);
      renderWatchlist(FIN.watchlist);
      renderGoals(FIN.goals);
      renderDividends(FIN.dividends);
      renderCashflowSummary(FIN.cashflowSummary);
      renderCashflow(FIN.cashflowEntries);
      renderCashflowAnalytics(FIN.cashflowAnalytics);
      renderCashflowBudgetStatus(FIN.cashflowAnalytics);
      syncCashflowMonthFilter(FIN.cashflowSummary);
      if (FIN._rebalanceLoaded) {
        renderRebalance();
        renderProjection();
        renderDividendCeiling();
        renderIndependenceScenario();
      }
      populateHistorySelect();
      applyHistoryPrefs();
      loadHistoryFromControls();
      checkWatchlistAlerts();
      checkDividendAlerts();
      checkGoalsMilestones(FIN.goals);

      if (perfEnabled) {
        _setPerfRunPatch(perfRunId, {
          deferredDataMs: _ms(performance.now() - deferredDataStart),
        });
        _commitPerf(perfRunId);
      }
      updateLastUpdated();
    });

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
  const quoteStale = !!meta.quoteStale;
  const staleItems = Number(meta.staleItems || 0);
  if (!stale) {
    chip.className = quoteStale
      ? "fin-market-health fin-market-health--stale"
      : "fin-market-health fin-market-health--ok";
    chip.textContent = quoteStale ? "parcialmente defasado" : "ao vivo";
    chip.title = quoteStale
      ? `Dados ao vivo com ${staleItems} cotacao(oes) em fallback/stale`
      : "Dados de mercado em tempo real";
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
    finFetch("/api/finance/transactions?limit=5000").then((r) => r.json()),
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

async function refreshCashflowPanel() {
  const month = String(byId("finCashflowMonth")?.value || "").trim();
  const effectiveMonth = month || currentMonthKey();
  const entryType = String(byId("finCashflowType")?.value || "").trim();
  const [entries, summary, analytics, budgetPayload] = await Promise.all([
    finFetch(`/api/finance/cashflow?limit=500${month ? `&month=${encodeURIComponent(month)}` : ""}${entryType ? `&type=${encodeURIComponent(entryType)}` : ""}`).then((r) => r.json()),
    finFetch("/api/finance/cashflow/summary?months=12").then((r) => r.json()),
    finFetch(`/api/finance/cashflow/analytics?month=${encodeURIComponent(effectiveMonth)}`).then((r) => r.json()),
    finFetch(`/api/finance/cashflow/budget?month=${encodeURIComponent(effectiveMonth)}`).then((r) => r.json()),
  ]);
  FIN.cashflowEntries = Array.isArray(entries) ? entries : [];
  FIN.cashflowSummary = summary || { monthly: [] };
  FIN.cashflowAnalytics = analytics || null;
  FIN.cashflowBudget = budgetPayload?.budget || {};
  renderCashflowSummary(FIN.cashflowSummary);
  renderCashflow(FIN.cashflowEntries);
  renderCashflowAnalytics(FIN.cashflowAnalytics);
  renderCashflowBudgetStatus(FIN.cashflowAnalytics);
  syncCashflowMonthFilter(FIN.cashflowSummary);
  updateLastUpdated();
}

async function refreshImportPanels() {
  const [summary, transactions, assets, allocTargets, dividends] = await Promise.all([
    finFetch("/api/finance/summary").then((r) => r.json()),
    finFetch("/api/finance/transactions?limit=5000").then((r) => r.json()),
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
    cashflow: refreshCashflowPanel,
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
    FIN.opsHealth = cached.health && cached.health.ok ? cached.health : null;
    renderIndices((FIN.marketData && FIN.marketData.indices) || {});
    renderMarketDataHealth({
      stale: !!cached.marketStale,
      quoteStale: !!cached.marketQuoteStale,
      staleItems: Number(cached.marketStaleItems || 0),
      snapshotAt: cached.marketSnapshotAt || null,
      snapshotAgeMs: cached.marketSnapshotAgeMs || 0,
      snapshotExpired: !!cached.marketSnapshotExpired,
    });
    renderPerformanceMetrics(FIN.performanceMetrics);
    renderOpsHealth(FIN.opsHealth);
    return { cacheHit: true, durationMs: _ms(performance.now() - started) };
  }

  const [marketMeta, metrics, health] = await Promise.all([
    (async () => {
      try {
        const resp = await finFetch("/api/finance/market-data");
        if (!resp.ok) throw new Error(`market status ${resp.status}`);
        const live = await resp.json();
        _saveMarketSnapshot(live);
        return {
          market: live || {},
          stale: false,
          quoteStale: !!(live?.meta?.quality?.has_stale_data),
          staleItems: Number(live?.meta?.quality?.stale_items || 0),
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
            quoteStale: !!(snap.market?.meta?.quality?.has_stale_data),
            staleItems: Number(snap.market?.meta?.quality?.stale_items || 0),
            snapshotAt: snap.ts || null,
            snapshotAgeMs: snap.ageMs || 0,
            snapshotExpired: !!snap.isExpired,
          };
        }
        return {
          market: {},
          stale: true,
          quoteStale: false,
          staleItems: 0,
          snapshotAt: null,
          snapshotAgeMs: 0,
          snapshotExpired: true,
        };
      }
    })(),
    finFetch("/api/finance/metrics/performance").then((r) => r.json()).catch(() => null),
    finFetch("/api/finance/health").then((r) => r.json()).catch(() => null),
  ]);

  FIN.marketData = marketMeta.market || {};
  FIN.performanceMetrics = metrics && !metrics.error ? metrics : null;
  FIN.opsHealth = health && health.ok ? health : null;
  FIN._secondaryCache = {
    ts: Date.now(),
    payload: {
      market: FIN.marketData,
      marketStale: !!marketMeta.stale,
      marketQuoteStale: !!marketMeta.quoteStale,
      marketStaleItems: Number(marketMeta.staleItems || 0),
      marketSnapshotAt: marketMeta.snapshotAt || null,
      marketSnapshotAgeMs: marketMeta.snapshotAgeMs || 0,
      marketSnapshotExpired: !!marketMeta.snapshotExpired,
      metrics,
      health,
    },
  };

  renderIndices((FIN.marketData && FIN.marketData.indices) || {});
  renderWatchlist(FIN.watchlist || []);
  renderMarketDataHealth(marketMeta);
  renderPerformanceMetrics(FIN.performanceMetrics);
  renderOpsHealth(FIN.opsHealth);
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

function _formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function renderOpsHealth(health) {
  const el = byId("finOpsHealthContent");
  if (!el) return;

  if (!health || health.ok === false) {
    el.innerHTML = '<p class="fin-empty">Health indisponível no momento.</p>';
    return;
  }

  const checks = health.checks || {};
  const quota = checks.brapi_quota || {};
  const market = checks.market_quality || {};
  const providers = checks.providers || {};
  const providerRows = Object.values(providers.metrics || {}).sort((a, b) => {
    return String(a.provider || "").localeCompare(String(b.provider || ""));
  });

  const degradedProviders = Array.isArray(providers.degraded_providers)
    ? providers.degraded_providers
    : [];
  const statusCls = _healthStatusClass(health.status);
  const updatedAt = health.timestamp
    ? new Date(health.timestamp).toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
    })
    : "—";

  const providersHtml = providerRows.length
    ? providerRows.map((p) => {
      const pName = escapeHtml(String(p.provider || "—").toUpperCase());
      const success = _formatPercent(p.success_rate);
      const fallback = _formatPercent(p.fallback_rate);
      const latency = p.avg_latency_ms == null ? "—" : `${formatNumber(p.avg_latency_ms, 1)} ms`;
      const total = formatNumber(p.total || 0, 0);
      const degraded = degradedProviders.includes(p.provider)
        ? '<span class="fin-health-provider-badge fin-health-provider-badge--warn">degradado</span>'
        : '<span class="fin-health-provider-badge">ok</span>';
      return `
        <div class="fin-health-provider-row">
          <div class="fin-health-provider-name">${pName} ${degraded}</div>
          <div class="fin-health-provider-metrics">
            <span>Total: <strong>${total}</strong></span>
            <span>Sucesso: <strong>${success}</strong></span>
            <span>Fallback: <strong>${fallback}</strong></span>
            <span>Latência média: <strong>${latency}</strong></span>
          </div>
        </div>
      `;
    }).join("")
    : '<p class="fin-empty">Sem métricas de provedores hoje.</p>';

  el.innerHTML = `
    <div class="fin-health-overview">
      <span class="${statusCls}">${escapeHtml(String(health.status || "unknown").toUpperCase())}</span>
      <span class="fin-health-meta">Atualizado: ${updatedAt}</span>
      <span class="fin-health-meta">BRAPI: ${formatNumber(quota.remaining || 0, 0)} restantes</span>
      <span class="fin-health-meta">Stale: ${formatNumber(market.stale_items || 0, 0)}</span>
    </div>
    <div class="fin-health-provider-list">
      ${providersHtml}
    </div>
  `;
}

function checkDividendAlerts() {
  const prefs = getAlertPrefs();
  const total = (FIN.dividends || []).reduce((sum, d) => sum + (d.total_amount || 0), 0);
  const key = "fin_last_dividend_total";
  const prev = Number(localStorage.getItem(key) || "0");
  const increase = total - prev;
  if (increase >= prefs.dividendMinIncrease && prev > 0) {
    showToast(`Novo provento detectado. Total acumulado: ${formatBRL(total)}`, "info");
    if (prefs.notifyDividendsDesktop && Notification.permission === "granted") {
      new Notification("💸 Novo provento detectado", {
        body: `Acumulado: ${formatBRL(total)} (variação: ${formatBRL(increase)})`,
        icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>💸</text></svg>",
      });
    }
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
  const FX_SYMBOLS = new Set(["USDBRL=X", "EURBRL=X", "BTCBRL=X"]);
  el.innerHTML = entries
    .map(([key, idx]) => {
      const cls = changeClass(idx.change_pct);
      const isFx = FX_SYMBOLS.has(key);
      const priceStr = isFx
        ? formatBRL(idx.price)
        : `${formatNumber(idx.price, 0)} pts`;
      const source = idx.source ? String(idx.source).toUpperCase() : "";
      const staleBadge = idx.is_stale
        ? '<span class="fin-quote-badge fin-quote-badge--stale" title="Cotacao em fallback">stale</span>'
        : "";
      const sourceBadge = source
        ? `<span class="fin-quote-badge" title="Fonte da cotacao">${escapeHtml(source)}</span>`
        : "";
      return `
        <div class="fin-index-row">
          <span class="fin-index-name-wrap">
            <span class="fin-index-name">${escapeHtml(idx.name)}</span>
            <span class="fin-quote-badges">${sourceBadge}${staleBadge}</span>
          </span>
          <span class="fin-index-price">${priceStr}</span>
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
    el.innerHTML = renderEmptyState(
      "Nenhum ativo no portfólio ainda.",
      "Adicionar ativo",
      "addAsset",
    );
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
      const displayType = detectAssetDisplayType(p);
      const typeCls = badgeClass(displayType);
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
            <span class="fin-badge ${typeCls}">${escapeHtml(assetTypeLabelPt(displayType))}</span>
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
            <button class="fin-del-btn" data-action="addTxForAsset" data-id="${p.asset_id}" title="Nova transação">＋</button>
            <button class="fin-del-btn" data-action="deleteAsset" data-id="${p.asset_id}" title="Remover">✕</button>
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
      <button class="fin-page-btn" data-action="portfolioPagePrev" ${FIN._portfolioPage === 0 ? "disabled" : ""}>‹</button>
      <span class="fin-page-info">${FIN._portfolioPage + 1} / ${totalPages} (${sorted.length} ativos)</span>
      <button class="fin-page-btn" data-action="portfolioPageNext" ${FIN._portfolioPage >= totalPages - 1 ? "disabled" : ""}>›</button>
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
      <button id="btnBatchEditTx" class="btn-text" type="button">✎ Lote</button>
      <span class="fin-tx-count">${filtered.length} de ${txns.length}</span>
    </div>
  `;

  if (!filtered.length) {
    el.innerHTML = filterBar + renderEmptyState(
      "Nenhuma transação encontrada para os filtros atuais.",
      "Limpar filtros",
      "clearTxFilters",
    );
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
            <button class="fin-del-btn" data-action="openEditTransactionModal" data-id="${t.id}" title="Editar">✎</button>
            <button class="fin-del-btn" data-action="deleteTransaction" data-id="${t.id}" title="Excluir">✕</button>
          </td>
        </tr>
      `;
    })
    .join("");

  let paginationHtml = "";
  if (totalPages > 1) {
    paginationHtml = `<div class="fin-pagination">
      <button class="fin-page-btn" data-action="txPagePrev" ${_txPage === 0 ? "disabled" : ""}>‹</button>
      <span class="fin-page-info">${_txPage + 1} / ${totalPages} (${filtered.length} itens)</span>
      <button class="fin-page-btn" data-action="txPageNext" ${_txPage >= totalPages - 1 ? "disabled" : ""}>›</button>
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
    el.innerHTML = renderEmptyState(
      "Watchlist vazia no momento.",
      "Adicionar ativo",
      "addWatchlist",
    );
    return;
  }

  el.innerHTML = watchlist
    .map((w) => {
      const targetStr = w.target_price ? `Alvo: ${formatBRL(w.target_price)}` : "";
      const dir = w.alert_above ? "↑" : "↓";
      const displayType = detectAssetDisplayType(w);
      const typeCls = badgeClass(displayType);
      const hasPrice = w.current_price != null;
      const priceStr = hasPrice ? formatBRL(w.current_price) : "—";
      const quote = FIN.marketData?.stocks?.[String(w.symbol || "").toUpperCase()] || null;
      const staleBadge = quote?.is_stale
        ? '<span class="fin-quote-badge fin-quote-badge--stale" title="Ultimo preco salvo (fallback)">stale</span>'
        : "";
      const sourceBadge = quote?.source
        ? `<span class="fin-quote-badge" title="Fonte da cotacao">${escapeHtml(String(quote.source).toUpperCase())}</span>`
        : "";

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
            <span class="fin-badge ${typeCls}">${escapeHtml(assetTypeLabelPt(displayType))}</span>
            <span class="fin-wl-name">${escapeHtml(w.name)}</span>
          </div>
          <div class="fin-wl-prices">
            <span class="fin-wl-price">${priceStr}</span>
            ${sourceBadge}
            ${staleBadge}
            ${changeHtml}
          </div>
          <div class="fin-wl-meta">
            <span class="fin-wl-target">${targetStr} ${dir}</span>
            ${alertHtml}
          </div>
          <div class="fin-wl-actions">
            <button class="fin-del-btn" data-action="openEditWatchlistModal" data-id="${w.id}" title="Editar">✎</button>
            <button class="fin-del-btn" data-action="deleteWatchlistItem" data-id="${w.id}" title="Remover">✕</button>
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
    el.innerHTML = renderEmptyState(
      "Nenhuma meta financeira criada.",
      "Criar meta",
      "addGoal",
    );
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
              <button class="fin-del-btn" data-action="openEditGoalModal" data-id="${g.id}" title="Editar">✎</button>
              <button class="fin-del-btn" data-action="deleteGoal" data-id="${g.id}" title="Excluir">✕</button>
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

function currentMonthKey() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
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

  const html = rows.map((entry) => {
    const type = String(entry.entry_type || "");
    const isIncome = type === "income";
    const badge = isIncome ? "fin-badge-buy" : "fin-badge-sell";
    const label = isIncome ? "GANHO" : "GASTO";
    const amountCls = isIncome ? "fin-up" : "fin-down";
    return `
      <tr>
        <td>${escapeHtml(String(entry.entry_date || "").slice(0, 10))}</td>
        <td><span class="fin-badge ${badge}">${label}</span></td>
        <td>${escapeHtml(entry.category || "—")}</td>
        <td>${escapeHtml(entry.description || "—")}</td>
        <td class="text-right mono ${amountCls}">${formatBRL(entry.amount || 0)}</td>
        <td>${escapeHtml(entry.notes || "")}</td>
        <td class="text-center">
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
            <th>Categoria</th>
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

function allocationBucketLabel(asset) {
  const displayType = detectAssetDisplayType(asset);
  if (displayType === "fii") return "Fundos Imobiliarios";
  if (displayType === "stock") return "Acoes";
  if (displayType === "etf") return "ETF";
  if (displayType === "crypto") return "Cripto";
  if (displayType === "fund" || displayType === "fundo") return "Fundos";
  if (displayType === "renda-fixa") return "Renda Fixa";
  return assetTypeLabelPt(displayType || "Ativo");
}

function buildAllocationByBucket(summary) {
  const byBucket = new Map();
  const portfolio = Array.isArray(summary?.portfolio) ? summary.portfolio : [];

  if (portfolio.length) {
    for (const asset of portfolio) {
      const value = Number(asset?.current_price || 0) * Number(asset?.quantity || 0);
      if (!(value > 0)) continue;
      const bucket = allocationBucketLabel(asset);
      byBucket.set(bucket, Number(byBucket.get(bucket) || 0) + value);
    }
  }

  // Fallback for payloads without portfolio details.
  if (!byBucket.size) {
    const alloc = summary?.allocation || {};
    for (const [type, value] of Object.entries(alloc)) {
      const num = Number(value || 0);
      if (!(num > 0)) continue;
      const bucket = allocationBucketLabel({ asset_type: type });
      byBucket.set(bucket, Number(byBucket.get(bucket) || 0) + num);
    }
  }

  return [...byBucket.entries()].filter(([_, value]) => value > 0);
}

function renderAllocationChart(summary) {
  if (typeof Chart === "undefined") return;
  const canvas = byId("allocationChart");
  if (!canvas) return;
  const entries = buildAllocationByBucket(summary);

  if (!entries.length) {
    canvas.parentElement.innerHTML = '<p class="fin-empty">Sem dados de alocação.</p>';
    return;
  }

  const labels = entries.map(([k]) => k);
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
  const investedBySymbol = new Map(sorted.map((p) => [String(p.symbol || ""), Number(p.total_invested || 0)]));
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
            footer: (items) => {
              const item = items?.[0];
              if (!item) return "";
              const symbol = String(item.label || "");
              const invested = Number(investedBySymbol.get(symbol) || 0);
              if (!(invested > 0)) return "";
              const pnl = Number(item.raw || 0);
              const pct = (pnl / invested) * 100;
              return `Rentabilidade: ${formatPct(pct)}`;
            },
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
            footer: (items) => {
              const investedItem = (items || []).find((it) => it.dataset?.label === "Investido");
              const currentItem = (items || []).find((it) => it.dataset?.label === "Valor Atual");
              if (!investedItem || !currentItem) return "";
              const invested = Number(investedItem.raw || 0);
              const currentValue = Number(currentItem.raw || 0);
              if (!(invested > 0)) return "";
              const pnl = currentValue - invested;
              const pct = (pnl / invested) * 100;
              return `P&L: ${formatBRL(pnl)} (${formatPct(pct)})`;
            },
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
    submitAddCashflow,
    submitEditCashflow,
    submitCashflowBudget,
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
        <button class="fin-import-tab active" data-tab="general">⤵ Importação Geral</button>
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
            ⤵ Importar Dados
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
      <button type="submit" class="fin-form-submit">＋ Adicionar Ativo</button>
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

function openAddCashflowModal() {
  openFinModal("Novo Lançamento (Ganho/Gasto)", `
    <form data-form-action="submitAddCashflow">
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Tipo</label>
          <select id="fmCfType">
            <option value="income">Ganho</option>
            <option value="expense">Gasto</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Data</label>
          <input id="fmCfDate" type="date" value="${new Date().toISOString().slice(0, 10)}" required />
        </div>
      </div>
      <div class="fin-form-row">
        <div class="fin-form-group">
          <label>Valor (R$)</label>
          <input id="fmCfAmount" type="number" min="0.01" step="0.01" required />
        </div>
        <div class="fin-form-group">
          <label>Categoria</label>
          <input id="fmCfCategory" placeholder="Ex.: Salário, Moradia, Alimentação" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Descrição</label>
        <input id="fmCfDescription" placeholder="Resumo do lançamento" required />
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

async function submitAddCashflow(e) {
  e.preventDefault();
  const body = {
    entry_type: String(byId("fmCfType")?.value || "expense"),
    amount: Number(byId("fmCfAmount")?.value || 0),
    category: String(byId("fmCfCategory")?.value || "").trim(),
    description: String(byId("fmCfDescription")?.value || "").trim(),
    entry_date: String(byId("fmCfDate")?.value || "").trim(),
    notes: String(byId("fmCfNotes")?.value || "").trim(),
  };
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
          <label>Valor (R$)</label>
          <input id="fmCfAmount" type="number" min="0.01" step="0.01" value="${Number(entry.amount || 0)}" required />
        </div>
        <div class="fin-form-group">
          <label>Categoria</label>
          <input id="fmCfCategory" value="${escapeHtml(entry.category || "")}" />
        </div>
      </div>
      <div class="fin-form-group">
        <label>Descrição</label>
        <input id="fmCfDescription" value="${escapeHtml(entry.description || "")}" required />
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
  const body = {
    entry_type: String(byId("fmCfType")?.value || "expense"),
    amount: Number(byId("fmCfAmount")?.value || 0),
    category: String(byId("fmCfCategory")?.value || "").trim(),
    description: String(byId("fmCfDescription")?.value || "").trim(),
    entry_date: String(byId("fmCfDate")?.value || "").trim(),
    notes: String(byId("fmCfNotes")?.value || "").trim(),
  };
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

// Dividends domain moved to app/static/finance_dividends.js.

function getCadastroCollections() {
  return {
    assets: FIN.assets.map((a) => ({
      title: `${a.symbol} — ${a.name || a.symbol}`,
      subtitle: assetTypeLabelPt(a.asset_type),
      meta: [
        `ID ${a.id}`,
        assetTypeLabelPt(a.asset_type || "sem tipo"),
      ],
      search: `${a.symbol} ${a.name || ""} ${a.asset_type || ""}`.toLowerCase(),
    })),
    watchlist: FIN.watchlist.map((w) => ({
      title: `${w.symbol} — ${w.name || w.symbol}`,
      subtitle: "watchlist",
      meta: [
        assetTypeLabelPt(w.asset_type || "sem tipo"),
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
    cashflow: FIN.cashflowEntries.map((entry) => ({
      title: `${entry.entry_type === "income" ? "Ganho" : "Gasto"} — ${formatBRL(entry.amount || 0)}`,
      subtitle: entry.category || "sem categoria",
      meta: [
        String(entry.entry_date || "").slice(0, 10),
        entry.description || "sem descrição",
      ],
      search: `${entry.entry_type || ""} ${entry.category || ""} ${entry.description || ""} ${entry.notes || ""}`.toLowerCase(),
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
        <option value="cashflow" ${initialType === "cashflow" ? "selected" : ""}>Ganhos/Gastos</option>
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

// Price history domain moved to app/static/finance_history.js.

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
            <strong>${escapeHtml(assetTypeLabelPt(s.asset_type))}</strong>
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
// Export Data
// ══════════════════════════════════════════════════════════

function _downloadBlob(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1200);
}

function _csvEscape(value) {
  const txt = String(value ?? "");
  return /[",\n;]/.test(txt) ? `"${txt.replace(/"/g, '""')}"` : txt;
}

function _toCsv(rows, headers) {
  const lines = [];
  lines.push(headers.map((h) => _csvEscape(h)).join(";"));
  rows.forEach((row) => {
    lines.push(row.map((v) => _csvEscape(v)).join(";"));
  });
  return lines.join("\n");
}

function exportFilteredCsv(type) {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");

  if (type === "transactions") {
    let rows = [...(FIN.transactions || [])];
    const f = FIN._txFilter || {};
    if (f.asset) rows = rows.filter((t) => t.asset_id === Number(f.asset));
    if (f.type) rows = rows.filter((t) => t.tx_type === f.type);
    if (f.dateFrom) rows = rows.filter((t) => String(t.tx_date || "").slice(0, 10) >= f.dateFrom);
    if (f.dateTo) rows = rows.filter((t) => String(t.tx_date || "").slice(0, 10) <= f.dateTo);
    if (f.minTotal !== "") rows = rows.filter((t) => Number(t.total || 0) >= Number(f.minTotal));
    if (f.maxTotal !== "") rows = rows.filter((t) => Number(t.total || 0) <= Number(f.maxTotal));

    const csv = _toCsv(
      rows.map((t) => [
        (t.tx_date || "").slice(0, 10),
        t.tx_type || "",
        t.symbol || "",
        t.quantity || 0,
        t.price || 0,
        t.total || 0,
        t.fees || 0,
        t.notes || "",
      ]),
      ["data", "tipo", "ativo", "quantidade", "preco", "total", "taxas", "notas"],
    );
    _downloadBlob(`transacoes-filtradas-${stamp}.csv`, csv, "text/csv;charset=utf-8");
    showToast(`CSV filtrado exportado (${rows.length} linhas).`, "success");
    return;
  }

  if (type === "dividends") {
    const rows = [...(FIN.dividends || [])];
    const csv = _toCsv(
      rows.map((d) => [
        d.symbol || "",
        d.div_type || "",
        (d.pay_date || d.ex_date || "").slice(0, 10),
        d.quantity || 0,
        d.amount_per_share || 0,
        d.total_amount || 0,
        d.notes || "",
      ]),
      ["ativo", "tipo", "data", "quantidade", "valor_por_cota", "total", "notas"],
    );
    _downloadBlob(`dividendos-${stamp}.csv`, csv, "text/csv;charset=utf-8");
    showToast(`CSV de dividendos exportado (${rows.length} linhas).`, "success");
    return;
  }

  const rows = [...(FIN.portfolio || [])];
  const csv = _toCsv(
    rows.map((p) => [
      p.symbol || "",
      p.name || "",
      p.asset_type || "",
      p.quantity || 0,
      p.avg_price || 0,
      p.current_price || 0,
      p.total_invested || 0,
    ]),
    ["ativo", "nome", "tipo", "quantidade", "preco_medio", "preco_atual", "investido"],
  );
  _downloadBlob(`portfolio-${stamp}.csv`, csv, "text/csv;charset=utf-8");
  showToast(`CSV do portfólio exportado (${rows.length} linhas).`, "success");
}

function exportChartImage(chartKey, format) {
  const chart = FIN.charts[chartKey];
  if (!chart || !chart.canvas) {
    showToast("Gráfico não disponível para exportação.", "warning");
    return;
  }
  const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
  const dataUrl = chart.toBase64Image("image/png", 1);
  const safeName = chartKey.replace(/[^a-z0-9_-]/gi, "").toLowerCase();

  if (format === "svg") {
    const width = chart.width || 1280;
    const height = chart.height || 720;
    const svg = `<?xml version="1.0" encoding="UTF-8"?>\n`
      + `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`
      + `<image href="${dataUrl}" width="${width}" height="${height}" /></svg>`;
    _downloadBlob(`grafico-${safeName}-${stamp}.svg`, svg, "image/svg+xml;charset=utf-8");
    showToast("Gráfico exportado em SVG.", "success");
    return;
  }

  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = `grafico-${safeName}-${stamp}.png`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  showToast("Gráfico exportado em PNG.", "success");
}

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
            <option value="csv_local">CSV filtrado (local)</option>
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
      <div class="fin-form-row" style="margin-top:8px">
        <div class="fin-form-group">
          <label>Gráfico</label>
          <select id="fmChartType">
            <option value="dividends">Fluxo de dividendos</option>
            <option value="allocation">Alocação</option>
            <option value="performance">Performance</option>
            <option value="history">Histórico</option>
            <option value="pnl">P&L</option>
          </select>
        </div>
        <div class="fin-form-group">
          <label>Imagem</label>
          <select id="fmChartFormat">
            <option value="png">PNG</option>
            <option value="svg">SVG</option>
          </select>
        </div>
      </div>
      <button id="fmExportBtn" class="fin-form-submit">⤴ Exportar</button>
      <button id="fmExportChartBtn" class="btn-text" type="button" style="margin-top:8px">🖼 Baixar gráfico</button>
    </div>
  `);

  const btn = byId("fmExportBtn");
  if (btn) {
    btn.addEventListener("click", () => {
      const format = byId("fmExportFormat").value;
      const type = byId("fmExportType").value;
      if (format === "csv_local") {
        exportFilteredCsv(type === "all" ? "portfolio" : type);
        closeFinModal();
        return;
      }
      window.location.href = `/api/finance/export?format=${format}&type=${type}`;
      closeFinModal();
    });
  }

  byId("fmExportChartBtn")?.addEventListener("click", () => {
    const map = {
      dividends: "dividends",
      allocation: "allocation",
      performance: "performance",
      history: "history",
      pnl: "pnl",
    };
    const chartType = byId("fmChartType")?.value || "dividends";
    const chartFormat = byId("fmChartFormat")?.value || "png";
    exportChartImage(map[chartType] || "dividends", chartFormat);
  });
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
  const prefs = getAlertPrefs();
  if (!prefs.goalMilestonesEnabled) return;
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

      if (prefs.notifyGoalsDesktop && Notification.permission === "granted") {
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
  const prefs = getAlertPrefs();
  // Always render visual banner regardless of notification permission
  const triggered = FIN.watchlist.filter((w) => {
    if (w.current_price == null || !w.target_price) return false;
    return w.alert_above
      ? w.current_price >= w.target_price
      : w.current_price <= w.target_price;
  });
  renderWatchlistAlertsBanner(triggered);

  if (!prefs.notifyWatchlistDesktop || Notification.permission !== "granted") return;
  const notified = JSON.parse(localStorage.getItem("fin_notified_alerts") || "{}");
  const now = Date.now();
  const cooldownMs = Math.max(1, Number(prefs.watchlistCooldownMinutes || 60)) * 60000;
  // Prune entries older than 1 hour
  Object.keys(notified).forEach((k) => {
    if (now - notified[k] > cooldownMs) delete notified[k];
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

// Finance settings domain moved to app/static/finance_settings.js.

// AI analysis domain moved to app/static/finance_ai.js.

// Bootstrap domain moved to app/static/finance_bootstrap.js.

/* ══════════════════════════════════════════════════════════
   Finance Bootstrap Domain
   ══════════════════════════════════════════════════════════ */

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
  initDensityMode();
  initFinancePWA();
  initA11yEnhancements();
  initFinanceLayoutTools();
  initFinanceKeyboardShortcuts();
  initQuickNav();
  if (isFinFlagOn("lazyRebalanceLoad")) {
    initRebalanceLazyLoad();
  } else {
    FIN._rebalanceLoaded = true;
  }
  maybeAutoOpenQuickTour();
  loadAll();

  const refreshBtn = byId("finRefreshBtn");
  if (refreshBtn) refreshBtn.addEventListener("click", loadAll);

  const chatInput = byId("finAIChatInput");
  if (chatInput) {
    chatInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendFinAIChat();
    });
  }

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
  bind("btnLayoutMode", toggleLayoutEditMode);
  bind("btnLayoutManage", openLayoutManagerModal);
  bind("btnLayoutPreset", openLayoutPresetModal);
  bind("btnLayoutReset", resetFinanceLayout);
  bind("btnTour", openQuickTourModal);
  bind("btnNotifications", setupNotifications);
  bind("finAIChatSend", sendFinAIChat);
  bind("finModalClose", closeFinModal);
  bind("btnRunRebalanceSim", renderRebalance);

  bind("btnRunProjection", renderProjection);
  bind("btnRunDividendCeiling", renderDividendCeiling);
  bind("btnRunIndependence", renderIndependenceScenario);

  const overlay = byId("finModalOverlay");
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeFinModal();
    });
  }

  const main = byId("financeMain");
  if (main) {
    main.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-empty-action]");
      if (!btn) return;
      runEmptyStateAction(btn.dataset.emptyAction || "");
    });
  }

  document.querySelectorAll(".fin-ai-btn[data-type]").forEach((btn) => {
    btn.addEventListener("click", () => requestAIAnalysis(btn.dataset.type));
  });

  const histSel = byId("historyAssetSelect");
  const histPeriodSel = byId("historyPeriodSelect");
  const histBenchmarkSel = byId("historyBenchmarkSelect");
  const histViewMode = byId("historyViewMode");
  const histInvested = byId("historyShowInvested");
  const histCompare = byId("historyCompareTotal");
  if (histSel) {
    histSel.addEventListener("change", loadHistoryFromControls);
  }
  if (histPeriodSel) {
    histPeriodSel.addEventListener("change", () => {
      if (typeof setHistoryQuickRange === "function") setHistoryQuickRange("");
      loadHistoryFromControls();
    });
  }
  if (histBenchmarkSel) histBenchmarkSel.addEventListener("change", loadHistoryFromControls);
  if (histViewMode) histViewMode.addEventListener("change", loadHistoryFromControls);
  if (histInvested) histInvested.addEventListener("change", loadHistoryFromControls);
  if (histCompare) histCompare.addEventListener("change", loadHistoryFromControls);
  document.querySelectorAll(".fin-history-range-btn[data-history-range]").forEach((btn) => {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const key = String(btn.dataset.historyRange || "").trim().toLowerCase();
      if (typeof setHistoryQuickRange === "function") setHistoryQuickRange(key);
      loadHistoryFromControls();
    });
  });

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

    if (action === "txPagePrev") { _txPage = Math.max(0, _txPage - 1); renderTransactions(FIN.transactions); return; }
    if (action === "txPageNext") { _txPage++; renderTransactions(FIN.transactions); return; }
    if (action === "portfolioPagePrev") { FIN._portfolioPage = Math.max(0, FIN._portfolioPage - 1); renderPortfolio(FIN.portfolio); return; }
    if (action === "portfolioPageNext") { FIN._portfolioPage++; renderPortfolio(FIN.portfolio); return; }

    const fn = actionMap[action];
    if (fn) fn(Number(btn.dataset.id));
  });

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

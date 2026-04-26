/* ══════════════════════════════════════════════════════════
   Price History Chart (Evolução Patrimonial)
   ══════════════════════════════════════════════════════════ */

const HISTORY_WORKER_URL = "/static/finance_worker.js";
const HISTORY_PREFS_KEY = "fin-history-prefs";
const HISTORY_DEFAULT_PERIOD = "180";
const HISTORY_QUICK_RANGES = new Set(["30", "90", "180", "365", "ytd", "max"]);
const HISTORY_DOWNSAMPLE_MAX_POINTS = 240;
let FIN_HISTORY_QUICK_RANGE = "";

function _downsampleHistory(labels, datasets, maxPoints = HISTORY_DOWNSAMPLE_MAX_POINTS) {
  const safeLabels = Array.isArray(labels) ? labels : [];
  const safeDatasets = Array.isArray(datasets) ? datasets : [];
  if (safeLabels.length <= maxPoints) {
    return { labels: safeLabels, datasets: safeDatasets };
  }

  const step = Math.ceil(safeLabels.length / maxPoints);
  const indices = [];
  for (let i = 0; i < safeLabels.length; i += step) {
    indices.push(i);
  }
  if (indices[indices.length - 1] !== safeLabels.length - 1) {
    indices.push(safeLabels.length - 1);
  }

  const nextLabels = indices.map((idx) => safeLabels[idx]);
  const nextDatasets = safeDatasets.map((dataset) => ({
    ...dataset,
    data: indices.map((idx) => (Array.isArray(dataset.data) ? dataset.data[idx] ?? null : null)),
  }));

  return {
    labels: nextLabels,
    datasets: nextDatasets,
  };
}

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

function readHistoryPrefs() {
  try {
    const raw = localStorage.getItem(HISTORY_PREFS_KEY);
    if (!raw) return {
      assetId: "",
      period: HISTORY_DEFAULT_PERIOD,
      compareTotal: false,
      benchmarks: [],
      showInvested: true,
      viewMode: "value",
      quickRange: "",
    };
    const parsed = JSON.parse(raw);
    const benchmarks = Array.isArray(parsed.benchmarks)
      ? parsed.benchmarks.filter((b) => ["ibov", "cdi", "ipca"].includes(String(b)))
      : (parsed.benchmark ? [String(parsed.benchmark)] : []);
    return {
      assetId: String(parsed.assetId || ""),
      period: String(parsed.period || HISTORY_DEFAULT_PERIOD),
      compareTotal: Boolean(parsed.compareTotal),
      benchmarks,
      showInvested: parsed.showInvested !== false,
      viewMode: parsed.viewMode === "base100" ? "base100" : "value",
      quickRange: HISTORY_QUICK_RANGES.has(String(parsed.quickRange || "").toLowerCase())
        ? String(parsed.quickRange || "").toLowerCase()
        : "",
    };
  } catch {
    return {
      assetId: "",
      period: HISTORY_DEFAULT_PERIOD,
      compareTotal: false,
      benchmarks: [],
      showInvested: true,
      viewMode: "value",
      quickRange: "",
    };
  }
}

function saveHistoryPrefs() {
  const sel = byId("historyAssetSelect");
  const compareEl = byId("historyCompareTotal");
  const benchmarkSel = byId("historyBenchmarkSelect");
  const investedEl = byId("historyShowInvested");
  const viewModeEl = byId("historyViewMode");
  if (!sel || !compareEl || !benchmarkSel || !investedEl) return;
  const benchmarks = [...benchmarkSel.selectedOptions].map((o) => o.value).filter(Boolean);
  localStorage.setItem(HISTORY_PREFS_KEY, JSON.stringify({
    assetId: sel.value || "",
    period: HISTORY_DEFAULT_PERIOD,
    compareTotal: compareEl.checked,
    benchmarks,
    showInvested: investedEl.checked,
    viewMode: viewModeEl?.value === "base100" ? "base100" : "value",
    quickRange: FIN_HISTORY_QUICK_RANGE || "",
  }));
}

function applyHistoryPrefs() {
  const prefs = readHistoryPrefs();
  const sel = byId("historyAssetSelect");
  const compareEl = byId("historyCompareTotal");
  const benchmarkSel = byId("historyBenchmarkSelect");
  const investedEl = byId("historyShowInvested");
  const viewModeEl = byId("historyViewMode");

  if (compareEl) compareEl.checked = !!prefs.compareTotal;
  if (benchmarkSel) {
    const allowedB = new Set(["ibov", "cdi", "ipca"]);
    [...benchmarkSel.options].forEach((opt) => {
      opt.selected = Array.isArray(prefs.benchmarks) && allowedB.has(opt.value) && prefs.benchmarks.includes(opt.value);
    });
  }
  if (investedEl) investedEl.checked = prefs.showInvested !== false;
  if (viewModeEl) viewModeEl.value = prefs.viewMode === "base100" ? "base100" : "value";
  FIN_HISTORY_QUICK_RANGE = HISTORY_QUICK_RANGES.has(prefs.quickRange) ? prefs.quickRange : "";
  _refreshHistoryQuickRangeUi();

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

function _historyFirstBuyDate(assetId) {
  const isTotal = assetId === "__total__";
  const normalizedAssetId = String(assetId || "");
  const dates = (FIN.transactions || [])
    .filter((tx) => {
      const txType = String(tx?.tx_type || "").trim().toLowerCase();
      if (txType !== "buy") return false;
      if (isTotal) return true;
      return String(tx?.asset_id || "") === normalizedAssetId;
    })
    .map((tx) => String(tx?.tx_date || "").slice(0, 10))
    .filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date));

  if (!dates.length) return null;
  dates.sort();
  return dates[0] || null;
}

function _trimHistoryBeforeDate(labels, datasets, startDate) {
  if (!startDate || !Array.isArray(labels) || !labels.length) {
    return { labels, datasets };
  }

  let firstValidIdx = labels.findIndex((label) => String(label) >= startDate);
  if (firstValidIdx < 0) {
    firstValidIdx = labels.length;
  }

  const nextLabels = labels.slice(firstValidIdx);
  const nextDatasets = (datasets || []).map((dataset) => ({
    ...dataset,
    data: Array.isArray(dataset?.data) ? dataset.data.slice(firstValidIdx) : [],
  }));

  return {
    labels: nextLabels,
    datasets: nextDatasets,
  };
}

function _historyRangeDays() {
  if (FIN_HISTORY_QUICK_RANGE === "ytd") {
    const now = new Date();
    const ytdStart = new Date(now.getFullYear(), 0, 1);
    return Math.max(1, Math.ceil((now - ytdStart) / 86400000) + 1);
  }
  if (FIN_HISTORY_QUICK_RANGE === "max") {
    return 3650;
  }
  if (["30", "90", "180", "365"].includes(FIN_HISTORY_QUICK_RANGE)) {
    return Number(FIN_HISTORY_QUICK_RANGE);
  }
  return Number(HISTORY_DEFAULT_PERIOD);
}

function _refreshHistoryQuickRangeUi() {
  document.querySelectorAll(".fin-history-range-btn[data-history-range]").forEach((btn) => {
    const key = String(btn.dataset.historyRange || "").trim().toLowerCase();
    const isActive = key && key === FIN_HISTORY_QUICK_RANGE;
    btn.classList.toggle("is-active", isActive);
    btn.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function setHistoryQuickRange(rangeKey) {
  const next = String(rangeKey || "").trim().toLowerCase();
  FIN_HISTORY_QUICK_RANGE = HISTORY_QUICK_RANGES.has(next) ? next : "";
  _refreshHistoryQuickRangeUi();
}

function _normalizeDatasetToBase100(data) {
  const numeric = (data || []).map((value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  });
  const base = numeric.find((value) => value != null && value > 0);
  if (!base) return numeric.map(() => null);
  return numeric.map((value) => {
    if (value == null) return null;
    return (value / base) * 100;
  });
}

function _applyHistoryViewMode(datasets, viewMode) {
  if (viewMode !== "base100") {
    return {
      datasets,
      usesBase100: false,
    };
  }

  const nextDatasets = (datasets || []).map((dataset) => {
    const label = String(dataset.label || "");
    if (dataset.yAxisID === "y1") {
      return {
        ...dataset,
        yAxisID: "yBase",
        data: (dataset.data || []).map((value) => {
          const parsed = Number(value);
          return Number.isFinite(parsed) ? (100 + parsed) : null;
        }),
      };
    }

    return {
      ...dataset,
      yAxisID: "yBase",
      fill: false,
      label: label.replace("(R$)", "(Base 100)").replace("Preço", "Índice"),
      data: _normalizeDatasetToBase100(dataset.data || []),
    };
  });

  return {
    datasets: nextDatasets,
    usesBase100: true,
  };
}

function _buildHistoryChartDataLocal(payload) {
  const {
    isTotal,
    compareTotal,
    benchmarkKeys,
    showInvested,
    primaryData,
    totalData,
    investedData,
    benchmarkSeries,
  } = payload;

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

  if (benchmarkKeys.length && Array.isArray(benchmarkSeries) && benchmarkSeries.length) {
    const colorMap = {
      ibov: { border: "#f59e0b", bg: "rgba(245,158,11,0.08)", label: "IBOV" },
      cdi: { border: "#22c55e", bg: "rgba(34,197,94,0.08)", label: "CDI" },
      ipca: { border: "#ef4444", bg: "rgba(239,68,68,0.08)", label: "IPCA" },
    };
    const maps = [];
    benchmarkSeries.forEach((seriesRows, idx) => {
      const key = benchmarkKeys[idx];
      const m = new Map();
      (seriesRows || []).forEach((row) => {
        const d = (row.captured_at || "").slice(0, 10);
        if (!d) return;
        m.set(d, Number(row.normalized_pct || 0));
      });
      if (m.size) maps.push({ key, map: m });
    });

    if (maps.length) {
      const mergedLabels = [...new Set([
        ...labels,
        ...maps.flatMap((it) => [...it.map.keys()]),
      ])].sort();
      datasets = datasets.map((ds) => {
        const map = new Map(labels.map((d, i) => [d, ds.data[i] ?? null]));
        return {
          ...ds,
          data: mergedLabels.map((d) => (map.has(d) ? map.get(d) : null)),
          spanGaps: true,
        };
      });

      maps.forEach((entry) => {
        const color = colorMap[entry.key] || colorMap.ibov;
        datasets.push({
          label: `Benchmark ${color.label} (%)`,
          data: mergedLabels.map((d) => (entry.map.has(d) ? entry.map.get(d) : null)),
          yAxisID: "y1",
          borderColor: color.border,
          backgroundColor: color.bg,
          fill: false,
          tension: 0.3,
          pointRadius: mergedLabels.length > 60 ? 0 : 2,
          borderWidth: 2,
          spanGaps: true,
        });
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

  return { labels, datasets };
}

async function _buildHistoryChartData(payload) {
  if (typeof Worker !== "function") {
    return _buildHistoryChartDataLocal(payload);
  }
  try {
    const worker = new Worker(HISTORY_WORKER_URL);
    const result = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("history worker timeout")), 4000);
      worker.onmessage = (event) => {
        clearTimeout(timer);
        resolve(event.data || {});
      };
      worker.onerror = (err) => {
        clearTimeout(timer);
        reject(err);
      };
      worker.postMessage({ type: "buildHistory", payload });
    });
    worker.terminate();
    if (!result || result.ok !== true || !result.payload) {
      throw new Error("history worker invalid payload");
    }
    return result.payload;
  } catch {
    return _buildHistoryChartDataLocal(payload);
  }
}

async function loadHistoryFromControls() {
  const sel = byId("historyAssetSelect");
  const compareEl = byId("historyCompareTotal");
  const benchmarkSel = byId("historyBenchmarkSelect");
  const investedEl = byId("historyShowInvested");
  const viewModeEl = byId("historyViewMode");
  if (!sel) return;
  saveHistoryPrefs();
  const benchmarks = benchmarkSel
    ? [...benchmarkSel.selectedOptions].map((o) => o.value).filter(Boolean)
    : [];
  await loadHistoryChart(sel.value, {
    compareTotal: !!(compareEl && compareEl.checked),
    rangeDays: _historyRangeDays(),
    benchmarks,
    showInvested: !(investedEl && investedEl.checked === false),
    viewMode: viewModeEl?.value === "base100" ? "base100" : "value",
  });
}

async function loadHistoryChart(assetId, options = {}) {
  const emptyEl = byId("historyEmpty");
  const canvas = byId("historyChart");
  if (!canvas) return;
  const isTotal = assetId === "__total__";
  const compareTotal = !!options.compareTotal;
  const rangeDays = Number(options.rangeDays || 180);
  const benchmarkKeys = Array.isArray(options.benchmarks)
    ? options.benchmarks.map((b) => String(b || "").trim().toLowerCase()).filter((b) => ["ibov", "cdi", "ipca"].includes(b))
    : [];
  const showInvested = options.showInvested !== false;
  const viewMode = options.viewMode === "base100" ? "base100" : "value";
  const limit = Math.min(3650, Math.max(1, rangeDays));

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
    if (benchmarkKeys.length) {
      reqs.push(Promise.all(benchmarkKeys.map((b) =>
        finFetch(`/api/finance/benchmark-history?benchmark=${encodeURIComponent(b)}&limit=${limit}`).then((r) => r.json())
      )));
    }

    const results = await Promise.all(reqs);
    let resultIdx = 0;
    const primaryData = results[resultIdx++] || [];
    const totalData = (!isTotal && compareTotal) ? (results[resultIdx++] || []) : [];
    const investedData = showInvested ? (results[resultIdx++] || []) : [];
    const benchmarkSeries = benchmarkKeys.length ? (results[resultIdx++] || []) : [];

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

    const built = await _buildHistoryChartData({
      isTotal,
      compareTotal,
      benchmarkKeys,
      showInvested,
      primaryData,
      totalData,
      investedData,
      benchmarkSeries,
    });
    const rawLabels = Array.isArray(built?.labels) ? built.labels : [];
    const rawDatasets = Array.isArray(built?.datasets) ? built.datasets : [];
    const firstBuyDate = _historyFirstBuyDate(assetId);
    const trimmed = _trimHistoryBeforeDate(rawLabels, rawDatasets, firstBuyDate);
    const transformed = _applyHistoryViewMode(trimmed.datasets, viewMode);
    const sampledMain = _downsampleHistory(trimmed.labels, transformed.datasets);
    const datasets = sampledMain.datasets;
    const chartLabels = sampledMain.labels;
    const usesBase100 = transformed.usesBase100;

    if (!chartLabels.length || !datasets.length) {
      if (FIN.charts.history) { FIN.charts.history.destroy(); FIN.charts.history = null; }
      canvas.style.display = "none";
      if (emptyEl) {
        emptyEl.style.display = "";
        emptyEl.textContent = "Sem dados suficientes para montar a evolução patrimonial neste período.";
      }
      return;
    }

    if (FIN.charts.history) FIN.charts.history.destroy();

    FIN.charts.history = new Chart(canvas, {
      type: "line",
      data: {
        labels: chartLabels,
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { intersect: false, mode: "index" },
        onClick: (_evt, elements, chart) => {
          if (!elements || !elements.length) return;
          const idx = elements[0].index;
          const selectedDate = chart?.data?.labels?.[idx];
          if (!selectedDate) return;
          drillDownTransactionsByDate(assetId, String(selectedDate));
        },
        plugins: {
          legend: { display: datasets.length > 1 },
          tooltip: {
            callbacks: {
              title: (items) => {
                const raw = String(items?.[0]?.label || "");
                if (!raw || raw.length < 10) return raw;
                const yyyy = raw.slice(0, 4);
                const mm = raw.slice(5, 7);
                const dd = raw.slice(8, 10);
                return `${dd}/${mm}/${yyyy}`;
              },
              label: (ctx) => {
                const raw = Number(ctx.raw || 0);
                const idx = Number(ctx.dataIndex || 0);
                const series = Array.isArray(ctx.dataset.data) ? ctx.dataset.data : [];
                let prev = null;
                for (let i = idx - 1; i >= 0; i -= 1) {
                  const n = Number(series[i]);
                  if (Number.isFinite(n)) {
                    prev = n;
                    break;
                  }
                }

                if (usesBase100) {
                  const delta = prev && prev !== 0 ? ((raw / prev) - 1) * 100 : null;
                  const deltaText = delta == null ? "" : ` | Δ ${formatPct(delta)}`;
                  return ` ${ctx.dataset.label}: ${formatNumber(raw, 2)} pts${deltaText}`;
                }

                if (ctx.dataset.yAxisID === "y1") {
                  return ` ${ctx.dataset.label}: ${formatPct(raw)}`;
                }
                const delta = prev && prev !== 0 ? ((raw / prev) - 1) * 100 : null;
                const deltaText = delta == null ? "" : ` | Δ ${formatPct(delta)}`;
                return ` ${ctx.dataset.label}: ${formatBRL(raw)}${deltaText}`;
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
            display: !usesBase100,
            grid: { color: "rgba(255,255,255,0.05)" },
            ticks: { color: "#8b92a5", font: { size: 10 }, callback: (v) => formatBRL(v) },
          },
          y1: {
            display: !usesBase100 && datasets.some((d) => d.yAxisID === "y1"),
            position: "right",
            grid: { drawOnChartArea: false },
            ticks: { color: "#f59e0b", font: { size: 10 }, callback: (v) => formatPct(v) },
          },
          yBase: {
            display: usesBase100,
            position: "right",
            grid: { color: "rgba(255,255,255,0.05)" },
            ticks: { color: "#8b92a5", font: { size: 10 }, callback: (v) => `${formatNumber(v, 1)} pts` },
          },
        },
      },
    });
  } catch (err) {
    console.error("History chart error:", err);
    if (emptyEl) {
      emptyEl.style.display = "";
      emptyEl.textContent = "Erro ao carregar histórico. Tente novamente em alguns segundos.";
    }
    canvas.style.display = "none";
  }
}

function drillDownTransactionsByDate(assetId, date) {
  if (!date) return;
  FIN._txFilter.dateFrom = date;
  FIN._txFilter.dateTo = date;
  if (assetId && assetId !== "__total__") {
    FIN._txFilter.asset = String(assetId);
  } else {
    FIN._txFilter.asset = "";
  }
  localStorage.setItem("fin_tx_filter", JSON.stringify(FIN._txFilter));
  renderTransactions(FIN.transactions || []);
  const txCard = byId("finTransactionsCard");
  if (txCard) txCard.scrollIntoView({ behavior: "smooth", block: "start" });
  showToast(`Drill-down aplicado: transações em ${date}`, "info", {
    actionLabel: "Limpar",
    onAction: () => {
      FIN._txFilter = { asset: "", type: "", dateFrom: "", dateTo: "", minTotal: "", maxTotal: "" };
      localStorage.removeItem("fin_tx_filter");
      renderTransactions(FIN.transactions || []);
    },
  });
}

function historySeriesMap(rows) {
  const map = new Map();
  for (const row of rows || []) {
    const date = String((row && row.captured_at) || "").slice(0, 10);
    if (!date) continue;
    map.set(date, Number((row && row.price) || 0));
  }
  return map;
}

function buildHistory(payload) {
  const {
    isTotal,
    compareTotal,
    benchmarkKeys,
    showInvested,
    primaryData,
    totalData,
    investedData,
    benchmarkSeries,
  } = payload || {};

  const primary = (primaryData || []).slice().reverse();
  const hasCompare = !isTotal && compareTotal && Array.isArray(totalData) && totalData.length > 0;

  let datasets = [];
  let labels = primary.map((d) => String((d && d.captured_at) || "").slice(0, 10));

  if (hasCompare) {
    const total = totalData.slice().reverse();
    const assetMap = historySeriesMap(primary);
    const totalMap = historySeriesMap(total);
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
    const prices = primary.map((d) => Number((d && d.price) || 0));
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

  if (Array.isArray(benchmarkKeys) && benchmarkKeys.length && Array.isArray(benchmarkSeries) && benchmarkSeries.length) {
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
        const d = String((row && row.captured_at) || "").slice(0, 10);
        if (!d) return;
        m.set(d, Number((row && row.normalized_pct) || 0));
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
    const invMap = historySeriesMap(investedData);
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

self.onmessage = (event) => {
  const msg = event && event.data ? event.data : {};
  if (msg.type !== "buildHistory") return;
  try {
    const payload = buildHistory(msg.payload || {});
    self.postMessage({ ok: true, payload });
  } catch (error) {
    self.postMessage({ ok: false, error: String((error && error.message) || error || "worker_error") });
  }
};

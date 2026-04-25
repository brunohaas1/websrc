/* ══════════════════════════════════════════════════════════
   Dividends Domain
   ══════════════════════════════════════════════════════════ */

const DIVIDENDS_CHART_PREFS_KEY = "fin_dividends_chart_prefs";

function renderDividends(divs) {
  const el = byId("finDividendsContent");
  const summaryEl = byId("finDividendSummary");
  if (!el) return;

  if (!divs.length) {
    el.innerHTML = renderEmptyState(
      "Nenhum dividendo registrado até agora.",
      "Registrar provento",
      "addDividend",
    );
    if (summaryEl) summaryEl.innerHTML = "";
    _destroyDividendCharts();
    return;
  }

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

  const currMonthVal = monthEntries.length ? Number(monthEntries[monthEntries.length - 1][1] || 0) : 0;
  const prevMonthVal = monthEntries.length > 1 ? Number(monthEntries[monthEntries.length - 2][1] || 0) : 0;
  const momPct = prevMonthVal > 0 ? ((currMonthVal / prevMonthVal) - 1) * 100 : null;

  const currentMonthKey = monthEntries.length ? String(monthEntries[monthEntries.length - 1][0] || "") : "";
  let yoyPct = null;
  if (currentMonthKey && currentMonthKey.length >= 7) {
    const yy = Number(currentMonthKey.slice(0, 4));
    const mm = currentMonthKey.slice(5, 7);
    const prevYearKey = `${yy - 1}-${mm}`;
    const prevYearVal = Number(monthTotals[prevYearKey] || 0);
    if (prevYearVal > 0) {
      yoyPct = ((currMonthVal / prevYearVal) - 1) * 100;
    }
  }

  const baselineAvg = last12.length ? (last12Total / last12.length) : averageMonth;
  const forecast3 = baselineAvg * 3;
  const forecast6 = baselineAvg * 6;
  const forecast12 = baselineAvg * 12;

  const typeLabels = { dividend: "Dividendos", jcp: "JCP", rendimento: "Rendimentos", bonus: "Bonificação" };
  if (summaryEl) {
    summaryEl.innerHTML = `
      <div class="fin-div-totals">
        <div class="fin-div-total-item fin-div-grand"><span>Total Geral</span><strong>${formatBRL(grandTotal)}</strong><em>${totalCount} lançamento(s)</em></div>
        <div class="fin-div-total-item"><span>Média Mensal</span><strong>${formatBRL(averageMonth)}</strong><em>${monthEntries.length || 0} mês(es)</em></div>
        <div class="fin-div-total-item"><span>Últimos 12 Meses</span><strong>${formatBRL(last12Total)}</strong><em>${last12.length || 0} competência(s)</em></div>
        <div class="fin-div-total-item"><span>MoM</span><strong class="${momPct == null ? "" : changeClass(momPct)}">${momPct == null ? "—" : formatPct(momPct)}</strong><em>mês atual vs anterior</em></div>
        <div class="fin-div-total-item"><span>YoY</span><strong class="${yoyPct == null ? "" : changeClass(yoyPct)}">${yoyPct == null ? "—" : formatPct(yoyPct)}</strong><em>mês atual vs ano anterior</em></div>
        <div class="fin-div-total-item"><span>Melhor Mês</span><strong>${bestMonth ? formatBRL(bestMonth[1]) : "—"}</strong><em>${bestMonth ? escapeHtml(bestMonth[0]) : "sem dados"}</em></div>
        <div class="fin-div-total-item"><span>Maior Pagador</span><strong>${bestAsset ? formatBRL(bestAsset[1]) : "—"}</strong><em>${bestAsset ? escapeHtml(bestAsset[0]) : "sem dados"}</em></div>
        <div class="fin-div-total-item"><span>Projeção 3m</span><strong>${formatBRL(forecast3)}</strong><em>base média recente</em></div>
        <div class="fin-div-total-item"><span>Projeção 6m</span><strong>${formatBRL(forecast6)}</strong><em>base média recente</em></div>
        <div class="fin-div-total-item"><span>Projeção 12m</span><strong>${formatBRL(forecast12)}</strong><em>base média recente</em></div>
        ${Object.entries(totals).map(([k, v]) =>
          `<div class="fin-div-total-item"><span>${typeLabels[k] || k}</span><strong>${formatBRL(v)}</strong></div>`
        ).join("")}
      </div>
    `;
  }

  el.innerHTML = `
    <div class="fin-div-table-toolbar">
      <div class="fin-div-table-caption">Nesta tela ficam apenas os gráficos e o resumo de proventos.</div>
      <a href="/finance/registros" class="btn-text">Abrir Registros</a>
    </div>
  `;

  const chartPrefs = getDividendsChartPrefs();
  applyDividendsChartControls(chartPrefs);
  bindDividendsChartControls();
  renderDividendsChart(divs, chartPrefs);
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

function getDividendsChartPrefs() {
  try {
    const raw = localStorage.getItem(DIVIDENDS_CHART_PREFS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    const showValues = parsed?.showValues !== false;
    const density = ["smart", "all", "sparse"].includes(parsed?.density) ? parsed.density : "smart";
    return { showValues, density };
  } catch {
    return { showValues: true, density: "smart" };
  }
}

function setDividendsChartPrefs(nextPrefs) {
  try {
    localStorage.setItem(DIVIDENDS_CHART_PREFS_KEY, JSON.stringify(nextPrefs));
  } catch {
    // ignore storage failures
  }
}

function applyDividendsChartControls(prefs) {
  const showValuesInput = byId("dividendsShowValues");
  const densitySelect = byId("dividendsLabelDensity");
  if (showValuesInput) showValuesInput.checked = prefs.showValues !== false;
  if (densitySelect) densitySelect.value = prefs.density || "smart";
}

function bindDividendsChartControls() {
  const showValuesInput = byId("dividendsShowValues");
  const densitySelect = byId("dividendsLabelDensity");
  if (showValuesInput && !showValuesInput.dataset.bound) {
    showValuesInput.dataset.bound = "1";
    showValuesInput.addEventListener("change", () => {
      const prefs = getDividendsChartPrefs();
      const next = { ...prefs, showValues: showValuesInput.checked };
      setDividendsChartPrefs(next);
      renderDividendsChart(FIN.dividends || [], next);
    });
  }
  if (densitySelect && !densitySelect.dataset.bound) {
    densitySelect.dataset.bound = "1";
    densitySelect.addEventListener("change", () => {
      const prefs = getDividendsChartPrefs();
      const next = { ...prefs, density: densitySelect.value || "smart" };
      setDividendsChartPrefs(next);
      renderDividendsChart(FIN.dividends || [], next);
    });
  }
}

function formatCompactBRL(value) {
  const num = Number(value || 0);
  const abs = Math.abs(num);
  if (abs >= 1000000) return `R$ ${(num / 1000000).toFixed(1)}M`;
  if (abs >= 1000) return `R$ ${(num / 1000).toFixed(1)}k`;
  return formatBRL(num);
}

function renderDividendsChart(divs, prefs = { showValues: true, density: "smart" }) {
  const canvas = byId("dividendsChart");
  if (!canvas || !window.Chart) return;

  const monthly = {};
  divs.forEach((d) => {
    const raw = d.pay_date || d.ex_date || d.created_at || "";
    const key = raw.slice(0, 7);
    if (!key) return;
    monthly[key] = (monthly[key] || 0) + (d.total_amount || 0);
  });

  const labels = Object.keys(monthly).sort();
  const data = labels.map((k) => monthly[k]);
  const maxVisibleLabels = prefs.density === "all" ? Number.POSITIVE_INFINITY : prefs.density === "sparse" ? 6 : 12;
  const step = maxVisibleLabels === Number.POSITIVE_INFINITY ? 1 : Math.max(1, Math.ceil(labels.length / maxVisibleLabels));
  const shouldCompactLabels = labels.length > 10;

  const barValueLabelsPlugin = {
    id: "barValueLabelsPlugin",
    afterDatasetsDraw(chart) {
      if (prefs.showValues === false) return;
      const { ctx } = chart;
      const dataset = chart.data.datasets[0];
      const meta = chart.getDatasetMeta(0);
      if (!dataset || !meta || !meta.data) return;

      ctx.save();
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.font = "700 11px Inter, sans-serif";
      ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--text") || "#e2e8f0";

      meta.data.forEach((bar, index) => {
        if (index % step !== 0 && index !== meta.data.length - 1) return;
        const value = dataset.data[index];
        if (!Number.isFinite(Number(value))) return;
        const label = shouldCompactLabels ? formatCompactBRL(value) : formatBRL(value);
        ctx.fillText(label, bar.x, bar.y - 6);
      });

      ctx.restore();
    },
  };

  if (FIN.charts.dividends) FIN.charts.dividends.destroy();

  FIN.charts.dividends = new Chart(canvas, {
    type: "bar",
    plugins: [barValueLabelsPlugin],
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
      onClick: (_evt, elements, chart) => {
        if (!elements || !elements.length) return;
        const idx = elements[0].index;
        const monthKey = chart?.data?.labels?.[idx];
        if (!monthKey) return;
        openDividendMonthDrilldown(String(monthKey), divs || []);
      },
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
        x: {
          ticks: {
            autoSkip: labels.length > 10,
            maxRotation: 0,
            callback: (_v, i) => {
              const raw = labels[i] || "";
              if (!raw) return raw;
              const yy = raw.slice(2, 4);
              const mm = raw.slice(5, 7);
              return `${mm}/${yy}`;
            },
          },
        },
        y: {
          beginAtZero: true,
          ticks: {
            callback: (v) => formatCompactBRL(v),
          },
        },
      },
    },
  });
}

function openDividendMonthDrilldown(monthKey, divs) {
  const filtered = (divs || []).filter((d) => {
    const raw = d.pay_date || d.ex_date || d.created_at || "";
    return String(raw).startsWith(monthKey);
  });
  const rows = filtered
    .sort((a, b) => String(b.pay_date || b.ex_date || "").localeCompare(String(a.pay_date || a.ex_date || "")))
    .map((d) => `
      <tr>
        <td>${escapeHtml(d.symbol || "—")}</td>
        <td>${escapeHtml(d.div_type || "dividend")}</td>
        <td>${escapeHtml(String(d.pay_date || d.ex_date || "").slice(0, 10))}</td>
        <td class="text-right mono">${formatNumber(d.quantity || 0)}</td>
        <td class="text-right mono">${formatBRL(d.total_amount || 0)}</td>
      </tr>
    `)
    .join("");
  const total = filtered.reduce((sum, d) => sum + Number(d.total_amount || 0), 0);
  openFinModal(`Drill-down de proventos: ${escapeHtml(monthKey)}`, `
    <p class="fin-empty" style="text-align:left;margin-bottom:8px;">${filtered.length} lançamento(s) • Total ${formatBRL(total)}</p>
    <div class="fin-table-wrap">
      <table class="fin-table">
        <thead>
          <tr><th>Ativo</th><th>Tipo</th><th>Data</th><th class="text-right">Qtd</th><th class="text-right">Total</th></tr>
        </thead>
        <tbody>${rows || '<tr><td colspan="5" class="fin-empty">Sem lançamentos.</td></tr>'}</tbody>
      </table>
    </div>
  `);
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

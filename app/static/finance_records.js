function byId(id) {
  return document.getElementById(id);
}

function finFetch(url, opts = {}) {
  const meta = document.querySelector('meta[name="finance-key"]');
  const key = meta ? meta.getAttribute("content") : "";
  if (key) {
    opts.headers = { ...(opts.headers || {}), "X-Finance-Key": key };
  }
  return fetch(url, opts);
}

async function fetchRecordsJson(url, fallbackValue = []) {
  try {
    const response = await finFetch(url);
    if (!response.ok) {
      console.warn("Records endpoint returned non-OK status", { url, status: response.status });
      return fallbackValue;
    }
    return await response.json();
  } catch (err) {
    console.warn("Records endpoint request failed", { url, err });
    return fallbackValue;
  }
}

function formatBRL(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function formatNumber(value, decimals = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("pt-BR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = String(text ?? "");
  return d.innerHTML;
}

function renderTransactions(list) {
  const el = byId("recordsTransactionsContent");
  if (!el) return;

  if (!Array.isArray(list) || !list.length) {
    el.innerHTML = '<p class="fin-empty">Nenhuma transação encontrada.</p>';
    return;
  }

  const rows = list.map((t) => {
    const txType = String(t.tx_type || "").toLowerCase();
    const typeClass = txType === "sell" ? "fin-badge-sell" : "fin-badge-buy";
    return `
      <tr>
        <td>${escapeHtml(String(t.tx_date || "").slice(0, 10))}</td>
        <td><strong>${escapeHtml(t.symbol || "—")}</strong></td>
        <td><span class="fin-badge ${typeClass}">${escapeHtml(txType || "buy")}</span></td>
        <td class="text-right mono">${formatNumber(t.quantity, 4)}</td>
        <td class="text-right mono">${formatBRL(t.price)}</td>
        <td class="text-right mono">${formatBRL(t.total)}</td>
        <td class="text-right mono">${formatBRL(t.fees || 0)}</td>
      </tr>
    `;
  }).join("");

  el.innerHTML = `
    <div class="fin-table-wrap">
      <table class="fin-table">
        <thead>
          <tr>
            <th>Data</th>
            <th>Ativo</th>
            <th>Tipo</th>
            <th class="text-right">Qtd</th>
            <th class="text-right">Preço</th>
            <th class="text-right">Total</th>
            <th class="text-right">Taxas</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderDividends(list) {
  const el = byId("recordsDividendsContent");
  if (!el) return;

  if (!Array.isArray(list) || !list.length) {
    el.innerHTML = '<p class="fin-empty">Nenhum provento encontrado.</p>';
    return;
  }

  const rows = list.map((d) => {
    const type = String(d.div_type || "dividend");
    const typeClass = type === "jcp" ? "fin-badge-sell" : "fin-badge-buy";
    return `
      <tr>
        <td>${escapeHtml(String(d.pay_date || d.ex_date || d.created_at || "").slice(0, 10))}</td>
        <td><strong>${escapeHtml(d.symbol || "—")}</strong></td>
        <td><span class="fin-badge ${typeClass}">${escapeHtml(type)}</span></td>
        <td class="text-right mono">${formatNumber(d.quantity, 4)}</td>
        <td class="text-right mono">${formatBRL(d.amount_per_share)}</td>
        <td class="text-right mono">${formatBRL(d.total_amount)}</td>
      </tr>
    `;
  }).join("");

  el.innerHTML = `
    <div class="fin-table-wrap">
      <table class="fin-table">
        <thead>
          <tr>
            <th>Pagamento</th>
            <th>Ativo</th>
            <th>Tipo</th>
            <th class="text-right">Qtd</th>
            <th class="text-right">$/ação</th>
            <th class="text-right">Total</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

async function loadRecords() {
  const txEl = byId("recordsTransactionsContent");
  const divEl = byId("recordsDividendsContent");
  if (txEl) txEl.innerHTML = '<p class="fin-empty">Carregando transações...</p>';
  if (divEl) divEl.innerHTML = '<p class="fin-empty">Carregando proventos...</p>';

  try {
    const [txData, divData] = await Promise.all([
      fetchRecordsJson("/api/finance/transactions?limit=500", []),
      fetchRecordsJson("/api/finance/dividends", []),
    ]);
    renderTransactions(Array.isArray(txData) ? txData : []);
    renderDividends(Array.isArray(divData) ? divData : []);
  } catch (err) {
    console.error("Records load error:", err);
    if (txEl) txEl.innerHTML = '<p class="fin-empty">Erro ao carregar transações.</p>';
    if (divEl) divEl.innerHTML = '<p class="fin-empty">Erro ao carregar proventos.</p>';
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const refreshBtn = byId("recordsRefreshBtn");
  if (refreshBtn) refreshBtn.addEventListener("click", loadRecords);
  loadRecords();
});

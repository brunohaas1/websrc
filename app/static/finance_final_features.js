/* ══════════════════════════════════════════════════════════
  Inline Editing + Validations + PDF Reports
  ══════════════════════════════════════════════════════════ */

// === INLINE EDITING ===

let finInlineEditState = {
  entryId: null,
  field: null,
  originalValue: null,
  editCell: null,
};

function enableInlineEditing() {
  const table = byId("finCashflowTable");
  if (!table) return;

  table.addEventListener("click", (e) => {
    const cell = e.target.closest("td");
    if (!cell || cell.querySelector("button")) return; // Skip if clicking buttons

    const row = cell.closest("tr");
    if (!row || !row.dataset.entryId) return;

    const entryId = Number(row.dataset.entryId);
    const entry = (FIN.cashflowEntries || []).find((x) => x.id === entryId);
    if (!entry) return;

    const colIndex = Array.from(row.children).indexOf(cell);
    const field = getFieldByColumnIndex(colIndex);

    if (!field || !isEditableField(field)) return;

    startInlineEdit(entryId, field, entry, cell);
  });

  // Keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") cancelInlineEdit();
    if (e.key === "Enter" && finInlineEditState.entryId) saveInlineEdit();
  });
}

function getFieldByColumnIndex(colIndex) {
  const fields = ["entry_date", "entry_type", "category", "description", "amount", "payment_status"];
  return fields[colIndex] || null;
}

function isEditableField(field) {
  return ["category", "description", "amount"].includes(field);
}

function startInlineEdit(entryId, field, entry, cell) {
  cancelInlineEdit(); // Cancel any existing edit

  finInlineEditState = {
    entryId: entryId,
    field: field,
    originalValue: entry[field],
    editCell: cell,
  };

  const value = entry[field] || "";
  let input;

  if (field === "amount") {
    input = document.createElement("input");
    input.type = "number";
    input.value = value;
    input.step = "0.01";
  } else if (field === "category") {
    input = document.createElement("select");
    const cats = FIN._cashflowCategories || [];
    input.innerHTML = cats.map((c) => `<option ${c === value ? "selected" : ""}>${escapeHtml(c)}</option>`).join("");
  } else {
    input = document.createElement("input");
    input.type = "text";
    input.value = value;
  }

  input.style.width = "100%";
  input.style.padding = "4px";
  input.style.border = "1px solid #3b82f6";
  input.style.borderRadius = "4px";
  input.style.background = "rgba(0,0,0,0.5)";
  input.style.color = "#fff";

  cell.innerHTML = "";
  cell.appendChild(input);
  input.focus();
  input.select?.();

  // Auto-save on blur
  input.addEventListener("blur", saveInlineEdit);
}

async function saveInlineEdit() {
  if (!finInlineEditState.entryId) return;

  const { entryId, field, originalValue, editCell } = finInlineEditState;
  const input = editCell?.querySelector("input, select");
  if (!input) return;

  const newValue = input.value;

  if (newValue === originalValue) {
    cancelInlineEdit();
    renderCashflow(FIN.cashflowEntries);
    return;
  }

  // Validate before submitting
  const validation = validateFieldValue(field, newValue);
  if (!validation.valid) {
    showToast(`❌ ${validation.message}`);
    return;
  }

  try {
    const payload = { [field]: newValue };
    const resp = await finFetch(`/api/finance/cashflow/${entryId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      showToast("Erro ao atualizar");
      return;
    }

    showToast("✓ Atualizado!", "success");
    finInlineEditState = { entryId: null, field: null };
    renderCashflow(FIN.cashflowEntries);
  } catch {
    showToast("Erro ao salvar");
  }
}

function cancelInlineEdit() {
  const { editCell, entryId } = finInlineEditState;
  if (editCell && entryId) {
    const entry = (FIN.cashflowEntries || []).find((x) => x.id === entryId);
    if (entry) {
      editCell.innerHTML = escapeHtml(String(entry[finInlineEditState.field] || ""));
    }
  }
  finInlineEditState = { entryId: null, field: null };
}

// === VALIDATIONS ===

function validateFieldValue(field, value) {
  if (field === "amount") {
    const num = parseFloat(value);
    if (isNaN(num) || num <= 0) return { valid: false, message: "Valor deve ser positivo" };
    if (num > 999999999) return { valid: false, message: "Valor muito alto" };
    return { valid: true };
  }

  if (field === "category") {
    if (!value || value.length === 0) return { valid: false, message: "Categoria obrigatória" };
    if (value.length > 60) return { valid: false, message: "Categoria muito longa" };
    return { valid: true };
  }

  if (field === "description") {
    if (value.length > 200) return { valid: false, message: "Descrição muito longa (máx 200)" };
    return { valid: true };
  }

  return { valid: true };
}

function checkForDuplicates(entry) {
  const similar = (FIN.cashflowEntries || []).filter(
    (e) => e.id !== entry.id && e.amount === entry.amount && e.entry_date === entry.entry_date && e.description === entry.description
  );

  if (similar.length > 0) {
    return {
      isDuplicate: true,
      message: `⚠️ ${similar.length} lançamento(s) similar(es) encontrado(s)`,
      entries: similar,
    };
  }

  return { isDuplicate: false };
}

// === PDF REPORTS ===

async function generatePDFReport() {
  const month = FIN.cashflowMonth || new Date().toISOString().slice(0, 7);
  const entries = FIN.cashflowEntries || [];
  const analytics = FIN.cashflowAnalytics || {};

  try {
    // Request PDF from server
    const resp = await finFetch(`/api/finance/report/pdf?month=${month}`, {
      headers: { Accept: "application/pdf" },
    });

    if (!resp.ok) throw new Error("PDF generation failed");

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);

    // Auto-download
    const a = document.createElement("a");
    a.href = url;
    a.download = `relatorio-financeiro-${month}.pdf`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast("✓ Relatório gerado!", "success");
  } catch {
    showToast("Erro ao gerar PDF");
  }
}

function openPDFReportModal() {
  openFinModal("📄 Gerar Relatório PDF", `
    <form data-form-action="submitPDFReport">
      <div class="fin-form-group">
        <label>Período</label>
        <input id="fmReportMonth" type="month" required />
      </div>
      <div class="fin-form-group">
        <label style="display:flex;gap:8px;align-items:center;">
          <input id="fmReportIncludeCharts" type="checkbox" checked />
          <span>Incluir gráficos</span>
        </label>
      </div>
      <div class="fin-form-group">
        <label style="display:flex;gap:8px;align-items:center;">
          <input id="fmReportIncludeAnalytics" type="checkbox" checked />
          <span>Incluir análises</span>
        </label>
      </div>
      <button type="submit" class="fin-form-submit">Gerar PDF</button>
    </form>
  `);

  // Set default month
  const today = new Date();
  byId("fmReportMonth").value = today.toISOString().slice(0, 7);
}

async function submitPDFReport(e) {
  e.preventDefault();
  const month = byId("fmReportMonth")?.value;
  const includeCharts = byId("fmReportIncludeCharts")?.checked || false;
  const includeAnalytics = byId("fmReportIncludeAnalytics")?.checked || false;

  if (!month) {
    showToast("Selecione um período");
    return;
  }

  try {
    const params = new URLSearchParams({ month, includeCharts, includeAnalytics });
    const resp = await finFetch(`/api/finance/report/pdf?${params.toString()}`, {
      headers: { Accept: "application/pdf" },
    });

    if (!resp.ok) throw new Error("Failed");

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `financeiro-${month}.pdf`;
    a.click();
    URL.revokeObjectURL(url);

    showToast("✓ PDF gerado e baixado!", "success");
    closeFinModal();
  } catch {
    showToast("Erro ao gerar PDF");
  }
}

// === EXPORT TO EXCEL ===

function exportToExcel() {
  const entries = FIN.cashflowEntries || [];
  const headers = ["Data", "Tipo", "Categoria", "Subcategoria", "Descrição", "Valor", "Status Pagamento"];

  let csv = headers.join(",") + "\n";

  entries.forEach((e) => {
    const row = [
      e.entry_date,
      e.entry_type === "income" ? "Receita" : "Despesa",
      escapeHtml(e.category || ""),
      escapeHtml(e.subcategory || ""),
      escapeHtml(e.description || "").replace(/,/g, ";"),
      e.amount,
      e.payment_status === "paid" ? "Pago" : "Pendente",
    ];
    csv += row.map((v) => `"${v}"`).join(",") + "\n";
  });

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);

  link.setAttribute("href", url);
  link.setAttribute("download", `cashflow-${new Date().toISOString().slice(0, 7)}.csv`);
  link.click();

  showToast("✓ Exportado para CSV!", "success");
}

// === INTEGRATION WITH MAIN LOGIC ===

// Enable inline editing when cashflow renders
const originalRenderCashflow = window.renderCashflow;
window.renderCashflow = function (entries) {
  originalRenderCashflow.call(this, entries);
  setTimeout(() => enableInlineEditing(), 100);
};

// Add PDF and export buttons to toolbar
function addReportButtons() {
  const btnGroup = document.querySelector(".fin-cashflow-toolbar");
  if (!btnGroup) return;

  const pdfBtn = document.createElement("button");
  pdfBtn.className = "btn-small";
  pdfBtn.textContent = "📄 PDF";
  pdfBtn.onclick = openPDFReportModal;

  const excelBtn = document.createElement("button");
  excelBtn.className = "btn-small";
  excelBtn.textContent = "📊 Excel";
  excelBtn.onclick = exportToExcel;

  btnGroup.appendChild(pdfBtn);
  btnGroup.appendChild(excelBtn);
}

console.log("✓ Inline editing, validations, PDF reports loaded");

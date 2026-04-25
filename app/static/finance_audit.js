/* ══════════════════════════════════════════════════════════
   Finance Audit
   ══════════════════════════════════════════════════════════ */

function renderAuditTrail(entries) {
  const el = byId("finAuditContent");
  if (!el) return;
  FIN.auditEntries = Array.isArray(entries) ? entries : [];
  const filter = String(byId("auditActionFilter")?.value || "").toLowerCase();
  const visible = !filter
    ? FIN.auditEntries
    : FIN.auditEntries.filter((e) => String(e.action || "").toLowerCase().includes(filter));
  if (!visible.length) {
    el.innerHTML = '<p class="fin-empty">Sem eventos recentes.</p>';
    return;
  }
  el.innerHTML = visible.map((e) => {
    const ts = String(e.created_at || "").replace("T", " ").slice(0, 19);
    const payload = e && typeof e.payload === "object" && e.payload ? e.payload : {};
    const meta = payload._meta && typeof payload._meta === "object" ? payload._meta : {};
    const severity = /cleanup|delete|batch_update|settings_update/.test(String(e.action || "").toLowerCase())
      ? "high"
      : "normal";
    const detailRows = [];
    if (meta.ip) detailRows.push(`<span>IP: ${escapeHtml(meta.ip)}</span>`);
    if (meta.method || meta.path) {
      detailRows.push(`<span>Req: ${escapeHtml(String(meta.method || "").toUpperCase())} ${escapeHtml(meta.path || "")}</span>`);
    }
    const summaryKeys = Object.keys(payload).filter((k) => k !== "_meta").slice(0, 4);
    if (summaryKeys.length) {
      const summary = summaryKeys.map((k) => `${k}=${JSON.stringify(payload[k])}`).join(" • ");
      detailRows.push(`<span class="fin-audit-payload">${escapeHtml(summary)}</span>`);
    }
    return `
      <div class="fin-audit-item fin-audit-${severity}">
        <span class="fin-audit-time">${escapeHtml(ts)}</span>
        <span class="fin-audit-action">${escapeHtml(e.action || "")}</span>
        <span class="fin-audit-target">${escapeHtml(e.target_type || "")} #${escapeHtml(String(e.target_id || "-"))}</span>
        <div class="fin-audit-details">${detailRows.join("")}</div>
      </div>
    `;
  }).join("");
}

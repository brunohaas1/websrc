/* ══════════════════════════════════════════════════════════
   Finance AI Domain
   ══════════════════════════════════════════════════════════ */

async function requestAIAnalysis(type) {
  const el = byId("finAIContent");
  if (!el) return;

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

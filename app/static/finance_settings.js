const FIN_ALERT_PREFS_KEY = "fin_alert_prefs_v1";
const finSettingsById = (id) => document.getElementById(id);

function getAlertPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(FIN_ALERT_PREFS_KEY) || "{}");
    return {
      watchlistCooldownMinutes: Math.max(1, Number(raw.watchlistCooldownMinutes || 60)),
      goalMilestonesEnabled: raw.goalMilestonesEnabled !== false,
      dividendMinIncrease: Math.max(0, Number(raw.dividendMinIncrease || 1)),
      notifyWatchlistDesktop: raw.notifyWatchlistDesktop !== false,
      notifyGoalsDesktop: raw.notifyGoalsDesktop !== false,
      notifyDividendsDesktop: raw.notifyDividendsDesktop === true,
    };
  } catch {
    return {
      watchlistCooldownMinutes: 60,
      goalMilestonesEnabled: true,
      dividendMinIncrease: 1,
      notifyWatchlistDesktop: true,
      notifyGoalsDesktop: true,
      notifyDividendsDesktop: false,
    };
  }
}

function setAlertPrefs(next) {
  const current = getAlertPrefs();
  const merged = { ...current, ...(next || {}) };
  localStorage.setItem(FIN_ALERT_PREFS_KEY, JSON.stringify(merged));
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

    const historyPrefs = readHistoryPrefs();
    const divPrefs = getDividendsChartPrefs();
    const alertPrefs = getAlertPrefs();
    const autoRefresh = localStorage.getItem("fin_auto_refresh") ?? "300";

    openFinModal("Configurações Financeiras", `
      <form data-form-action="submitFinanceSettings">
        <div class="fin-form-group">
          <label>Ativar IA Local</label>
          <select id="finSetAiEnabled">
            <option value="1" ${String(data.ai_local_enabled) === "1" ? "selected" : ""}>Sim</option>
            <option value="0" ${String(data.ai_local_enabled) === "0" ? "selected" : ""}>Não</option>
          </select>
        </div>

        <div class="fin-form-group">
          <label>Timeout IA (segundos)</label>
          <input type="number" id="finSetAiTimeout" min="5" max="180" value="${escapeHtml(data.ai_local_timeout_seconds || "45")}" />
        </div>

        <div class="fin-form-group">
          <label>Token BRAPI (opcional)</label>
          <input type="password" id="finSetBrapiToken" placeholder="Cole seu token BRAPI" />
        </div>

        <div class="fin-form-group">
          <label>Chave da API Financeira (X-Finance-Key)</label>
          <input type="password" id="finSetFinanceApiKey" placeholder="Defina/atualize a chave de proteção" />
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

        <hr style="margin:16px 0;border-color:var(--fin-border,#333)">
        <p class="fin-empty" style="text-align:left;margin-bottom:10px;font-weight:600">🎛 Preferências de visualização</p>
        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>Período padrão (Histórico)</label>
            <select id="finPrefHistoryPeriod">
              <option value="30" ${String(historyPrefs.period) === "30" ? "selected" : ""}>30 dias</option>
              <option value="90" ${String(historyPrefs.period) === "90" ? "selected" : ""}>90 dias</option>
              <option value="180" ${String(historyPrefs.period) === "180" ? "selected" : ""}>6 meses</option>
              <option value="365" ${String(historyPrefs.period) === "365" ? "selected" : ""}>1 ano</option>
            </select>
          </div>
          <div class="fin-form-group">
            <label>Densidade padrão (Proventos)</label>
            <select id="finPrefDivDensity">
              <option value="smart" ${String(divPrefs.density) === "smart" ? "selected" : ""}>Inteligente</option>
              <option value="all" ${String(divPrefs.density) === "all" ? "selected" : ""}>Todos</option>
              <option value="sparse" ${String(divPrefs.density) === "sparse" ? "selected" : ""}>Reduzida</option>
            </select>
          </div>
        </div>

        <div class="fin-form-group">
          <label>Auto-refresh padrão</label>
          <select id="finPrefAutoRefresh">
            <option value="0" ${autoRefresh === "0" ? "selected" : ""}>Manual</option>
            <option value="60" ${autoRefresh === "60" ? "selected" : ""}>1 min</option>
            <option value="300" ${autoRefresh === "300" ? "selected" : ""}>5 min</option>
            <option value="600" ${autoRefresh === "600" ? "selected" : ""}>10 min</option>
            <option value="1800" ${autoRefresh === "1800" ? "selected" : ""}>30 min</option>
          </select>
        </div>

        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>Cooldown alertas watchlist (min)</label>
            <input type="number" id="finPrefWatchlistCooldown" min="1" max="1440" value="${escapeHtml(alertPrefs.watchlistCooldownMinutes || 60)}" />
          </div>
          <div class="fin-form-group">
            <label>Aumento mínimo proventos (R$)</label>
            <input type="number" id="finPrefDividendMinIncrease" min="0" step="0.01" value="${escapeHtml(alertPrefs.dividendMinIncrease || 1)}" />
          </div>
        </div>

        <div class="fin-form-group">
          <label>Alertas de marcos de metas</label>
          <select id="finPrefGoalMilestonesEnabled">
            <option value="1" ${alertPrefs.goalMilestonesEnabled ? "selected" : ""}>Ativado</option>
            <option value="0" ${!alertPrefs.goalMilestonesEnabled ? "selected" : ""}>Desativado</option>
          </select>
        </div>

        <div class="fin-form-row">
          <div class="fin-form-group">
            <label>Notificações desktop (Watchlist)</label>
            <select id="finPrefNotifyWatchlistDesktop">
              <option value="1" ${alertPrefs.notifyWatchlistDesktop ? "selected" : ""}>Ativado</option>
              <option value="0" ${!alertPrefs.notifyWatchlistDesktop ? "selected" : ""}>Desativado</option>
            </select>
          </div>
          <div class="fin-form-group">
            <label>Notificações desktop (Metas)</label>
            <select id="finPrefNotifyGoalsDesktop">
              <option value="1" ${alertPrefs.notifyGoalsDesktop ? "selected" : ""}>Ativado</option>
              <option value="0" ${!alertPrefs.notifyGoalsDesktop ? "selected" : ""}>Desativado</option>
            </select>
          </div>
        </div>

        <div class="fin-form-group">
          <label>Notificações desktop (Proventos)</label>
          <select id="finPrefNotifyDividendsDesktop">
            <option value="1" ${alertPrefs.notifyDividendsDesktop ? "selected" : ""}>Ativado</option>
            <option value="0" ${!alertPrefs.notifyDividendsDesktop ? "selected" : ""}>Desativado</option>
          </select>
        </div>

        <button type="submit" class="fin-form-submit">💾 Salvar configurações</button>
      </form>

      <hr style="margin:20px 0;border-color:var(--fin-border,#333)">
      <p class="fin-empty" style="text-align:left;margin-bottom:10px;font-weight:600">🔧 Manutenção</p>
      <p class="fin-empty" style="text-align:left;margin-bottom:12px;font-size:.85rem">
        Remove transações duplicadas do histórico (mantém o registro mais antigo de cada grupo idêntico) e recalcula o portfólio.
      </p>
      <button id="btnCleanupDuplicates" class="fin-form-submit" style="background:var(--fin-warn,#b45309);max-width:260px">
        🧹 Limpar transações duplicadas
      </button>
      <p id="cleanupResult" style="margin-top:8px;font-size:.85rem;display:none"></p>
    `);
  } catch {
    showToast("Erro de rede ao carregar configurações", "error");
  }

  finSettingsById("btnCleanupDuplicates")?.addEventListener("click", runCleanupDuplicates);
}

async function runCleanupDuplicates() {
  const btn = finSettingsById("btnCleanupDuplicates");
  const result = finSettingsById("cleanupResult");

  const accepted = window.prompt(
    "Confirma limpeza de duplicatas? Digite CONFIRM_CLEANUP_DUPLICATES para continuar.",
    "",
  );
  if (accepted !== "CONFIRM_CLEANUP_DUPLICATES") {
    showToast("Limpeza cancelada: confirmação inválida.", "warning");
    return;
  }

  const idemKey = (window.crypto && window.crypto.randomUUID)
    ? window.crypto.randomUUID()
    : `cleanup-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  if (btn) { btn.disabled = true; btn.textContent = "⏳ Processando…"; }
  try {
    const resp = await finFetch("/api/finance/maintenance/cleanup-duplicates", {
      method: "POST",
      headers: {
        "X-Cleanup-Confirm": "CONFIRM_CLEANUP_DUPLICATES",
        "X-Idempotency-Key": idemKey,
      },
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resp.status === 429 && data.retry_after_seconds) {
        showToast(`Cooldown ativo. Aguarde ${data.retry_after_seconds}s.`, "warning");
      } else {
        showToast(data.error || "Erro na limpeza", "error");
      }
    } else {
      const tx = data.transactions || {};
      const div = data.dividends || {};
      const msg = `✅ Transações: ${tx.scanned ?? 0} verificadas, ${tx.deleted ?? 0} removidas | Dividendos: ${div.scanned ?? 0} verificados, ${div.deleted ?? 0} removidos`;
      if (result) { result.textContent = msg; result.style.display = "block"; }
      showToast(msg, "success");
    }
  } catch {
    showToast("Erro de rede na limpeza", "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "🧹 Limpar transações duplicadas"; }
  }
}

async function submitFinanceSettings() {
  const payload = {
    ai_local_enabled: finSettingsById("finSetAiEnabled")?.value || "1",
    ai_local_timeout_seconds: finSettingsById("finSetAiTimeout")?.value || "45",
    ai_local_url: finSettingsById("finSetAiUrl")?.value?.trim() || "",
    ai_local_model: finSettingsById("finSetAiModel")?.value?.trim() || "",
    currency_api_url: finSettingsById("finSetCurrencyApi")?.value?.trim() || "",
    currency_update_minutes: finSettingsById("finSetCurrencyUpdate")?.value || "15",
  };

  const brapiToken = finSettingsById("finSetBrapiToken")?.value?.trim() || "";
  const financeApiKey = finSettingsById("finSetFinanceApiKey")?.value?.trim() || "";
  const prefHistoryPeriod = finSettingsById("finPrefHistoryPeriod")?.value || "180";
  const prefDivDensity = finSettingsById("finPrefDivDensity")?.value || "smart";
  const prefAutoRefresh = finSettingsById("finPrefAutoRefresh")?.value || "300";
  const prefWatchlistCooldown = Number(finSettingsById("finPrefWatchlistCooldown")?.value || 60);
  const prefDividendMinIncrease = Number(finSettingsById("finPrefDividendMinIncrease")?.value || 1);
  const prefGoalMilestonesEnabled = (finSettingsById("finPrefGoalMilestonesEnabled")?.value || "1") === "1";
  const prefNotifyWatchlistDesktop = (finSettingsById("finPrefNotifyWatchlistDesktop")?.value || "1") === "1";
  const prefNotifyGoalsDesktop = (finSettingsById("finPrefNotifyGoalsDesktop")?.value || "1") === "1";
  const prefNotifyDividendsDesktop = (finSettingsById("finPrefNotifyDividendsDesktop")?.value || "0") === "1";
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

    // Persist local visualization defaults
    const historyPrefs = readHistoryPrefs();
    localStorage.setItem(HISTORY_PREFS_KEY, JSON.stringify({
      ...historyPrefs,
      period: prefHistoryPeriod,
    }));

    const divPrefs = getDividendsChartPrefs();
    setDividendsChartPrefs({
      ...divPrefs,
      density: ["smart", "all", "sparse"].includes(prefDivDensity) ? prefDivDensity : "smart",
    });

    localStorage.setItem("fin_auto_refresh", prefAutoRefresh);
    const autoSel = finSettingsById("autoRefreshSelect");
    if (autoSel) autoSel.value = prefAutoRefresh;
    _startAutoRefresh(Number(prefAutoRefresh));

    setAlertPrefs({
      watchlistCooldownMinutes: Math.max(1, prefWatchlistCooldown),
      dividendMinIncrease: Math.max(0, prefDividendMinIncrease),
      goalMilestonesEnabled: prefGoalMilestonesEnabled,
      notifyWatchlistDesktop: prefNotifyWatchlistDesktop,
      notifyGoalsDesktop: prefNotifyGoalsDesktop,
      notifyDividendsDesktop: prefNotifyDividendsDesktop,
    });

    showToast("Configurações salvas com sucesso!", "success");
    closeFinModal();
    applyHistoryPrefs();
    loadHistoryFromControls();
    renderDividends(FIN.dividends || []);
    loadAll();
  } catch {
    showToast("Erro de rede ao salvar configurações", "error");
  }
}

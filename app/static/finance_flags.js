/* ══════════════════════════════════════════════════════════
   Finance Feature Flags
   ══════════════════════════════════════════════════════════ */

const FIN_FLAGS_STORAGE_KEY = "fin_feature_flags";
const FIN_FLAGS_DEFAULT = {
  a11yEnhancements: true,
  keyboardShortcuts: true,
  sectionQuickNav: true,
  featureFlagsUI: true,
  perfTelemetry: true,
  lazyRebalanceLoad: true,
  secondaryPanelCache: true,
};

const FIN_FLAG_LABELS = {
  a11yEnhancements: "Melhorias de acessibilidade",
  keyboardShortcuts: "Atalhos globais de teclado",
  sectionQuickNav: "Navegação por seções (Alt+1..9)",
  featureFlagsUI: "Painel de feature flags",
  perfTelemetry: "Métricas de performance no carregamento",
  lazyRebalanceLoad: "Lazy load de rebalanceamento/projeção",
  secondaryPanelCache: "Cache dos painéis secundários no auto-refresh",
};

function _readFinFlagsFromMeta() {
  const meta = document.querySelector('meta[name="finance-flags"]');
  const raw = meta ? String(meta.getAttribute("content") || "").trim() : "";
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function _readFinFlagsFromStorage() {
  try {
    const raw = localStorage.getItem(FIN_FLAGS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function resolveFinanceFlags() {
  const metaFlags = _readFinFlagsFromMeta();
  const storedFlags = _readFinFlagsFromStorage();
  // Server rollout has precedence over local storage to keep behavior deterministic.
  const merged = { ...FIN_FLAGS_DEFAULT, ...storedFlags, ...metaFlags };
  return Object.fromEntries(Object.entries(merged).map(([k, v]) => [k, Boolean(v)]));
}

function isFinFlagOn(flagName) {
  if (!flagName) return false;
  if (!FIN.flags || typeof FIN.flags !== "object") return Boolean(FIN_FLAGS_DEFAULT[flagName]);
  if (Object.prototype.hasOwnProperty.call(FIN.flags, flagName)) return Boolean(FIN.flags[flagName]);
  return Boolean(FIN_FLAGS_DEFAULT[flagName]);
}

function openFeatureFlagsModal() {
  const rows = Object.keys(FIN_FLAGS_DEFAULT).map((key) => `
    <label class="fin-shortcut-row" style="justify-content:space-between;gap:14px;align-items:center;">
      <span>${escapeHtml(FIN_FLAG_LABELS[key] || key)}</span>
      <input type="checkbox" class="fin-flag-check" data-flag="${key}" ${isFinFlagOn(key) ? "checked" : ""} />
    </label>
  `).join("");

  openFinModal("Feature Flags", `
    <form id="finFeatureFlagsForm">
      <p class="fin-empty" style="text-align:left;margin-bottom:10px;">Controle de recursos por ambiente. Alterações são salvas no navegador atual.</p>
      <div class="fin-shortcuts-list">${rows}</div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
        <button type="button" id="finFlagsReset" class="btn-text">Restaurar padrão</button>
        <button type="submit" class="fin-form-submit">Salvar e aplicar</button>
      </div>
    </form>
  `);

  const form = byId("finFeatureFlagsForm");
  const resetBtn = byId("finFlagsReset");

  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      localStorage.removeItem(FIN_FLAGS_STORAGE_KEY);
      closeFinModal();
      showToast("Feature flags restauradas para o padrão.", "success");
      window.location.reload();
    });
  }

  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const nextFlags = { ...FIN_FLAGS_DEFAULT };
      form.querySelectorAll(".fin-flag-check[data-flag]").forEach((el) => {
        nextFlags[el.dataset.flag] = el.checked;
      });
      localStorage.setItem(FIN_FLAGS_STORAGE_KEY, JSON.stringify(nextFlags));
      closeFinModal();
      showToast("Feature flags atualizadas. Recarregando...", "info");
      window.location.reload();
    });
  }
}

/* ══════════════════════════════════════════════════════════
   Finance Shared Utilities
   ══════════════════════════════════════════════════════════ */

function initFinancePWA() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js").catch(() => {
      // ignore registration failures on unsupported contexts
    });
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    _deferredInstallPrompt = e;
    showToast("App instalavel disponivel", "info", {
      actionLabel: "Instalar",
      onAction: async () => {
        if (!_deferredInstallPrompt) return;
        _deferredInstallPrompt.prompt();
        try {
          await _deferredInstallPrompt.userChoice;
        } catch {
          // ignore
        }
        _deferredInstallPrompt = null;
      },
      timeout: 8000,
    });
  });
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = String(text ?? "");
  return d.innerHTML;
}

function formatBRL(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function formatPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const sign = Number(value) >= 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

function formatNumber(value, decimals = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("pt-BR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function changeClass(value) {
  if (value == null || Number.isNaN(Number(value))) return "";
  return Number(value) >= 0 ? "fin-up" : "fin-down";
}

function finFetch(url, opts = {}) {
  const meta = document.querySelector('meta[name="finance-key"]');
  const key = meta ? meta.getAttribute("content") : "";
  if (key) {
    opts.headers = { ...(opts.headers || {}), "X-Finance-Key": key };
  }
  return fetch(url, opts);
}

async function fetchFinanceJson(url, fallbackValue) {
  try {
    const response = await finFetch(url);
    if (!response.ok) {
      console.warn("Finance endpoint returned non-OK status", { url, status: response.status });
      return fallbackValue;
    }
    const contentType = String(response.headers.get("content-type") || "").toLowerCase();
    if (!contentType.includes("application/json")) {
      console.warn("Finance endpoint returned non-JSON response", {
        url,
        status: response.status,
        contentType,
      });
      return fallbackValue;
    }
    return await response.json();
  } catch (err) {
    console.warn("Finance endpoint request failed", { url, err });
    return fallbackValue;
  }
}

async function fetchWidgetJsonCached(key, url, fallbackValue, options = {}) {
  const useCache = options.useCache === true;
  const now = Date.now();
  const cached = FIN._widgetCache && FIN._widgetCache[key];
  if (useCache && cached && (now - cached.ts) < WIDGET_CACHE_TTL_MS) {
    return cached.data;
  }
  const data = await fetchFinanceJson(url, fallbackValue);
  if (FIN._widgetCache) {
    FIN._widgetCache[key] = { ts: now, data };
  }
  return data;
}

function badgeClass(type) {
  const map = {
    stock: "fin-badge-stock",
    crypto: "fin-badge-crypto",
    fii: "fin-badge-fii",
    etf: "fin-badge-etf",
    fund: "fin-badge-fund",
    "renda-fixa": "fin-badge-renda-fixa",
  };
  return map[type] || "fin-badge-stock";
}

function applyFinanceTheme(theme) {
  const nextTheme = FIN_THEME_ORDER.includes(theme) ? theme : "dark";
  document.body.classList.remove("light", "theme-ocean", "theme-sunset");
  if (nextTheme === "light") {
    document.body.classList.add("light");
  } else if (nextTheme === "ocean") {
    document.body.classList.add("theme-ocean");
  } else if (nextTheme === "sunset") {
    document.body.classList.add("theme-sunset");
  }
  localStorage.setItem(FIN_THEME_KEY, nextTheme);

  const btn = byId("themeToggle");
  if (btn) {
    const glyphMap = { dark: "◐", light: "◑", ocean: "◒", sunset: "◓" };
    btn.innerHTML = `<span class="btn-glyph" aria-hidden="true">${glyphMap[nextTheme] || "◐"}</span><span>Tema</span>`;
    btn.title = `Tema atual: ${nextTheme}`;
    btn.setAttribute("aria-label", `Tema atual: ${nextTheme}`);
  }
}

function applyFinanceDensity(density) {
  const next = density === "compact" ? "compact" : "comfortable";
  document.body.classList.remove("fin-density-compact", "fin-density-comfortable");
  document.body.classList.add(next === "compact" ? "fin-density-compact" : "fin-density-comfortable");
  localStorage.setItem(FIN_DENSITY_KEY, next);
  const btn = byId("btnDensity");
  if (btn) {
    btn.innerHTML = next === "compact"
      ? '<span class="btn-glyph" aria-hidden="true">▤</span><span>Compacto</span>'
      : '<span class="btn-glyph" aria-hidden="true">▥</span><span>Conforto</span>';
  }
}

function initDensityMode() {
  const saved = localStorage.getItem(FIN_DENSITY_KEY) || "comfortable";
  applyFinanceDensity(saved);
  const btn = byId("btnDensity");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const current = localStorage.getItem(FIN_DENSITY_KEY) || "comfortable";
    const next = current === "compact" ? "comfortable" : "compact";
    applyFinanceDensity(next);
    showToast(`Densidade: ${next === "compact" ? "compacta" : "confortável"}`, "info");
  });
}

function initTheme() {
  const saved = localStorage.getItem(FIN_THEME_KEY) || "dark";
  applyFinanceTheme(saved);
  const btn = byId("themeToggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const current = localStorage.getItem(FIN_THEME_KEY) || "dark";
      const idx = FIN_THEME_ORDER.indexOf(current);
      const next = FIN_THEME_ORDER[(idx + 1) % FIN_THEME_ORDER.length];
      applyFinanceTheme(next);
      showToast(`Tema alterado: ${next}`, "info");
    });
  }
}

function initFinanceKeyboardShortcuts() {
  if (!isFinFlagOn("keyboardShortcuts")) return;
  document.addEventListener("keydown", (e) => {
    const tag = document.activeElement && document.activeElement.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    const overlay = byId("finModalOverlay");
    if (overlay && overlay.style.display !== "none") return;

    const ctrl = e.ctrlKey || e.metaKey;

    if (ctrl && e.key === "r") { e.preventDefault(); loadAll(); showToast("Atualizando dados...", "info"); return; }
    if (ctrl && e.key === "i") { e.preventDefault(); openImportModal(); return; }
    if (ctrl && e.key === "e") { e.preventDefault(); openExportModal(); return; }
    if (e.key === "?") { showKeyboardShortcutsHelp(); return; }
    if (e.key === "Escape") { closeFinModal(); return; }
  });
}

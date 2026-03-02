const state = {
  snapshot: null,
  query: "",
  jobFilter: "",
  newsTopic: "",
  aiCategory: "",
  sortMode: "recency",
  theme: localStorage.getItem("dashboard-theme") || "dark",
  locale: localStorage.getItem("dashboard-locale") || "pt-BR",
  favoriteIds: new Set(),
  savedFilters: [],
  offlineQueue: JSON.parse(localStorage.getItem("offline-queue") || "[]"),
};

const CARD_ORDER_KEY = "dashboard-card-order-v2";
const COLLAPSED_KEY = "dashboard-collapsed-cards-v1";

/* ── Toast notification system ────────────────────────── */

function getOrCreateToastContainer() {
  let container = document.getElementById("toastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "toastContainer";
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  return container;
}

function showToast(message, type = "info", durationMs = 3500) {
  const container = getOrCreateToastContainer();
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  const icons = { success: "✓", error: "✕", info: "ℹ", warning: "⚠" };
  toast.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span class="toast-msg">${escapeHtml(message)}</span>`;

  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast-visible"));

  const timer = setTimeout(() => dismissToast(toast), durationMs);
  toast.addEventListener("click", () => { clearTimeout(timer); dismissToast(toast); });
}

function dismissToast(toast) {
  toast.classList.remove("toast-visible");
  toast.classList.add("toast-exit");
  toast.addEventListener("animationend", () => toast.remove(), { once: true });
  setTimeout(() => toast.remove(), 400);
}

/* ── Relative time (há X min) ─────────────────────────── */

function timeAgo(dateValue) {
  if (!dateValue) return "sem data";
  const date = new Date(dateValue);
  if (Number.isNaN(date.getTime())) return String(dateValue);

  const now = Date.now();
  const diffMs = now - date.getTime();
  if (diffMs < 0) return "agora";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return "agora";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `há ${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `há ${days}d`;
  if (days < 30) return `há ${Math.floor(days / 7)} sem`;
  return date.toLocaleDateString("pt-BR");
}

/* ── Theme toggle ─────────────────────────────────────── */

function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("dashboard-theme", theme);
  const btn = byId("themeToggle");
  if (btn) btn.textContent = theme === "dark" ? "☀️" : "🌙";
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "dark" ? "#050a15" : "#f0f2f5";
}

function toggleTheme() {
  applyTheme(state.theme === "dark" ? "light" : "dark");
}

/* ── Card collapse ────────────────────────────────────── */

function getCollapsedCards() {
  try { return JSON.parse(localStorage.getItem(COLLAPSED_KEY) || "[]"); } catch { return []; }
}

function setCollapsedCards(ids) {
  localStorage.setItem(COLLAPSED_KEY, JSON.stringify(ids));
}

function toggleCardCollapse(cardId) {
  const card = document.querySelector(`.card[data-card-id="${cardId}"]`);
  if (!card) return;
  const collapsed = getCollapsedCards();
  const isCollapsed = collapsed.includes(cardId);

  if (isCollapsed) {
    card.classList.remove("collapsed");
    setCollapsedCards(collapsed.filter((id) => id !== cardId));
  } else {
    card.classList.add("collapsed");
    setCollapsedCards([...collapsed, cardId]);
  }
}

function applySavedCollapseState() {
  const collapsed = getCollapsedCards();
  collapsed.forEach((cardId) => {
    const card = document.querySelector(`.card[data-card-id="${cardId}"]`);
    if (card) card.classList.add("collapsed");
  });
}

function injectCardControls() {
  document.querySelectorAll(".card[data-card-id]").forEach((card) => {
    if (card.querySelector(".card-collapse-btn")) return;
    const btn = document.createElement("button");
    btn.className = "card-collapse-btn";
    btn.title = "Minimizar / Expandir";
    btn.textContent = "−";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleCardCollapse(card.dataset.cardId);
      btn.textContent = card.classList.contains("collapsed") ? "+" : "−";
    });
    card.prepend(btn);
  });
  // Fix button label for already-collapsed
  getCollapsedCards().forEach((cardId) => {
    const card = document.querySelector(`.card[data-card-id="${cardId}"]`);
    const btn = card?.querySelector(".card-collapse-btn");
    if (btn) btn.textContent = "+";
  });
}
const CARD_HEIGHT_KEY = "dashboard-card-height-v2";
const CARD_SPAN_KEY = "dashboard-card-span-v1";
const CARD_MIN_HEIGHT = 90;
const CARD_MAX_HEIGHT = 780;

const TOPIC_KEYWORDS = {
  ia: [
    "ia", "ai", "inteligência artificial", "inteligencia artificial",
    "machine learning", "modelo", "chatgpt", "llm",
  ],
  programacao: [
    "programação", "programacao", "dev", "código", "codigo",
    "software", "framework", "python", "javascript", "react",
    "backend", "frontend",
  ],
  seguranca: [
    "segurança", "seguranca", "ciber", "hacker", "vazamento",
    "malware", "ransomware", "vulnerabilidade", "cve", "phishing",
  ],
  mobile: [
    "android", "iphone", "ios", "smartphone", "celular",
    "app", "aplicativo", "samsung", "xiaomi", "motorola",
  ],
  mercado: [
    "mercado", "empresa", "negócio", "negocio", "investimento",
    "receita", "lucro", "startup", "aquisição", "aquisicao", "economia",
  ],
  guerra_ucrania: [
    "ucrânia", "ucrania", "ukraine", "kyiv", "kiev",
    "zelensky", "rússia", "russia", "moscou", "moscow",
    "putin", "donetsk", "crimeia", "crimea",
  ],
  guerra_ira: [
    "irã", "ira", "iran", "teerã", "teera", "tehran",
    "israel", "hamas", "hezbollah", "oriente médio",
    "oriente medio", "middle east", "ataque", "míssil", "missil",
  ],
  brasil_hoje: [
    "brasil", "brasileiro", "brasileira", "brasilia",
    "rio de janeiro", "são paulo", "sao paulo", "g1",
    "agência brasil", "agencia brasil", "economia brasileira",
    "governo federal", "stf", "senado", "câmara", "camara",
  ],
};

let draggingCardId = null;
let resizingCard = null;
let dashboardPollTimer = null;
let dashboardFetchInFlight = false;

const byId = (id) => document.getElementById(id);

function escapeHtml(text) {
  const div = document.createElement("div");
  div.appendChild(document.createTextNode(String(text ?? "")));
  return div.innerHTML;
}

/* ── i18n Internationalization ────────────────────────── */

const I18N = {
  "pt-BR": {
    currency_title: "Câmbio",
    monitors_title: "Monitor de Serviços",
    digest_title: "Resumo Diário IA",
    trending_title: "Trending",
    feeds_title: "RSS Feeds Customizados",
    favorites_title: "Favoritos",
    calendar_title: "Calendário de Releases",
    no_items: "Nenhum item no momento.",
    no_monitors: "Nenhum serviço monitorado.",
    no_digest: "Nenhum resumo disponível ainda.",
    no_trending: "Sem tópicos trending no momento.",
    no_favorites: "Nenhum favorito ainda. Clique ⭐ nos itens.",
    no_feeds: "Nenhum feed customizado.",
    search_placeholder: "Buscar notícias, vagas, vídeos...",
    refresh: "Atualizar agora",
    add: "Adicionar",
    delete: "Excluir",
    save_filter: "Salvar filtro",
    saved_filters: "Filtros salvos",
    notes: "Notas",
    add_note: "Adicionar nota...",
    growth: "crescimento",
    mentions: "menções",
    up: "Online",
    down: "Offline",
    timeout: "Timeout",
    unknown: "Desconhecido",
    export_report: "Exportar relatório",
    api_docs: "Documentação API",
    price_chart: "Gráfico",
    variation: "Variação",
  },
  en: {
    currency_title: "Exchange Rates",
    monitors_title: "Service Monitor",
    digest_title: "Daily AI Digest",
    trending_title: "Trending",
    feeds_title: "Custom RSS Feeds",
    favorites_title: "Favorites",
    calendar_title: "Release Calendar",
    no_items: "No items at this time.",
    no_monitors: "No services monitored.",
    no_digest: "No digest available yet.",
    no_trending: "No trending topics right now.",
    no_favorites: "No favorites yet. Click ⭐ on items.",
    no_feeds: "No custom feeds.",
    search_placeholder: "Search news, jobs, videos...",
    refresh: "Refresh now",
    add: "Add",
    delete: "Delete",
    save_filter: "Save filter",
    saved_filters: "Saved filters",
    notes: "Notes",
    add_note: "Add note...",
    growth: "growth",
    mentions: "mentions",
    up: "Online",
    down: "Offline",
    timeout: "Timeout",
    unknown: "Unknown",
    export_report: "Export report",
    api_docs: "API Docs",
    price_chart: "Chart",
    variation: "Variation",
  },
};

function t(key) {
  const dict = I18N[state.locale] || I18N["pt-BR"];
  return dict[key] || I18N["pt-BR"][key] || key;
}

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.dataset.i18n;
    el.textContent = t(key);
  });
  const search = byId("searchInput");
  if (search) search.placeholder = t("search_placeholder");
}

function setLocale(locale) {
  state.locale = locale;
  localStorage.setItem("dashboard-locale", locale);
  applyI18n();
  render();
}

/* ── Offline Sync Queue ───────────────────────────────── */

function queueOfflineAction(action) {
  state.offlineQueue.push({ ...action, timestamp: Date.now() });
  localStorage.setItem("offline-queue", JSON.stringify(state.offlineQueue));
}

async function flushOfflineQueue() {
  if (!navigator.onLine || !state.offlineQueue.length) return;
  const queue = [...state.offlineQueue];
  state.offlineQueue = [];
  localStorage.setItem("offline-queue", "[]");

  for (const action of queue) {
    try {
      await fetch(action.url, {
        method: action.method || "POST",
        headers: { "Content-Type": "application/json" },
        body: action.body ? JSON.stringify(action.body) : undefined,
      });
    } catch {
      // Re-queue on failure
      state.offlineQueue.push(action);
    }
  }
  localStorage.setItem("offline-queue", JSON.stringify(state.offlineQueue));
}

window.addEventListener("online", flushOfflineQueue);

async function fetchDashboard() {
  if (dashboardFetchInFlight) return;

  dashboardFetchInFlight = true;
  try {
    const response = await fetch("/api/dashboard");
    if (!response.ok) {
      console.error("Dashboard fetch failed:", response.status);
      return;
    }
    state.snapshot = await response.json();
    render();
  } catch (err) {
    console.error("Dashboard fetch error:", err);
  } finally {
    dashboardFetchInFlight = false;
  }
}

function dashboardPollIntervalMs() {
  return document.visibilityState === "visible" ? 60_000 : 300_000;
}

function scheduleDashboardPolling() {
  if (dashboardPollTimer) {
    window.clearTimeout(dashboardPollTimer);
    dashboardPollTimer = null;
  }

  const interval = dashboardPollIntervalMs();
  dashboardPollTimer = window.setTimeout(async () => {
    await fetchDashboard();
    scheduleDashboardPolling();
  }, interval);
}

function fmtDate(value) {
  if (!value) return "sem data";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR");
}

function matchQuery(item) {
  if (!state.query) return true;
  const text = `${item.title ?? ""} ${item.summary ?? ""}`.toLowerCase();
  return text.includes(state.query.toLowerCase());
}

function itemCategory(item) {
  return String(item?.extra?.ai_category || "").trim().toLowerCase();
}

function matchAICategory(item) {
  if (!state.aiCategory) return true;
  return itemCategory(item) === state.aiCategory;
}

function itemTimestamp(item) {
  const value = item?.published_at || item?.created_at;
  const date = new Date(value || "");
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
}

function sortByMode(items) {
  const list = [...(items || [])];
  if (state.sortMode !== "ai_score_desc") {
    return list;
  }

  return list.sort((left, right) => {
    const scoreDiff = (resolveItemScore(right) || -1) - (resolveItemScore(left) || -1);
    if (scoreDiff !== 0) return scoreDiff;
    return itemTimestamp(right) - itemTimestamp(left);
  });
}

function renderItems(target, items, options = {}) {
  const {
    max = 10,
    summaryLength = 160,
    showImage = false,
    allowAIControls = true,
  } = options;
  const filtered = (items || []).filter((item) => {
    if (!matchQuery(item)) return false;
    if (allowAIControls && !matchAICategory(item)) return false;
    return true;
  });
  const filteredAndSorted = sortByMode(filtered).slice(0, max);

  if (!filteredAndSorted.length) {
    target.innerHTML = '<small style="color:var(--text-faint)">Nenhum item no momento.</small>';
    return;
  }

  target.innerHTML = filteredAndSorted
    .map(
      (item, idx) => `
        <article class="item" style="animation:item-fade-in 0.3s ease both;animation-delay:${Math.min(idx * 30, 300)}ms" data-item-id="${item.id || ''}">
          ${showImage && item.image_url ? `<img class="item-image" src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}" loading="lazy" />` : ""}
          ${buildItemBadges(item)}
          <div class="item-actions">
            <button class="btn-fav" onclick="toggleFavorite(${item.id})" title="Favoritar">
              ${state.favoriteIds.has(item.id) ? "★" : "☆"}
            </button>
            <button class="btn-note" onclick="showNoteModal(${item.id}, '${escapeHtml(item.title).replace(/'/g, "\\'")}')" title="${t("notes")}">📝</button>
          </div>
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>
          <div class="item-summary">${escapeHtml(toOneLineSummary(resolveItemSummary(item), summaryLength))}</div>
          <small>${escapeHtml(item.source ?? "fonte")} • ${timeAgo(item.published_at || item.created_at)}</small>
        </article>
      `
    )
    .join("");
}

function resolveItemSummary(item) {
  const extra = item?.extra || {};
  const aiSummary = String(extra.ai_summary || "").trim();
  if (aiSummary) return aiSummary;

  const titleRaw = String(item?.title || "").replace(/\s+/g, " ").trim();
  const title = titleRaw.toLowerCase();
  let summary = String(item?.summary || "").replace(/\s+/g, " ").trim();
  if (!summary) return "";
  if (title && summary.toLowerCase() === title) return "";

  const normalizedTitle = titleRaw.replace(/[\s.:-–—]+$/g, "");
  if (normalizedTitle && summary.toLowerCase().startsWith(normalizedTitle.toLowerCase())) {
    summary = summary.slice(normalizedTitle.length).replace(/^[\s.:-–—]+/, "").trim();
  }

  if (!summary || (title && summary.toLowerCase() === title)) return "";

  return summary;
}

function resolveItemScore(item) {
  if (Number.isFinite(item?.relevance_score)) {
    return item.relevance_score;
  }

  const aiScore = item?.extra?.ai_score;
  return Number.isFinite(aiScore) ? aiScore : null;
}

function buildItemBadges(item) {
  const extra = item?.extra || {};
  const score = resolveItemScore(item);
  const category = extra.ai_category;

  const badges = [];
  if (typeof category === "string" && category.trim()) {
    badges.push(`<span class="item-category">${escapeHtml(category.replaceAll("_", " "))}</span>`);
  }
  if (Number.isFinite(score)) {
    badges.push(`<span class="item-score">Relevância ${score}</span>`);
  }

  return badges.length ? `<div class="item-badges">${badges.join("")}</div>` : "";
}

function toOneLineSummary(summary, summaryLength = 160) {
  const plain = (summary ?? "").replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
  if (!plain) return "Sem resumo.";

  const firstSentence = plain.split(/(?<=[.!?])\s+/)[0] || plain;
  const clipped = firstSentence.slice(0, summaryLength);
  return clipped.length < firstSentence.length ? `${clipped}...` : clipped;
}

function renderNews(newsItems) {
  const newsTarget = byId("newsList");
  const filteredNews = rankNewsByTopic(filterNewsByTopic(newsItems || []));

  renderItems(newsTarget, filteredNews, {
    max: 80,
    summaryLength: 120,
    showImage: true,
  });
}

function filterNewsByTopic(items) {
  if (!state.newsTopic) return items || [];

  const keywords = TOPIC_KEYWORDS[state.newsTopic] || [];
  if (!keywords.length) return items || [];

  return (items || []).filter((item) => {
    const text = `${item.title ?? ""} ${item.summary ?? ""} ${item.source ?? ""}`
      .toLowerCase();
    return keywords.some((keyword) => text.includes(keyword));
  });
}

function computeTopicRelevanceScore(item) {
  if (!state.newsTopic) return null;

  const keywords = TOPIC_KEYWORDS[state.newsTopic] || [];
  if (!keywords.length) return null;

  const title = String(item.title || "").toLowerCase();
  const summary = String(item.summary || "").toLowerCase();
  const source = String(item.source || "").toLowerCase();

  let score = 0;
  keywords.forEach((keyword) => {
    if (title.includes(keyword)) score += 3;
    if (summary.includes(keyword)) score += 1;
    if (source.includes(keyword)) score += 1;
  });

  return score;
}

function rankNewsByTopic(items) {
  if (!state.newsTopic) {
    return (items || []).map((item) => ({
      ...item,
      relevance_score: undefined,
    }));
  }

  return (items || [])
    .map((item) => {
      const score = computeTopicRelevanceScore(item);
      return {
        ...item,
        relevance_score: Number.isFinite(score) ? score : 0,
      };
    })
    .sort((left, right) => (right.relevance_score || 0) - (left.relevance_score || 0));
}

function filterJobs(items) {
  return (items || []).filter((item) => {
    if (!state.jobFilter) return true;
    const text = `${item.title} ${item.summary}`.toLowerCase();

    if (state.jobFilter === "brasil") {
      return text.includes("brasil") || text.includes("brazil");
    }
    if (state.jobFilter === "remote") {
      return text.includes("remote") || text.includes("remoto");
    }
    if (state.jobFilter === "junior") {
      return text.includes("junior") || text.includes("júnior");
    }

    return text.includes(state.jobFilter);
  });
}

function renderPrices(prices, maxItems) {
  const target = byId("pricesList");
  const list = Array.isArray(prices) ? prices : [];
  const limited = Number.isFinite(maxItems) ? list.slice(0, maxItems) : list;
  if (!limited.length) {
    target.innerHTML = "<small>Nenhum produto monitorado.</small>";
    return;
  }
  // Store for comparison feature
  state._priceWatchList = limited;

  const compareBtn = list.length >= 2
    ? `<button class="btn-small" style="margin-bottom:8px" onclick="openPriceComparison()">📊 Comparar preços</button>`
    : "";

  target.innerHTML = compareBtn + limited
    .map(
      (watch) => `
        <article class="item">
          <strong>${escapeHtml(watch.name)}</strong>
          <div>Último preço: ${escapeHtml(watch.last_price ?? "--")} ${escapeHtml(watch.currency)}</div>
          <div>Alvo: ${escapeHtml(watch.target_price)} ${escapeHtml(watch.currency)}</div>
          <small>${escapeHtml(watch.product_url)}</small>
        </article>
      `
    )
    .join("");
}

function renderResponsiveCollections(data) {
  renderNews(data.news || []);

  const promoTarget = byId("promoList");
  renderItems(promoTarget, data.promotions || [], {
    max: 60,
    summaryLength: 90,
    showImage: true,
  });

  const videosTarget = byId("videosList");
  renderItems(videosTarget, data.videos || [], {
    max: 120,
    summaryLength: 90,
    showImage: true,
  });

  const releasesTarget = byId("releasesList");
  renderItems(releasesTarget, data.releases || [], { max: 60 });

  const jobsTarget = byId("jobsList");
  renderItems(jobsTarget, filterJobs(data.jobs || []), { max: 100 });

  const techTarget = byId("techList");
  renderItems(techTarget, data.tech_ai || [], { max: 80 });

  const alertsTarget = byId("alertsList");
  const alerts = (data.alerts || []).map((a) => ({
    ...a,
    url: a.payload?.url || "#",
  }));
  renderItems(alertsTarget, alerts, { max: 80, allowAIControls: false });

  renderPrices(data.prices || [], 60);
}

function renderAIObservability(metrics) {
  const data = metrics || {};
  const target = byId("aiObservabilityContent");
  if (!target) return;

  const sources = Array.isArray(data.source_accuracy) ? data.source_accuracy : [];
  const fallbackByHour = Array.isArray(data.fallback_rate_by_hour)
    ? data.fallback_rate_by_hour
    : [];
  const reasons = Array.isArray(data.reason_breakdown)
    ? data.reason_breakdown
    : [];

  const topSources = sources
    .slice(0, 5)
    .map(
      (entry) => `
        <li>
          <strong>${escapeHtml(entry.source)}</strong>
          <span>${escapeHtml(entry.model_success_rate)}% acerto modelo</span>
        </li>
      `
    )
    .join("");

  const fallbackRows = fallbackByHour
    .slice(0, 5)
    .map(
      (entry) => `
        <li>
          <strong>${escapeHtml(entry.hour)}</strong>
          <span>${escapeHtml(entry.fallback_rate)}% fallback (${escapeHtml(entry.fallback)}/${escapeHtml(entry.total)})</span>
        </li>
      `
    )
    .join("");

  const reasonRows = reasons
    .slice(0, 5)
    .map(
      (entry) => `
        <li>
          <strong>${escapeHtml(entry.reason)}</strong>
          <span>${escapeHtml(entry.total)} ocorrências</span>
        </li>
      `
    )
    .join("");

  target.innerHTML = `
    <div class="ai-metric-row">
      <span>Enriquecidos (24h)</span>
      <strong>${escapeHtml(data.enriched_percent ?? 0)}%</strong>
    </div>
    <div class="ai-metric-row">
      <span>Latência média IA</span>
      <strong>${Number.isFinite(data.avg_ai_latency_ms) ? `${escapeHtml(data.avg_ai_latency_ms)} ms` : "--"}</strong>
    </div>
    <div class="ai-observability-block">
      <h3>Acerto por fonte</h3>
      <ul>${topSources || "<li><span>Sem dados</span></li>"}</ul>
    </div>
    <div class="ai-observability-block">
      <h3>Fallback por hora</h3>
      <ul>${fallbackRows || "<li><span>Sem dados</span></li>"}</ul>
    </div>
    <div class="ai-observability-block">
      <h3>Motivos de fallback</h3>
      <ul>${reasonRows || "<li><span>Sem dados</span></li>"}</ul>
    </div>
  `;
}

const WEATHER_CODE_LABEL = {
  0: "Céu limpo",
  1: "Predomínio de sol",
  2: "Parcialmente nublado",
  3: "Nublado",
  45: "Neblina",
  48: "Neblina com geada",
  51: "Garoa fraca",
  53: "Garoa moderada",
  55: "Garoa intensa",
  56: "Garoa gelada fraca",
  57: "Garoa gelada intensa",
  61: "Chuva fraca",
  63: "Chuva moderada",
  65: "Chuva forte",
  66: "Chuva congelante fraca",
  67: "Chuva congelante forte",
  71: "Neve fraca",
  73: "Neve moderada",
  75: "Neve forte",
  77: "Grãos de neve",
  80: "Pancadas fracas",
  81: "Pancadas moderadas",
  82: "Pancadas fortes",
  85: "Neve fraca",
  86: "Neve forte",
  95: "Trovoadas",
  96: "Trovoadas com granizo fraco",
  99: "Trovoadas com granizo forte",
};

function weatherCodeLabel(code) {
  if (code === null || code === undefined) return "Condição indisponível";
  return WEATHER_CODE_LABEL[Number(code)] || `Código ${code}`;
}

function fmtDay(value) {
  if (!value) return "--";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("pt-BR", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  });
}

function renderWeather(weatherItems) {
  const target = byId("weatherContent");
  const weather = weatherItems?.[0];
  if (!weather) {
    target.textContent = "Sem dados de clima";
    return;
  }
  const extra = weather.extra || {};
  const current = extra.current || extra;
  const daily = Array.isArray(extra.daily) ? extra.daily : [];
  const city = extra.city || "Lajeado, RS";

  const forecastHtml = daily
    .slice(0, 6)
    .map(
      (day) => `
        <article class="weather-day">
          <div class="weather-day-top">
            <strong>${escapeHtml(fmtDay(day.date))}</strong>
            <small>${escapeHtml(weatherCodeLabel(day.weather_code))}</small>
          </div>
          <span class="weather-day-meta">
            ${escapeHtml(day.temp_min ?? "--")}°C / ${escapeHtml(day.temp_max ?? "--")}°C •
            Chuva ${escapeHtml(day.precip_prob_max ?? "--")}% •
            Vento ${escapeHtml(day.wind_speed_max ?? "--")} km/h
          </span>
        </article>
      `
    )
    .join("");

  target.innerHTML = `
    <div class="weather-now">
      <div class="weather-now-title">
        <strong>${escapeHtml(city)}</strong>
        <small>${escapeHtml(weatherCodeLabel(current.weather_code))}</small>
      </div>
      <div class="weather-main-temp">${escapeHtml(current.temperature_2m ?? "--")}°C</div>
      <small>
        Sensação ${escapeHtml(current.apparent_temperature ?? "--")}°C •
        Umidade ${escapeHtml(current.relative_humidity_2m ?? "--")}% •
        Chuva ${escapeHtml(current.precipitation ?? "--")} mm •
        Vento ${escapeHtml(current.wind_speed_10m ?? "--")} km/h
      </small>
    </div>
    <div class="weather-forecast">${forecastHtml || "<small>Sem previsão disponível.</small>"}</div>
  `;
}

function animateValue(el, newText) {
  if (!el || el.textContent === newText) return;
  el.style.transition = 'opacity 0.15s, transform 0.15s';
  el.style.opacity = '0';
  el.style.transform = 'translateY(-4px)';
  setTimeout(() => {
    el.textContent = newText;
    el.style.opacity = '1';
    el.style.transform = 'translateY(0)';
  }, 150);
}

/* ── Currency Widget ──────────────────────────────────── */

function renderCurrency(rates) {
  const target = byId("currencyContent");
  if (!target) return;
  const list = Array.isArray(rates) ? rates : [];
  if (!list.length) {
    target.innerHTML = `<small>${t("no_items")}</small>`;
    return;
  }
  const PAIR_ICONS = { "USD-BRL": "🇺🇸", "EUR-BRL": "🇪🇺", "BTC-BRL": "₿" };
  target.innerHTML = list
    .map((r) => {
      const icon = PAIR_ICONS[r.pair] || "💱";
      const variation = Number(r.variation) || 0;
      const varClass = variation >= 0 ? "currency-up" : "currency-down";
      const varSign = variation >= 0 ? "+" : "";
      const rateFormatted = r.pair === "BTC-BRL"
        ? Number(r.rate).toLocaleString(state.locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : Number(r.rate).toFixed(4);
      return `
        <div class="currency-row">
          <span class="currency-icon">${icon}</span>
          <strong>${escapeHtml(r.pair)}</strong>
          <span class="currency-rate">R$ ${escapeHtml(rateFormatted)}</span>
          <span class="${varClass}">${varSign}${variation.toFixed(2)}%</span>
        </div>`;
    })
    .join("");
}

/* ── Service Monitor ──────────────────────────────────── */

function renderServiceMonitors(monitors) {
  const target = byId("monitorList");
  if (!target) return;
  const list = Array.isArray(monitors) ? monitors : [];
  if (!list.length) {
    target.innerHTML = `<small>${t("no_monitors")}</small>`;
    return;
  }
  target.innerHTML = list
    .map((m) => {
      const status = String(m.last_status || "unknown").toLowerCase();
      const statusClass = status === "up" ? "status-up" : status === "down" ? "status-down" : "status-unknown";
      const statusLabel = status === "up" ? t("up") : status === "down" ? t("down") : status === "timeout" ? t("timeout") : t("unknown");
      const latency = m.last_latency_ms ? `${Math.round(m.last_latency_ms)}ms` : "--";
      return `
        <article class="item monitor-item">
          <span class="monitor-status ${statusClass}">●</span>
          <strong>${escapeHtml(m.name)}</strong>
          <span class="monitor-latency">${latency}</span>
          <small>${statusLabel}</small>
          <button class="btn-small btn-delete" onclick="deleteServiceMonitor(${m.id})" title="${t("delete")}">✕</button>
        </article>`;
    })
    .join("");
}

/* ── Daily Digest ─────────────────────────────────────── */

function renderDailyDigest(digest) {
  const target = byId("digestContent");
  if (!target) return;
  if (!digest || !digest.content) {
    target.innerHTML = `<small>${t("no_digest")}</small>`;
    return;
  }
  // Simple markdown-like rendering
  const html = escapeHtml(digest.content)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^## (.+)$/gm, "<h3>$1</h3>")
    .replace(/\n/g, "<br>");
  target.innerHTML = `
    <div class="digest-body">${html}</div>
    <small class="digest-date">${digest.digest_date || ""}</small>
  `;
}

/* ── Trending Topics ──────────────────────────────────── */

function renderTrending(topics) {
  const target = byId("trendingContent");
  if (!target) return;
  const list = Array.isArray(topics) ? topics : [];
  if (!list.length) {
    target.innerHTML = `<small>${t("no_trending")}</small>`;
    return;
  }
  target.innerHTML = list
    .slice(0, 10)
    .map((topic) => {
      const growth = topic.growth_pct > 0 ? `+${topic.growth_pct}%` : `${topic.growth_pct}%`;
      return `
        <span class="trending-tag" title="${topic.current_count} ${t("mentions")}, ${growth} ${t("growth")}">
          🔥 ${escapeHtml(topic.topic)} <small>(${topic.current_count})</small>
        </span>`;
    })
    .join("");
}

/* ── Custom Feeds ─────────────────────────────────────── */

function renderCustomFeeds(feeds) {
  const target = byId("feedList");
  if (!target) return;
  const list = Array.isArray(feeds) ? feeds : [];
  if (!list.length) {
    target.innerHTML = `<small>${t("no_feeds")}</small>`;
    return;
  }
  target.innerHTML = list
    .map((f) => {
      const active = f.active === true || f.active === 1 || f.active === "1";
      return `
        <article class="item feed-item">
          <strong>${escapeHtml(f.name)}</strong>
          <small>${escapeHtml(f.feed_url)}</small>
          <span class="feed-type">${escapeHtml(f.item_type || "news")}</span>
          <button class="btn-small" onclick="loadFeedArticles(${f.id}, '${escapeHtml(f.name)}')" title="Ler artigos">📰</button>
          <button class="btn-small" onclick="toggleFeed(${f.id}, ${!active})">${active ? "⏸" : "▶"}</button>
          <button class="btn-small btn-delete" onclick="deleteFeed(${f.id})">✕</button>
        </article>`;
    })
    .join("");
}

/* ── RSS Reader Modal ─────────────────────────────────── */

async function loadFeedArticles(feedId, feedName) {
  let modal = document.getElementById("rssModal");
  if (modal) modal.remove();

  modal = document.createElement("div");
  modal.id = "rssModal";
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal-content chart-modal-content">
      <div class="modal-header">
        <h3>📰 ${escapeHtml(feedName)}</h3>
        <button class="modal-close" id="rssModalClose">✕</button>
      </div>
      <div id="rssArticleList"><small>Carregando artigos...</small></div>
    </div>
  `;
  document.body.appendChild(modal);

  document.getElementById("rssModalClose").onclick = () => modal.remove();
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.remove(); });

  try {
    const res = await fetch(`/api/custom-feeds/${feedId}/articles`);
    const data = await res.json();
    const container = document.getElementById("rssArticleList");
    if (!res.ok) {
      container.innerHTML = `<small style="color:var(--rose)">Erro: ${escapeHtml(data.error || "Falha")}</small>`;
      return;
    }
    const articles = data.articles || [];
    if (!articles.length) {
      container.innerHTML = `<small>Nenhum artigo encontrado.</small>`;
      return;
    }
    container.innerHTML = articles.map(a => `
      <a href="${escapeHtml(a.link)}" target="_blank" rel="noopener" class="rss-article">
        <div class="rss-article-title">${escapeHtml(a.title)}</div>
        <div class="rss-article-meta">${escapeHtml(a.published)}${a.summary ? " — " + escapeHtml(a.summary) : ""}</div>
      </a>
    `).join("");
  } catch (err) {
    const container = document.getElementById("rssArticleList");
    if (container) container.innerHTML = `<small style="color:var(--rose)">Erro de rede</small>`;
  }
}

/* ── Favorites ────────────────────────────────────────── */

function renderFavorites(snapshot) {
  const target = byId("favoritesList");
  if (!target) return;

  // Update favorite IDs set from snapshot
  const ids = snapshot.favorite_ids || [];
  state.favoriteIds = new Set(ids);

  if (!ids.length) {
    target.innerHTML = `<small>${t("no_favorites")}</small>`;
    return;
  }

  // Gather all items and filter favorites
  const allItems = [
    ...(snapshot.news || []),
    ...(snapshot.promotions || []),
    ...(snapshot.tech_ai || []),
    ...(snapshot.videos || []),
    ...(snapshot.jobs || []),
    ...(snapshot.releases || []),
  ];
  const favItems = allItems.filter((item) => state.favoriteIds.has(item.id));

  if (!favItems.length) {
    target.innerHTML = `<small>${t("no_favorites")}</small>`;
    return;
  }

  target.innerHTML = favItems
    .slice(0, 30)
    .map(
      (item) => `
        <article class="item">
          <button class="btn-fav active" onclick="toggleFavorite(${item.id})">★</button>
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>
          <small>${escapeHtml(item.source ?? "")} • ${timeAgo(item.published_at || item.created_at)}</small>
        </article>`
    )
    .join("");
}

/* ── Release Calendar ─────────────────────────────────── */

function renderReleaseCalendar(releases) {
  const target = byId("releaseCalendar");
  if (!target) return;
  const list = Array.isArray(releases) ? releases : [];
  if (!list.length) {
    target.innerHTML = `<small>${t("no_items")}</small>`;
    return;
  }

  // Group by date
  const grouped = {};
  for (const item of list) {
    const dateStr = (item.published_at || item.created_at || "").slice(0, 10);
    if (!grouped[dateStr]) grouped[dateStr] = [];
    grouped[dateStr].push(item);
  }

  const dates = Object.keys(grouped).sort().slice(-14);
  target.innerHTML = `
    <div class="calendar-timeline">
      ${dates
        .map(
          (date) => `
          <div class="calendar-day">
            <div class="calendar-date">${fmtDay(date)}</div>
            ${grouped[date]
              .slice(0, 5)
              .map(
                (item) => `
                <div class="calendar-item" title="${escapeHtml(item.title)}">
                  <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml((item.title || "").slice(0, 40))}</a>
                </div>`
              )
              .join("")}
          </div>`
        )
        .join("")}
    </div>`;
}

/* ── Price Charts (Chart.js) ──────────────────────────── */

const priceChartInstances = {};

async function renderPriceCharts(prices) {
  if (typeof Chart === "undefined") return;
  const list = Array.isArray(prices) ? prices : [];

  for (const watch of list.slice(0, 10)) {
    const canvasId = `price-chart-${watch.id}`;
    let canvas = document.getElementById(canvasId);

    if (!canvas) {
      const container = byId("pricesList");
      if (!container) continue;
      const wrapper = document.createElement("div");
      wrapper.className = "price-chart-wrapper";
      wrapper.innerHTML = `<canvas id="${canvasId}" height="60"></canvas>`;
      container.appendChild(wrapper);
      canvas = document.getElementById(canvasId);
    }

    try {
      const resp = await fetch(`/api/price-history/${watch.id}`);
      if (!resp.ok) continue;
      const history = await resp.json();
      if (!history.length) continue;

      const labels = history.map((h) => h.captured_at?.slice(5, 16) || "").reverse();
      const data = history.map((h) => h.price).reverse();

      if (priceChartInstances[canvasId]) {
        priceChartInstances[canvasId].destroy();
      }

      priceChartInstances[canvasId] = new Chart(canvas, {
        type: "line",
        data: {
          labels,
          datasets: [
            {
              label: watch.name,
              data,
              borderColor: "rgba(99, 102, 241, 0.8)",
              backgroundColor: "rgba(99, 102, 241, 0.1)",
              fill: true,
              tension: 0.3,
              pointRadius: 1,
              borderWidth: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { display: false },
            y: { display: true, ticks: { font: { size: 9 } } },
          },
        },
      });

      // Click to expand chart in modal
      canvas.style.cursor = "pointer";
      canvas.onclick = () => openChartModal(watch.name, labels, data);
    } catch {
      // Ignore chart errors
    }
  }
}

/* ── Chart Modal (expanded view) ──────────────────────── */

let _chartModalInstance = null;
function openChartModal(title, labels, data) {
  let modal = document.getElementById("chartModal");
  if (modal) modal.remove();
  if (_chartModalInstance) { _chartModalInstance.destroy(); _chartModalInstance = null; }

  modal = document.createElement("div");
  modal.id = "chartModal";
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal-content chart-modal-content">
      <div class="modal-header">
        <h3>📈 ${escapeHtml(title)}</h3>
        <button class="modal-close" id="chartModalClose">✕</button>
      </div>
      <div style="position:relative;height:400px;width:100%">
        <canvas id="chartModalCanvas"></canvas>
      </div>
      <div class="chart-modal-stats" id="chartModalStats"></div>
    </div>
  `;
  document.body.appendChild(modal);

  document.getElementById("chartModalClose").onclick = () => {
    if (_chartModalInstance) { _chartModalInstance.destroy(); _chartModalInstance = null; }
    modal.remove();
  };
  modal.addEventListener("click", (e) => {
    if (e.target === modal) {
      if (_chartModalInstance) { _chartModalInstance.destroy(); _chartModalInstance = null; }
      modal.remove();
    }
  });

  // Stats
  const numData = data.map(Number).filter(Number.isFinite);
  const min = Math.min(...numData);
  const max = Math.max(...numData);
  const avg = numData.length ? (numData.reduce((a, b) => a + b, 0) / numData.length) : 0;
  const latest = numData[numData.length - 1] || 0;
  const statsEl = document.getElementById("chartModalStats");
  if (statsEl) {
    statsEl.innerHTML = `
      <span>Mín: <strong>R$ ${min.toFixed(2)}</strong></span>
      <span>Máx: <strong>R$ ${max.toFixed(2)}</strong></span>
      <span>Média: <strong>R$ ${avg.toFixed(2)}</strong></span>
      <span>Atual: <strong>R$ ${latest.toFixed(2)}</strong></span>
      <span>Pontos: <strong>${numData.length}</strong></span>
    `;
  }

  const ctx = document.getElementById("chartModalCanvas");
  _chartModalInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: title,
        data,
        borderColor: "rgba(99, 102, 241, 1)",
        backgroundColor: "rgba(99, 102, 241, 0.15)",
        fill: true,
        tension: 0.3,
        pointRadius: 3,
        pointHoverRadius: 6,
        borderWidth: 2.5,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: true, position: "top" },
        tooltip: {
          callbacks: {
            label: (ctx) => `R$ ${Number(ctx.parsed.y).toFixed(2)}`,
          },
        },
      },
      scales: {
        x: { display: true, ticks: { maxRotation: 45, font: { size: 10 } } },
        y: { display: true, ticks: { font: { size: 11 } } },
      },
    },
  });
}

/* ── Price Comparison Overlay ─────────────────────────── */

const COMPARISON_COLORS = [
  "rgba(99, 102, 241, 1)", "rgba(34, 211, 238, 1)", "rgba(251, 113, 133, 1)",
  "rgba(251, 191, 36, 1)", "rgba(52, 211, 153, 1)", "rgba(168, 85, 247, 1)",
  "rgba(244, 114, 182, 1)", "rgba(56, 189, 248, 1)",
];

let _comparisonChartInstance = null;

async function openPriceComparison() {
  const watches = state._priceWatchList || [];
  if (watches.length < 2) return;

  let modal = document.getElementById("priceCompModal");
  if (modal) modal.remove();
  if (_comparisonChartInstance) { _comparisonChartInstance.destroy(); _comparisonChartInstance = null; }

  const selected = new Set(watches.slice(0, 4).map(w => w.id));

  modal = document.createElement("div");
  modal.id = "priceCompModal";
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal-content chart-modal-content">
      <div class="modal-header">
        <h3>📊 Comparar Preços</h3>
        <button class="modal-close" id="priceCompClose">✕</button>
      </div>
      <div class="comparison-toolbar" id="compToolbar"></div>
      <div style="position:relative;height:400px;width:100%">
        <canvas id="compCanvas"></canvas>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  document.getElementById("priceCompClose").onclick = () => {
    if (_comparisonChartInstance) { _comparisonChartInstance.destroy(); _comparisonChartInstance = null; }
    modal.remove();
  };
  modal.addEventListener("click", (e) => {
    if (e.target === modal) {
      if (_comparisonChartInstance) { _comparisonChartInstance.destroy(); _comparisonChartInstance = null; }
      modal.remove();
    }
  });

  // Render chips
  const toolbar = document.getElementById("compToolbar");
  toolbar.innerHTML = watches.map(w => {
    const sel = selected.has(w.id) ? "selected" : "";
    return `<span class="comparison-chip ${sel}" data-wid="${w.id}">${escapeHtml(w.name)}</span>`;
  }).join("");

  toolbar.addEventListener("click", (e) => {
    const chip = e.target.closest(".comparison-chip");
    if (!chip) return;
    const wid = Number(chip.dataset.wid);
    if (selected.has(wid)) { selected.delete(wid); chip.classList.remove("selected"); }
    else { selected.add(wid); chip.classList.add("selected"); }
    drawComparisonChart(watches, selected);
  });

  await drawComparisonChart(watches, selected);
}

async function drawComparisonChart(watches, selectedIds) {
  if (_comparisonChartInstance) { _comparisonChartInstance.destroy(); _comparisonChartInstance = null; }
  const ctx = document.getElementById("compCanvas");
  if (!ctx) return;

  const datasets = [];
  let colorIdx = 0;

  for (const w of watches) {
    if (!selectedIds.has(w.id)) continue;
    try {
      const resp = await fetch(`/api/price-history/${w.id}`);
      if (!resp.ok) continue;
      const history = await resp.json();
      if (!history.length) continue;
      const labels = history.map(h => h.captured_at?.slice(5, 16) || "").reverse();
      const data = history.map(h => h.price).reverse();
      const color = COMPARISON_COLORS[colorIdx % COMPARISON_COLORS.length];
      datasets.push({
        label: w.name,
        data,
        borderColor: color,
        backgroundColor: color.replace(", 1)", ", 0.1)"),
        fill: false,
        tension: 0.3,
        pointRadius: 2,
        pointHoverRadius: 5,
        borderWidth: 2,
        _labels: labels,
      });
      colorIdx++;
    } catch { /* skip */ }
  }

  if (!datasets.length) return;

  // Use longest label set
  const longestLabels = datasets.reduce((a, b) => (a._labels || []).length >= (b._labels || []).length ? a : b)._labels || [];

  _comparisonChartInstance = new Chart(ctx, {
    type: "line",
    data: { labels: longestLabels, datasets: datasets.map(d => { const { _labels, ...rest } = d; return rest; }) },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: true, position: "top" },
        tooltip: {
          callbacks: { label: (ctx) => `${ctx.dataset.label}: R$ ${Number(ctx.parsed.y).toFixed(2)}` },
        },
      },
      scales: {
        x: { display: true, ticks: { maxRotation: 45, font: { size: 10 } } },
        y: { display: true, ticks: { font: { size: 11 } } },
      },
    },
  });
}

/* ── Favorite toggle ──────────────────────────────────── */

async function toggleFavorite(itemId) {
  if (!itemId) return;

  const action = state.favoriteIds.has(itemId) ? "remove" : "add";

  if (!navigator.onLine) {
    queueOfflineAction({
      url: action === "add" ? "/api/favorites" : `/api/favorites/${itemId}`,
      method: action === "add" ? "POST" : "DELETE",
      body: action === "add" ? { item_id: itemId } : undefined,
    });
    // Optimistic update
    if (action === "add") state.favoriteIds.add(itemId);
    else state.favoriteIds.delete(itemId);
    render();
    return;
  }

  try {
    if (action === "add") {
      await fetch("/api/favorites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: itemId }),
      });
      state.favoriteIds.add(itemId);
      showToast("Adicionado aos favoritos!", "success");
    } else {
      await fetch(`/api/favorites/${itemId}`, { method: "DELETE" });
      state.favoriteIds.delete(itemId);
      showToast("Removido dos favoritos", "info");
    }
    render();
  } catch {
    showToast("Erro ao atualizar favorito", "error");
  }
}

/* ── Notes Modal ──────────────────────────────────────── */

async function showNoteModal(itemId, itemTitle) {
  let modal = document.getElementById("noteModal");
  if (modal) modal.remove();

  let notes = [];
  try {
    const resp = await fetch(`/api/notes?item_id=${itemId}`);
    if (resp.ok) notes = await resp.json();
  } catch { /* ignore */ }

  modal = document.createElement("div");
  modal.id = "noteModal";
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h3>📝 ${t("notes")} — ${escapeHtml(itemTitle)}</h3>
        <button class="modal-close" onclick="document.getElementById('noteModal').remove()">✕</button>
      </div>
      <div class="notes-list" id="notesList">
        ${notes.length ? notes.map((n) => `
          <div class="note-item">
            <p>${escapeHtml(n.content)}</p>
            <small>${timeAgo(n.created_at)}</small>
            <button class="btn-small btn-delete" onclick="deleteNote(${n.id})">✕</button>
          </div>
        `).join("") : `<small>${t("no_items")}</small>`}
      </div>
      <form class="note-form" onsubmit="submitNote(event, ${itemId})">
        <textarea name="content" placeholder="${t("add_note")}" rows="2" required></textarea>
        <button type="submit">${t("add")}</button>
      </form>
    </div>
  `;
  document.body.appendChild(modal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.remove();
  });
}

async function submitNote(event, itemId) {
  event.preventDefault();
  const form = event.target;
  const content = form.content.value.trim();
  if (!content) return;

  try {
    const resp = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, content }),
    });
    if (resp.ok) {
      form.content.value = "";
      showToast("Nota adicionada!", "success");
      // Refresh note list
      const notesResp = await fetch(`/api/notes?item_id=${itemId}`);
      if (notesResp.ok) {
        const notes = await notesResp.json();
        const list = document.getElementById("notesList");
        if (list) {
          list.innerHTML = notes.map((n) => `
            <div class="note-item">
              <p>${escapeHtml(n.content)}</p>
              <small>${timeAgo(n.created_at)}</small>
              <button class="btn-small btn-delete" onclick="deleteNote(${n.id})">✕</button>
            </div>
          `).join("");
        }
      }
    }
  } catch {
    showToast("Erro ao salvar nota", "error");
  }
}

async function deleteNote(noteId) {
  try {
    await fetch(`/api/notes/${noteId}`, { method: "DELETE" });
    showToast("Nota removida", "info");
    // Find and remove the note element
    const modal = document.getElementById("noteModal");
    if (modal) {
      const noteEl = modal.querySelector(`.note-item button[onclick="deleteNote(${noteId})"]`);
      if (noteEl) noteEl.closest(".note-item").remove();
    }
  } catch {
    showToast("Erro ao remover nota", "error");
  }
}

/* ── Custom Feed management ───────────────────────────── */

async function deleteFeed(feedId) {
  try {
    await fetch(`/api/custom-feeds/${feedId}`, { method: "DELETE" });
    showToast("Feed removido", "info");
    await fetchDashboard();
  } catch {
    showToast("Erro ao remover feed", "error");
  }
}

async function toggleFeed(feedId, active) {
  try {
    await fetch(`/api/custom-feeds/${feedId}/toggle`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active }),
    });
    await fetchDashboard();
  } catch {
    showToast("Erro ao atualizar feed", "error");
  }
}

/* ── Service Monitor management ───────────────────────── */

async function deleteServiceMonitor(monitorId) {
  try {
    await fetch(`/api/service-monitors/${monitorId}`, { method: "DELETE" });
    showToast("Monitor removido", "info");
    await fetchDashboard();
  } catch {
    showToast("Erro ao remover monitor", "error");
  }
}

/* ── Saved Filters ────────────────────────────────────── */

async function loadSavedFilters() {
  try {
    const resp = await fetch("/api/saved-filters");
    if (resp.ok) {
      state.savedFilters = await resp.json();
      renderSavedFilterOptions();
    }
  } catch { /* ignore */ }
}

function renderSavedFilterOptions() {
  const select = byId("savedFilterSelect");
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">${t("saved_filters")}</option>`;
  for (const f of state.savedFilters) {
    const opt = document.createElement("option");
    opt.value = String(f.id);
    opt.textContent = f.name;
    select.appendChild(opt);
  }
  select.value = current;
}

async function saveCurrentFilter() {
  const name = prompt(t("save_filter") + ":");
  if (!name) return;
  const filterData = {
    query: state.query,
    jobFilter: state.jobFilter,
    newsTopic: state.newsTopic,
    aiCategory: state.aiCategory,
    sortMode: state.sortMode,
  };
  try {
    await fetch("/api/saved-filters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, filter: filterData }),
    });
    showToast("Filtro salvo!", "success");
    await loadSavedFilters();
  } catch {
    showToast("Erro ao salvar filtro", "error");
  }
}

function applySavedFilter(filterId) {
  if (!filterId) return;
  const saved = state.savedFilters.find((f) => String(f.id) === String(filterId));
  if (!saved || !saved.filter) return;
  const f = saved.filter;
  if (f.query !== undefined) { state.query = f.query; byId("searchInput").value = f.query; }
  if (f.jobFilter !== undefined) state.jobFilter = f.jobFilter;
  if (f.newsTopic !== undefined) state.newsTopic = f.newsTopic;
  if (f.aiCategory !== undefined) { state.aiCategory = f.aiCategory; byId("aiCategoryFilter").value = f.aiCategory; }
  if (f.sortMode !== undefined) { state.sortMode = f.sortMode; byId("sortMode").value = f.sortMode; }
  render();
  showToast(`Filtro "${saved.name}" aplicado`, "info");
}

/* ── Web Push Notifications ───────────────────────────── */

async function setupWebPush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;

  try {
    const resp = await fetch("/api/push/vapid-public-key");
    if (!resp.ok) return;
    const { publicKey } = await resp.json();
    if (!publicKey) return;

    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();

    if (!subscription) {
      const converted = urlBase64ToUint8Array(publicKey);
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: converted,
      });

      // Send subscription to server
      await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: subscription.endpoint,
          keys: {
            p256dh: arrayBufferToBase64(subscription.getKey("p256dh")),
            auth: arrayBufferToBase64(subscription.getKey("auth")),
          },
        }),
      });
    }
  } catch (err) {
    console.debug("Web Push setup skipped:", err.message);
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

function arrayBufferToBase64(buffer) {
  if (!buffer) return "";
  return btoa(String.fromCharCode(...new Uint8Array(buffer)));
}

function render() {
  const data = state.snapshot;
  if (!data) return;

  animateValue(byId("countNews"), String((data.news || []).length));
  animateValue(byId("countPromo"), String((data.promotions || []).length));
  animateValue(byId("countJobs"), String((data.jobs || []).length));
  animateValue(byId("countVideos"), String((data.videos || []).length));
  animateValue(byId("lastUpdated"), new Date().toLocaleTimeString("pt-BR"));

  const aiMetrics = data.ai_observability || {};
  animateValue(byId("aiEnrichedPct"), `${aiMetrics.enriched_percent ?? 0}%`);
  animateValue(
    byId("aiLatency"),
    Number.isFinite(aiMetrics.avg_ai_latency_ms)
      ? `${aiMetrics.avg_ai_latency_ms} ms`
      : "—"
  );
  const latestFallback = Array.isArray(aiMetrics.fallback_rate_by_hour)
    ? aiMetrics.fallback_rate_by_hour[0]
    : null;
  animateValue(
    byId("aiFallbackHour"),
    latestFallback ? `${latestFallback.fallback_rate}%` : "—"
  );

  renderWeather(data.weather || []);
  renderResponsiveCollections(data);
  renderAIObservability(aiMetrics);
  renderCurrency(data.currency_rates || []);
  renderServiceMonitors(data.service_monitors || []);
  renderDailyDigest(data.daily_digest);
  renderTrending(data.trending_topics || []);
  renderCustomFeeds(data.custom_feeds || []);
  renderFavorites(data);
  renderReleaseCalendar(data.releases || []);
  renderPriceCharts(data.prices || []);

  updateAllCardListHeights();
}

async function addPriceWatch(event) {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.target_price = Number(payload.target_price);

  try {
    const response = await fetch("/api/price-watch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      showToast(body.error || "Erro ao criar monitor de preço", "error");
      return;
    }

    form.reset();
    showToast("Monitor de preço adicionado!", "success");
    await fetchDashboard();
  } catch (err) {
    console.error("Price watch error:", err);
    showToast("Erro de rede ao criar monitor de preço", "error");
  }
}

async function runNow() {
  const btn = byId("refreshBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Atualizando...";
    btn.style.opacity = "0.7";
  }
  try {
    const response = await fetch("/api/run-now", { method: "POST" });
    if (!response.ok) {
      showToast("Falha ao iniciar atualização", "error");
    } else {
      showToast("Atualização iniciada!", "success");
    }
  } catch (err) {
    console.error("run-now error:", err);
    showToast("Erro de rede", "error");
  }
  await fetchDashboard();
  if (btn) {
    btn.disabled = false;
    btn.textContent = "Atualizar agora";
    btn.style.opacity = "1";
  }
}

function setupEvents() {
  byId("searchInput").addEventListener("input", (event) => {
    state.query = event.target.value.trim();
    render();
  });

  byId("priceForm").addEventListener("submit", addPriceWatch);
  byId("refreshBtn").addEventListener("click", runNow);
  byId("themeToggle")?.addEventListener("click", toggleTheme);
  byId("focusModeBtn")?.addEventListener("click", toggleFocusMode);

  byId("jobFilters").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-term]");
    if (!button) return;

    if (state.jobFilter === button.dataset.term) {
      state.jobFilter = "";
      button.classList.remove("active");
      render();
      return;
    }

    state.jobFilter = button.dataset.term;
    byId("jobFilters")
      .querySelectorAll("button[data-term]")
      .forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    render();
  });

  byId("newsFilters").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-topic]");
    if (!button) return;

    state.newsTopic = button.dataset.topic || "";
    byId("newsFilters")
      .querySelectorAll("button[data-topic]")
      .forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    render();
  });

  byId("aiCategoryFilter").addEventListener("change", (event) => {
    state.aiCategory = String(event.target.value || "").trim().toLowerCase();
    render();
  });

  byId("sortMode").addEventListener("change", (event) => {
    state.sortMode = String(event.target.value || "recency");
    render();
  });

  /* --- New feature event listeners --- */

  // Service monitor form
  const monitorForm = byId("monitorForm");
  if (monitorForm) {
    monitorForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(monitorForm);
      const name = (fd.get("name") || "").trim();
      const url = (fd.get("url") || "").trim();
      if (!name || !url) return;
      try {
        const res = await fetch("/api/service-monitors", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, url }),
        });
        if (res.ok) {
          showToast(t("monitorAdded") || "Monitor added");
          monitorForm.reset();
          fetchDashboard();
        } else {
          showToast("Error adding monitor", "error");
        }
      } catch {
        queueOfflineAction({ method: "POST", url: "/api/service-monitors", body: { name, url } });
        showToast("Queued for when online", "warning");
      }
    });
  }

  // Custom feed form
  const feedForm = byId("feedForm");
  if (feedForm) {
    feedForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(feedForm);
      const name = (fd.get("name") || "").trim();
      const url = (fd.get("feed_url") || "").trim();
      if (!name || !url) return;
      try {
        const res = await fetch("/api/custom-feeds", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, feed_url: url }),
        });
        if (res.ok) {
          showToast(t("feedAdded") || "Feed added");
          feedForm.reset();
          fetchDashboard();
        } else {
          showToast("Error adding feed", "error");
        }
      } catch {
        queueOfflineAction({ method: "POST", url: "/api/custom-feeds", body: { name, url } });
        showToast("Queued for when online", "warning");
      }
    });
  }

  // Saved filters
  const savedFilterSelect = byId("savedFilterSelect");
  if (savedFilterSelect) {
    savedFilterSelect.addEventListener("change", () => applySavedFilter());
  }
  const saveFilterBtn = byId("saveFilterBtn");
  if (saveFilterBtn) {
    saveFilterBtn.addEventListener("click", () => saveCurrentFilter());
  }

  // Language select
  const langSelect = byId("langSelect");
  if (langSelect) {
    langSelect.value = state.locale;
    langSelect.addEventListener("change", (e) => setLocale(e.target.value));
  }

  // Delegate click events for dynamic buttons
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    const itemId = btn.dataset.itemId;

    switch (action) {
      case "toggle-favorite":
        if (itemId) toggleFavorite(itemId);
        break;
      case "show-notes":
        if (itemId) showNoteModal(itemId);
        break;
      case "delete-feed":
        if (id) deleteFeed(id);
        break;
      case "toggle-feed":
        if (id) toggleFeed(id);
        break;
      case "delete-monitor":
        if (id) deleteServiceMonitor(id);
        break;
      case "delete-note":
        if (id) deleteNote(id);
        break;
    }
  });
}

function persistCardOrder() {
  const grid = byId("dashboardGrid");
  if (!grid) return;
  const cardIds = [...grid.querySelectorAll(".card[data-card-id]")].map(
    (card) => card.dataset.cardId
  );
  localStorage.setItem(CARD_ORDER_KEY, JSON.stringify(cardIds));
}

function applySavedCardOrder() {
  const grid = byId("dashboardGrid");
  if (!grid) return;
  const raw = localStorage.getItem(CARD_ORDER_KEY);
  if (!raw) return;

  let order;
  try {
    order = JSON.parse(raw);
  } catch {
    return;
  }

  if (!Array.isArray(order)) return;

  const cardsById = new Map(
    [...grid.querySelectorAll(".card[data-card-id]")].map((card) => [
      card.dataset.cardId,
      card,
    ])
  );

  order.forEach((cardId) => {
    const card = cardsById.get(cardId);
    if (card) {
      grid.appendChild(card);
    }
  });
}

function persistCardHeights() {
  const grid = byId("dashboardGrid");
  if (!grid) return;

  const heights = {};
  [...grid.querySelectorAll(".card[data-card-id]")].forEach((card) => {
    if (card.style.height) {
      heights[card.dataset.cardId] = card.style.height;
    }
  });
  localStorage.setItem(CARD_HEIGHT_KEY, JSON.stringify(heights));
}

function applySavedCardHeights() {
  const grid = byId("dashboardGrid");
  if (!grid) return;

  const raw = localStorage.getItem(CARD_HEIGHT_KEY);
  if (!raw) return;

  let heights;
  try {
    heights = JSON.parse(raw);
  } catch {
    return;
  }

  if (!heights || typeof heights !== "object") return;

  [...grid.querySelectorAll(".card[data-card-id]")].forEach((card) => {
    const value = heights[card.dataset.cardId];
    if (typeof value === "string" && value.endsWith("px")) {
      card.style.height = value;
    }
  });
}

function normalizeCardHeightsToViewport() {
  const grid = byId("dashboardGrid");
  if (!grid) return;

  const maxViewportHeight = Math.max(260, window.innerHeight - 120);

  [...grid.querySelectorAll(".card[data-card-id]")].forEach((card) => {
    const raw = card.style.height;
    if (!raw || !raw.endsWith("px")) return;
    const value = Number.parseInt(raw, 10);
    if (!Number.isFinite(value)) return;

    const clamped = Math.max(CARD_MIN_HEIGHT, Math.min(maxViewportHeight, value));
    card.style.height = `${clamped}px`;
  });

  persistCardHeights();
}

function updateCardListHeights(card) {
  if (!card) return;

  const areas = [...card.querySelectorAll(".list, .weather-forecast")];
  if (!areas.length) return;

  const hasManualHeight = Boolean(card.style.height);

  areas.forEach((area) => {
    if (!hasManualHeight) {
      area.style.maxHeight = "";
      return;
    }

    const topOffset = area.offsetTop - card.offsetTop;
    const available = card.clientHeight - topOffset - 16;
    const minAreaHeight = area.classList.contains("weather-forecast") ? 36 : 48;
    const nextMaxHeight = Math.max(minAreaHeight, Math.round(available));
    area.style.maxHeight = `${nextMaxHeight}px`;
  });
}

function updateAllCardListHeights() {
  const grid = byId("dashboardGrid");
  if (!grid) return;

  [...grid.querySelectorAll(".card[data-card-id]")].forEach((card) => {
    updateCardListHeights(card);
  });
}

function persistCardSpans() {
  const grid = byId("dashboardGrid");
  if (!grid) return;

  const spans = {};
  [...grid.querySelectorAll(".card[data-card-id]")].forEach((card) => {
    const match = String(card.style.gridColumn || "").match(/span\s+(\d+)/i);
    if (match?.[1]) {
      spans[card.dataset.cardId] = Number(match[1]);
    }
  });
  localStorage.setItem(CARD_SPAN_KEY, JSON.stringify(spans));
}

function getGridColumnCount(grid) {
  const columns = getComputedStyle(grid)
    .gridTemplateColumns
    .split(" ")
    .filter(Boolean);
  return Math.max(1, columns.length);
}

function clampCardSpan(card, maxCols) {
  const match = String(card.style.gridColumn || "").match(/span\s+(\d+)/i);
  if (!match?.[1]) return;
  const clamped = Math.max(1, Math.min(maxCols, Number(match[1])));
  card.style.gridColumn = `span ${clamped}`;
}

function applySavedCardSpans() {
  const grid = byId("dashboardGrid");
  if (!grid) return;

  const raw = localStorage.getItem(CARD_SPAN_KEY);
  if (!raw) return;

  let spans;
  try {
    spans = JSON.parse(raw);
  } catch {
    return;
  }

  if (!spans || typeof spans !== "object") return;

  const maxCols = getGridColumnCount(grid);
  [...grid.querySelectorAll(".card[data-card-id]")].forEach((card) => {
    const value = Number(spans[card.dataset.cardId]);
    if (!Number.isFinite(value)) return;
    const span = Math.max(1, Math.min(maxCols, Math.round(value)));
    card.style.gridColumn = `span ${span}`;
  });
}

function normalizeCardSpansToViewport() {
  const grid = byId("dashboardGrid");
  if (!grid) return;
  const maxCols = getGridColumnCount(grid);
  [...grid.querySelectorAll(".card[data-card-id]")].forEach((card) => {
    clampCardSpan(card, maxCols);
  });
  persistCardSpans();
}

function setupCardResize() {
  const grid = byId("dashboardGrid");
  if (!grid) return;

  const cards = [...grid.querySelectorAll(".card[data-card-id]")];
  const edgeThreshold = 12;
  const resizeDirections = ["n", "e", "s", "w", "ne", "nw", "se", "sw"];

  function beginResize(card, event, direction) {
    event.preventDefault();
    event.stopPropagation();

    resizingCard = {
      card,
      grid,
      direction,
      startY: event.clientY,
      startX: event.clientX,
      startHeight: card.getBoundingClientRect().height,
      startWidth: card.getBoundingClientRect().width,
    };
    card.classList.add("resizing");
    card.style.cursor = cursorForDirection(direction);
    card.draggable = false;
  }

  function getResizeDirection(card, event) {
    const rect = card.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;

    const nearLeft = x <= edgeThreshold;
    const nearRight = x >= rect.width - edgeThreshold;
    const nearTop = y <= edgeThreshold;
    const nearBottom = y >= rect.height - edgeThreshold;

    const vertical = nearTop ? "n" : nearBottom ? "s" : "";
    const horizontal = nearLeft ? "w" : nearRight ? "e" : "";
    const direction = `${vertical}${horizontal}`;
    return direction || null;
  }

  function cursorForDirection(direction) {
    if (!direction) return "grab";
    if (direction === "n" || direction === "s") return "ns-resize";
    if (direction === "e" || direction === "w") return "ew-resize";
    if (direction === "ne" || direction === "sw") return "nesw-resize";
    return "nwse-resize";
  }

  cards.forEach((card) => {
    resizeDirections.forEach((direction) => {
      const selector = `.card-resize-handle[data-dir="${direction}"]`;
      if (card.querySelector(selector)) return;

      const handle = document.createElement("div");
      handle.className = `card-resize-handle card-resize-${direction}`;
      handle.dataset.dir = direction;

      handle.addEventListener("mousedown", (event) => {
        beginResize(card, event, direction);
      });

      card.appendChild(handle);
    });

    card.addEventListener("mousemove", (event) => {
      if (resizingCard?.card === card) return;
      const direction = getResizeDirection(card, event);
      card.style.cursor = cursorForDirection(direction);
    });

    card.addEventListener("mouseleave", () => {
      if (resizingCard?.card === card) return;
      card.style.cursor = "grab";
    });

    card.addEventListener("mousedown", (event) => {
      if (event.button !== 0) return;

      const direction = getResizeDirection(card, event);
      if (!direction) return;

      beginResize(card, event, direction);
    });
  });

  window.addEventListener("mousemove", (event) => {
    if (!resizingCard) return;

    const gridStyle = getComputedStyle(resizingCard.grid);
    const columnGap =
      Number.parseFloat(gridStyle.columnGap || gridStyle.gap || "0") || 0;
    const cols = getGridColumnCount(resizingCard.grid);
    const colWidth =
      (resizingCard.grid.clientWidth - columnGap * (cols - 1)) / cols;

    const deltaX = event.clientX - resizingCard.startX;
    const deltaY = event.clientY - resizingCard.startY;
    const direction = resizingCard.direction || "se";
    const widthDelta =
      (direction.includes("e") ? deltaX : 0) +
      (direction.includes("w") ? -deltaX : 0);
    const heightDelta =
      (direction.includes("s") ? deltaY : 0) +
      (direction.includes("n") ? -deltaY : 0);

    const hasHorizontalResize = /e|w/.test(direction);
    const hasVerticalResize = /n|s/.test(direction);

    const nextWidth = Math.max(colWidth, resizingCard.startWidth + widthDelta);
    const maxViewportHeight = Math.max(260, window.innerHeight - 120);
    const nextHeight = Math.max(
      CARD_MIN_HEIGHT,
      Math.min(
        CARD_MAX_HEIGHT,
        maxViewportHeight,
        resizingCard.startHeight + heightDelta
      )
    );
    const targetSpan = Math.max(
      1,
      Math.min(cols, Math.round((nextWidth + columnGap) / (colWidth + columnGap)))
    );

    if (hasHorizontalResize) {
      resizingCard.card.style.gridColumn = `span ${targetSpan}`;
    }
    if (hasVerticalResize) {
      resizingCard.card.style.height = `${Math.round(nextHeight)}px`;
    }
    updateCardListHeights(resizingCard.card);
  });

  window.addEventListener("mouseup", () => {
    if (!resizingCard) return;
    clampCardSpan(resizingCard.card, getGridColumnCount(resizingCard.grid));
    updateCardListHeights(resizingCard.card);
    resizingCard.card.classList.remove("resizing");
    resizingCard.card.style.cursor = "grab";
    resizingCard.card.draggable = true;
    resizingCard = null;
    persistCardHeights();
    persistCardSpans();
  });

  window.addEventListener("resize", normalizeCardSpansToViewport);
  window.addEventListener("resize", normalizeCardHeightsToViewport);
  window.addEventListener("resize", updateAllCardListHeights);
}

function setupCardDragAndDrop() {
  const grid = byId("dashboardGrid");
  if (!grid) return;

  const cards = [...grid.querySelectorAll(".card[data-card-id]")];

  /* ── Desktop HTML5 drag ─────────────────────────────── */
  cards.forEach((card) => {
    card.addEventListener("dragstart", () => {
      if (resizingCard) {
        return;
      }
      draggingCardId = card.dataset.cardId;
      card.classList.add("dragging");
    });

    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      [...grid.querySelectorAll(".card")].forEach((item) =>
        item.classList.remove("drag-over")
      );
      draggingCardId = null;
      persistCardOrder();
    });

    card.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (!draggingCardId || draggingCardId === card.dataset.cardId) return;
      card.classList.add("drag-over");
    });

    card.addEventListener("dragleave", () => {
      card.classList.remove("drag-over");
    });

    card.addEventListener("drop", (event) => {
      event.preventDefault();
      card.classList.remove("drag-over");

      if (!draggingCardId || draggingCardId === card.dataset.cardId) return;

      const draggingCard = grid.querySelector(
        `.card[data-card-id="${draggingCardId}"]`
      );

      if (!draggingCard) return;

      grid.insertBefore(draggingCard, card);
      persistCardOrder();
    });
  });

  /* ── Mobile touch drag ──────────────────────────────── */
  let touchDragCard = null;
  let touchStartY = 0;
  let touchStartX = 0;
  let touchClone = null;
  let touchMoved = false;
  const TOUCH_DRAG_THRESHOLD = 15;

  cards.forEach((card) => {
    card.addEventListener("touchstart", (e) => {
      if (resizingCard) return;
      const touch = e.touches[0];
      touchStartX = touch.clientX;
      touchStartY = touch.clientY;
      touchDragCard = card;
      touchMoved = false;
    }, { passive: true });
  });

  grid.addEventListener("touchmove", (e) => {
    if (!touchDragCard) return;
    const touch = e.touches[0];
    const dx = touch.clientX - touchStartX;
    const dy = touch.clientY - touchStartY;

    if (!touchMoved && Math.abs(dx) + Math.abs(dy) < TOUCH_DRAG_THRESHOLD) return;
    touchMoved = true;
    e.preventDefault();

    if (!touchClone) {
      touchClone = touchDragCard.cloneNode(true);
      touchClone.classList.add("touch-drag-clone");
      touchClone.style.cssText = `
        position:fixed; z-index:9999; pointer-events:none;
        width:${touchDragCard.offsetWidth}px; opacity:0.85;
        transform:rotate(2deg); transition:none;
      `;
      document.body.appendChild(touchClone);
      touchDragCard.classList.add("dragging");
    }
    touchClone.style.left = `${touch.clientX - touchDragCard.offsetWidth / 2}px`;
    touchClone.style.top = `${touch.clientY - 30}px`;

    // Highlight drop target
    const target = document.elementFromPoint(touch.clientX, touch.clientY)?.closest(".card[data-card-id]");
    grid.querySelectorAll(".card").forEach((c) => c.classList.remove("drag-over"));
    if (target && target !== touchDragCard) target.classList.add("drag-over");
  }, { passive: false });

  grid.addEventListener("touchend", () => {
    if (!touchDragCard) return;

    if (touchClone) {
      touchClone.remove();
      touchClone = null;
    }
    touchDragCard.classList.remove("dragging");

    if (touchMoved) {
      const overCard = grid.querySelector(".card.drag-over");
      if (overCard && overCard !== touchDragCard) {
        grid.insertBefore(touchDragCard, overCard);
        persistCardOrder();
      }
      grid.querySelectorAll(".card").forEach((c) => c.classList.remove("drag-over"));
    }

    touchDragCard = null;
    touchMoved = false;
  });
}

/* ── Keyboard shortcuts ───────────────────────────────── */

const FOCUS_KEY = "ws_hidden_cards";
const ACCENT_KEY = "ws_accent_color";
let focusMode = false;

function getHiddenCards() {
  try { return new Set(JSON.parse(localStorage.getItem(FOCUS_KEY) || "[]")); }
  catch { return new Set(); }
}
function saveHiddenCards(set) {
  localStorage.setItem(FOCUS_KEY, JSON.stringify([...set]));
}

function toggleFocusMode() {
  focusMode = !focusMode;
  const grid = byId("dashboardGrid");
  if (!grid) return;
  const hidden = getHiddenCards();
  const btn = byId("focusModeBtn");

  grid.querySelectorAll(".card[data-card-id]").forEach((card) => {
    const cid = card.dataset.cardId;
    if (focusMode && hidden.has(cid)) {
      card.style.display = "none";
    } else {
      card.style.display = "";
    }
    // Show/hide eye icon on cards
    const eye = card.querySelector(".card-focus-toggle");
    if (eye) eye.style.display = focusMode ? "inline-block" : "none";
  });

  if (btn) btn.textContent = focusMode ? "👁️ Sair Focus" : "🎯 Focus";
  showToast(focusMode ? "Modo Focus ativado" : "Modo Focus desativado", "info");
}

function toggleCardVisibility(cardId) {
  const hidden = getHiddenCards();
  if (hidden.has(cardId)) hidden.delete(cardId);
  else hidden.add(cardId);
  saveHiddenCards(hidden);

  const card = document.querySelector(`.card[data-card-id="${cardId}"]`);
  if (card && focusMode) {
    card.style.display = hidden.has(cardId) ? "none" : "";
  }
  const eye = card?.querySelector(".card-focus-toggle");
  if (eye) eye.textContent = hidden.has(cardId) ? "👁️‍🗨️" : "👁️";
}

function injectFocusToggles() {
  const grid = byId("dashboardGrid");
  if (!grid) return;
  const hidden = getHiddenCards();
  grid.querySelectorAll(".card[data-card-id]").forEach((card) => {
    if (card.querySelector(".card-focus-toggle")) return;
    const cid = card.dataset.cardId;
    const btn = document.createElement("button");
    btn.className = "card-focus-toggle btn-small";
    btn.style.display = "none";
    btn.title = "Ocultar/mostrar este card no Focus mode";
    btn.textContent = hidden.has(cid) ? "👁️‍🗨️" : "👁️";
    btn.onclick = (e) => { e.stopPropagation(); toggleCardVisibility(cid); };
    const h2 = card.querySelector("h2");
    if (h2) h2.appendChild(btn);
  });
}

/* ── Accent Color ─────────────────────────────────────── */

function applyAccentColor(color) {
  if (!color) return;
  document.documentElement.style.setProperty("--accent", color);
  // Derive lighter/darker variants
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);
  document.documentElement.style.setProperty("--accent-light", `rgba(${r},${g},${b},0.15)`);
  document.documentElement.style.setProperty("--accent-glow", `rgba(${r},${g},${b},0.4)`);
  localStorage.setItem(ACCENT_KEY, color);
}

function initAccentColor() {
  const saved = localStorage.getItem(ACCENT_KEY);
  const picker = byId("accentColorPicker");
  if (saved) {
    applyAccentColor(saved);
    if (picker) picker.value = saved;
  }
  if (picker) {
    picker.addEventListener("input", (e) => applyAccentColor(e.target.value));
  }
}

function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Ctrl+K or Cmd+K → focus search
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault();
      const input = byId("searchInput");
      if (input) { input.focus(); input.select(); }
      return;
    }

    // Don't trigger shortcuts when typing in inputs
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;

    if (e.key === "r" || e.key === "R") {
      e.preventDefault();
      runNow();
    }

    if (e.key === "t" || e.key === "T") {
      e.preventDefault();
      toggleTheme();
    }

    if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      showToast("Ctrl+K = busca · R = atualizar · T = tema · F = focus · ? = atalhos", "info", 5000);
    }

    if (e.key === "f" || e.key === "F") {
      e.preventDefault();
      toggleFocusMode();
    }
  });
}

/* ── LLM Status Indicator ─────────────────────────────── */

let _llmPollTimer = null;
async function pollLLMStatus() {
  try {
    const resp = await fetch("/api/llm-status");
    if (!resp.ok) return;
    const data = await resp.json();
    const pill = document.getElementById("llmStatusPill");
    const label = document.getElementById("llmStatusLabel");
    if (!pill || !label) return;

    pill.classList.remove("llm-ok", "llm-error", "llm-disabled");
    if (data.status === "ok") {
      pill.classList.add("llm-ok");
      label.textContent = "Online";
    } else if (data.status === "disabled") {
      pill.classList.add("llm-disabled");
      label.textContent = "Off";
    } else {
      pill.classList.add("llm-error");
      label.textContent = "Offline";
    }
    pill.title = `LLM: ${data.status} — ${typeof data.detail === "object" ? JSON.stringify(data.detail) : data.detail || ""}`;
  } catch { /* ignore */ }
}
function scheduleLLMPolling() {
  if (_llmPollTimer) clearInterval(_llmPollTimer);
  pollLLMStatus();
  _llmPollTimer = setInterval(pollLLMStatus, 60_000);
}

/* ── Server-Sent Events (SSE) ────────────────────────── */

let _sseSource = null;
/* ── Smart Alerts (AI) ─────────────────────────────────── */

async function runSmartAnalysis() {
  const banner = byId("smartAlertsBanner");
  if (banner) banner.innerHTML = `<small style="color:var(--text-dim)">🧠 Analisando dados...</small>`;

  try {
    const res = await fetch("/api/smart-alerts/analyze", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      if (banner) banner.innerHTML = `<small style="color:var(--rose)">Erro: ${escapeHtml(data.error || "Falha")}</small>`;
      return;
    }
    renderSmartAlerts(data.alerts || []);
    showToast(`🧠 ${data.count || 0} alertas inteligentes gerados`, "info");
  } catch (err) {
    if (banner) banner.innerHTML = `<small style="color:var(--rose)">Erro de rede</small>`;
  }
}

function renderSmartAlerts(alerts) {
  const banner = byId("smartAlertsBanner");
  if (!banner) return;
  if (!alerts.length) {
    banner.innerHTML = `<small style="color:var(--text-dim)">✅ Nenhuma anomalia detectada</small>`;
    return;
  }

  const iconMap = { info: "ℹ️", success: "✅", warning: "⚠️", danger: "🚨" };
  banner.innerHTML = alerts.map(a => {
    const icon = iconMap[a.type] || "ℹ️";
    const typeClass = `alert-${a.type || "info"}`;
    return `
      <div class="smart-alert ${typeClass}">
        <span class="smart-alert-icon">${icon}</span>
        <div class="smart-alert-body">
          <div class="smart-alert-title">${escapeHtml(a.title)}</div>
          <div>${escapeHtml(a.message)}</div>
          ${a.ai_reason ? `<div class="smart-alert-reason">💡 ${escapeHtml(a.ai_reason)}</div>` : ""}
        </div>
      </div>
    `;
  }).join("");
}

/* ── SSE real-time connection ─────────────────────────── */

function connectSSE() {
  if (_sseSource) { _sseSource.close(); _sseSource = null; }
  if (typeof EventSource === "undefined") return;

  _sseSource = new EventSource("/api/stream");

  _sseSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "connected") return;
      if (data.type === "refresh") {
        showToast(data.message || "Dados atualizados", "info");
        fetchDashboard();
      }
      if (data.type === "alert") {
        showToast(data.message || "Novo alerta", "warning", 8000);
        fetchDashboard();
      }
      if (data.type === "price_alert") {
        showToast(`💰 ${data.message}`, "success", 10000);
      }
      if (data.type === "smart_alert") {
        showToast("🧠 Novos alertas inteligentes", "info", 6000);
        renderSmartAlerts(data.alerts || []);
        fetchDashboard();
      }
    } catch { /* ignore parse errors */ }
  };

  _sseSource.onerror = () => {
    _sseSource.close();
    _sseSource = null;
    // Retry after 30s
    setTimeout(connectSSE, 30_000);
  };
}

/* ── PWA: Register service worker ─────────────────────── */

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js").catch(() => {});
}

/* ── Bootstrap ────────────────────────────────────────── */

applyTheme(state.theme);
applyI18n();
initAccentColor();
setupEvents();
applySavedCardOrder();
applySavedCardHeights();
applySavedCardSpans();
applySavedCollapseState();
injectCardControls();
injectFocusToggles();
setupCardResize();
setupCardDragAndDrop();
setupKeyboardShortcuts();
normalizeCardHeightsToViewport();
normalizeCardSpansToViewport();
updateAllCardListHeights();
loadSavedFilters();
setupWebPush();
scheduleLLMPolling();
connectSSE();
flushOfflineQueue();
fetchDashboard();
scheduleDashboardPolling();
document.addEventListener("visibilitychange", () => {
  scheduleDashboardPolling();
});

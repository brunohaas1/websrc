const state = {
  snapshot: null,
  query: "",
  jobFilter: "",
  newsTopic: "",
  aiCategory: "",
  sortMode: "recency",
};

const CARD_ORDER_KEY = "dashboard-card-order-v2";
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
    target.innerHTML = "<small>Nenhum item no momento.</small>";
    return;
  }

  target.innerHTML = filteredAndSorted
    .map(
      (item) => `
        <article class="item">
          ${showImage && item.image_url ? `<img class="item-image" src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}" loading="lazy" />` : ""}
          ${buildItemBadges(item)}
          <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a>
          <div class="item-summary">${escapeHtml(toOneLineSummary(resolveItemSummary(item), summaryLength))}</div>
          <small>${escapeHtml(item.source ?? "fonte")} • ${fmtDate(item.published_at || item.created_at)}</small>
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
  target.innerHTML = limited
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
          <strong>${entry.source}</strong>
          <span>${entry.model_success_rate}% acerto modelo</span>
        </li>
      `
    )
    .join("");

  const fallbackRows = fallbackByHour
    .slice(0, 5)
    .map(
      (entry) => `
        <li>
          <strong>${entry.hour}</strong>
          <span>${entry.fallback_rate}% fallback (${entry.fallback}/${entry.total})</span>
        </li>
      `
    )
    .join("");

  const reasonRows = reasons
    .slice(0, 5)
    .map(
      (entry) => `
        <li>
          <strong>${entry.reason}</strong>
          <span>${entry.total} ocorrências</span>
        </li>
      `
    )
    .join("");

  target.innerHTML = `
    <div class="ai-metric-row">
      <span>Enriquecidos (24h)</span>
      <strong>${data.enriched_percent ?? 0}%</strong>
    </div>
    <div class="ai-metric-row">
      <span>Latência média IA</span>
      <strong>${Number.isFinite(data.avg_ai_latency_ms) ? `${data.avg_ai_latency_ms} ms` : "--"}</strong>
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
            <strong>${fmtDay(day.date)}</strong>
            <small>${weatherCodeLabel(day.weather_code)}</small>
          </div>
          <span class="weather-day-meta">
            ${day.temp_min ?? "--"}°C / ${day.temp_max ?? "--"}°C •
            Chuva ${day.precip_prob_max ?? "--"}% •
            Vento ${day.wind_speed_max ?? "--"} km/h
          </span>
        </article>
      `
    )
    .join("");

  target.innerHTML = `
    <div class="weather-now">
      <div class="weather-now-title">
        <strong>${city}</strong>
        <small>${weatherCodeLabel(current.weather_code)}</small>
      </div>
      <div class="weather-main-temp">${current.temperature_2m ?? "--"}°C</div>
      <small>
        Sensação ${current.apparent_temperature ?? "--"}°C •
        Umidade ${current.relative_humidity_2m ?? "--"}% •
        Chuva ${current.precipitation ?? "--"} mm •
        Vento ${current.wind_speed_10m ?? "--"} km/h
      </small>
    </div>
    <div class="weather-forecast">${forecastHtml || "<small>Sem previsão disponível.</small>"}</div>
  `;
}

function render() {
  const data = state.snapshot;
  if (!data) return;

  byId("countNews").textContent = String((data.news || []).length);
  byId("countPromo").textContent = String((data.promotions || []).length);
  byId("countJobs").textContent = String((data.jobs || []).length);
  byId("countVideos").textContent = String((data.videos || []).length);
  byId("lastUpdated").textContent = new Date().toLocaleTimeString("pt-BR");

  const aiMetrics = data.ai_observability || {};
  byId("aiEnrichedPct").textContent = `${aiMetrics.enriched_percent ?? 0}%`;
  byId("aiLatency").textContent = Number.isFinite(aiMetrics.avg_ai_latency_ms)
    ? `${aiMetrics.avg_ai_latency_ms} ms`
    : "--";
  const latestFallback = Array.isArray(aiMetrics.fallback_rate_by_hour)
    ? aiMetrics.fallback_rate_by_hour[0]
    : null;
  byId("aiFallbackHour").textContent = latestFallback
    ? `${latestFallback.fallback_rate}%`
    : "--";

  renderWeather(data.weather || []);
  renderResponsiveCollections(data);
  renderAIObservability(aiMetrics);

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
      alert(body.error || "Erro ao criar monitor de preço");
      return;
    }

    form.reset();
    await fetchDashboard();
  } catch (err) {
    console.error("Price watch error:", err);
    alert("Erro de rede ao criar monitor de preço");
  }
}

async function runNow() {
  try {
    const response = await fetch("/api/run-now", { method: "POST" });
    if (!response.ok) {
      console.error("run-now failed:", response.status);
    }
  } catch (err) {
    console.error("run-now error:", err);
  }
  await fetchDashboard();
}

function setupEvents() {
  byId("searchInput").addEventListener("input", (event) => {
    state.query = event.target.value.trim();
    render();
  });

  byId("priceForm").addEventListener("submit", addPriceWatch);
  byId("refreshBtn").addEventListener("click", runNow);

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
}

setupEvents();
applySavedCardOrder();
applySavedCardHeights();
applySavedCardSpans();
setupCardResize();
setupCardDragAndDrop();
normalizeCardHeightsToViewport();
normalizeCardSpansToViewport();
updateAllCardListHeights();
fetchDashboard();
scheduleDashboardPolling();
document.addEventListener("visibilitychange", () => {
  scheduleDashboardPolling();
});

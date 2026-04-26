/* Cache version – bump on deploy or use build hash */
const CACHE_VERSION = "v2-" + "20260426j";
const CACHE_NAME = "webdash-" + CACHE_VERSION;
const PRECACHE = [
  "/",
  "/finance",
  "/finance/registros",
  "/static/style.css",
  "/static/app.js",
  "/static/finance.css",
  "/static/finance.js",
  "/static/finance_shared.js",
  "/static/finance_flags.js",
  "/static/finance_history.js",
  "/static/finance_dividends.js",
  "/static/finance_settings.js",
  "/static/finance_ai.js",
  "/static/finance_bootstrap.js",
  "/static/finance_worker.js",
  "/static/finance_records.js",
  "/static/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Skip non-GET requests
  if (request.method !== "GET") return;

  // API requests: network-first with cache fallback
  if (request.url.includes("/api/")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Static assets: stale-while-revalidate
  event.respondWith(
    caches.match(request).then((cached) => {
      const fetchPromise = fetch(request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => cached);
      return cached || fetchPromise;
    })
  );
});

/* ── Web Push Notifications ───────────────────────────── */

self.addEventListener("push", (event) => {
  let data = { title: "WebSRC", body: "Novidade no dashboard!" };
  try {
    if (event.data) data = event.data.json();
  } catch {
    if (event.data) data.body = event.data.text();
  }

  const options = {
    body: data.body || "",
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    tag: data.tag || "websrc-notification",
    data: { url: data.url || "/" },
    vibrate: [100, 50, 100],
  };

  event.waitUntil(self.registration.showNotification(data.title || "WebSRC", options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url === url && "focus" in client) return client.focus();
      }
      return clients.openWindow(url);
    })
  );
});

/* ── Background Sync (offline queue) ──────────────────── */

self.addEventListener("sync", (event) => {
  if (event.tag === "offline-queue") {
    event.waitUntil(
      (async () => {
        // The main app.js flushes the queue on its own "online" event.
        // This is a fallback for browsers that support Background Sync.
        const allClients = await clients.matchAll();
        for (const client of allClients) {
          client.postMessage({ type: "flush-offline-queue" });
        }
      })()
    );
  }
});

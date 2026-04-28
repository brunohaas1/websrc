/**
 * finance_offline.js — PWA offline queue for cashflow entries.
 * Stores pending entries in IndexedDB when offline, syncs when back online.
 */

const _OFFLINE_DB_NAME = "finance_offline";
const _OFFLINE_DB_VERSION = 1;
const _OFFLINE_STORE = "pending_cashflow";

function _openOfflineDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(_OFFLINE_DB_NAME, _OFFLINE_DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(_OFFLINE_STORE)) {
        db.createObjectStore(_OFFLINE_STORE, { keyPath: "_local_id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function queueOfflineEntry(entry) {
  const db = await _openOfflineDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(_OFFLINE_STORE, "readwrite");
    const store = tx.objectStore(_OFFLINE_STORE);
    const record = { ...entry, _queued_at: new Date().toISOString() };
    const req = store.add(record);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function getOfflinePendingCount() {
  try {
    const db = await _openOfflineDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(_OFFLINE_STORE, "readonly");
      const req = tx.objectStore(_OFFLINE_STORE).count();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } catch {
    return 0;
  }
}

async function syncOfflineQueue() {
  if (!navigator.onLine) return;
  let db;
  try {
    db = await _openOfflineDb();
  } catch {
    return;
  }

  const records = await new Promise((resolve, reject) => {
    const tx = db.transaction(_OFFLINE_STORE, "readonly");
    const req = tx.objectStore(_OFFLINE_STORE).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  if (!records || records.length === 0) return;

  let synced = 0;
  let failed = 0;
  for (const record of records) {
    const { _local_id, _queued_at, ...entry } = record;
    try {
      const resp = await finFetch("/api/finance/cashflow", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(entry),
      });
      if (resp.ok) {
        await new Promise((resolve, reject) => {
          const tx = db.transaction(_OFFLINE_STORE, "readwrite");
          const req = tx.objectStore(_OFFLINE_STORE).delete(_local_id);
          req.onsuccess = resolve;
          req.onerror = () => reject(req.error);
        });
        synced++;
      } else {
        failed++;
      }
    } catch {
      failed++;
    }
  }

  if (synced > 0) {
    if (typeof refreshByDomains === "function") refreshByDomains(["cashflow"]);
    if (typeof showToast === "function") {
      showToast(`${synced} lançamento(s) sincronizado(s) do modo offline.`, "success");
    }
  }
  if (failed > 0 && typeof showToast === "function") {
    showToast(`${failed} lançamento(s) não puderam ser sincronizados. Verifique sua conexão.`);
  }
  updateOfflineBadge();
}

async function updateOfflineBadge() {
  const badge = document.getElementById("offlinePendingBadge");
  if (!badge) return;
  const count = await getOfflinePendingCount();
  if (count > 0) {
    badge.textContent = String(count);
    badge.style.display = "inline-block";
    badge.title = `${count} lançamento(s) pendente(s) para sincronizar`;
  } else {
    badge.style.display = "none";
    badge.textContent = "";
  }
}

window.addEventListener("online", syncOfflineQueue);
document.addEventListener("DOMContentLoaded", updateOfflineBadge);

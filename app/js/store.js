// Lokale Speicherung (IndexedDB) – Depotdaten verlassen das Gerät nur per Backup-Datei.
const DB_NAME = 'momentum-lab';
const DB_VERSION = 1;
export const STORES = ['kv', 'positions', 'transactions', 'plans', 'screenings', 'valuations'];
let dbp = null;

function req(r) {
  return new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
}
export function openDB() {
  if (dbp) return dbp;
  dbp = new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) { reject(new Error('IndexedDB nicht verfügbar')); return; }
    const r = indexedDB.open(DB_NAME, DB_VERSION);
    r.onupgradeneeded = () => {
      const db = r.result;
      if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv', { keyPath: 'key' });
      if (!db.objectStoreNames.contains('positions')) db.createObjectStore('positions', { keyPath: 'id' });
      if (!db.objectStoreNames.contains('transactions')) {
        const s = db.createObjectStore('transactions', { keyPath: 'id' });
        s.createIndex('positionId', 'positionId');
      }
      if (!db.objectStoreNames.contains('plans')) {
        const s = db.createObjectStore('plans', { keyPath: 'id' });
        s.createIndex('positionId', 'positionId');
      }
      if (!db.objectStoreNames.contains('screenings')) {
        const s = db.createObjectStore('screenings', { keyPath: 'id' });
        s.createIndex('createdAt', 'createdAt');
      }
      if (!db.objectStoreNames.contains('valuations')) db.createObjectStore('valuations', { keyPath: 'date' });
    };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.onblocked = () => reject(new Error('Datenbank blockiert – bitte App neu starten'));
  });
  return dbp;
}
async function tx(store, mode) {
  const db = await openDB();
  return db.transaction(store, mode).objectStore(store);
}
export const db = {
  async get(store, key) { return req((await tx(store, 'readonly')).get(key)); },
  async all(store) { return req((await tx(store, 'readonly')).getAll()); },
  async put(store, value) { const r = await req((await tx(store, 'readwrite')).put(value)); await markChange(store); return r; },
  async del(store, key) { const r = await req((await tx(store, 'readwrite')).delete(key)); await markChange(store); return r; },
  async clear(store) { return req((await tx(store, 'readwrite')).clear()); },
};

async function markChange(store) {
  if (store === 'kv' || store === 'valuations' || store === 'screenings') return;
  const s = await tx('kv', 'readwrite');
  const cur = (await req(s.get('changesSinceBackup')))?.value || 0;
  await req(s.put({ key: 'changesSinceBackup', value: cur + 1 }));
}
export async function getSetting(key, def = null) {
  const r = await db.get('kv', key);
  return r ? r.value : def;
}
export async function setSetting(key, value) {
  const s = await tx('kv', 'readwrite');
  return req(s.put({ key, value }));
}

export const DEFAULT_SETTINGS = {
  maxWeight: 0.2,          // Klumpenrisiko-Grenze für "Nachkaufen"
  taxAllowanceLeft: 1000,  // verbleibender Sparerpauschbetrag (Schätzung)
  churchTax: false,
  backupReminderDays: 14,
};
export async function loadSettings() {
  const s = { ...DEFAULT_SETTINGS };
  for (const k of Object.keys(DEFAULT_SETTINGS)) s[k] = await getSetting(k, DEFAULT_SETTINGS[k]);
  return s;
}

// ---------------------------------------------------------------- Backup
export const BACKUP_APP = 'momentum-lab';
export const BACKUP_SCHEMA = 1;

export async function exportBackup() {
  const data = {};
  for (const s of STORES) data[s] = await db.all(s);
  data.kv = data.kv.filter((r) => r.key !== 'changesSinceBackup');
  return { app: BACKUP_APP, schema: BACKUP_SCHEMA, exported_at: new Date().toISOString(), data };
}
export async function markBackupDone() {
  await setSetting('lastBackupAt', new Date().toISOString());
  await setSetting('changesSinceBackup', 0);
}

export function validateBackup(obj) {
  const errors = [];
  if (!obj || typeof obj !== 'object') return { ok: false, errors: ['Datei ist kein gültiges JSON-Objekt.'] };
  if (obj.app !== BACKUP_APP) errors.push('Datei stammt nicht aus Momentum Lab.');
  if (typeof obj.schema !== 'number' || obj.schema > BACKUP_SCHEMA) errors.push(`Unbekannte Backup-Version ${obj.schema}.`);
  const d = obj.data || {};
  const counts = {};
  for (const s of STORES) {
    if (d[s] !== undefined && !Array.isArray(d[s])) errors.push(`Bereich ${s} ist beschädigt.`);
    counts[s] = Array.isArray(d[s]) ? d[s].length : 0;
  }
  const posIds = new Set((d.positions || []).map((p) => p.id));
  for (const t of d.transactions || []) {
    if (!t.id || !t.positionId || !t.type || !t.date) { errors.push('Eine Transaktion ist unvollständig.'); break; }
    if (!posIds.has(t.positionId)) { errors.push('Eine Transaktion verweist auf eine unbekannte Position.'); break; }
  }
  return { ok: errors.length === 0, errors, counts, exported_at: obj.exported_at };
}

export async function importBackup(obj, mode = 'replace') {
  const v = validateBackup(obj);
  if (!v.ok) throw new Error(v.errors.join(' '));
  const database = await openDB();
  await new Promise((resolve, reject) => {
    const t = database.transaction(STORES, 'readwrite');
    t.oncomplete = resolve;
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error || new Error('Import abgebrochen'));
    for (const s of STORES) {
      const os = t.objectStore(s);
      if (mode === 'replace') os.clear();
      for (const rec of obj.data[s] || []) os.put(rec);
    }
  });
  await setSetting('changesSinceBackup', 0);
  return v.counts;
}

export async function wipeAll() {
  for (const s of STORES) await db.clear(s);
}

export async function storageInfo() {
  const out = { persisted: null, usage: null, quota: null, standalone: false };
  try { out.persisted = await navigator.storage?.persisted?.(); } catch { /* nicht unterstützt */ }
  try { const e = await navigator.storage?.estimate?.(); if (e) { out.usage = e.usage; out.quota = e.quota; } } catch { /* */ }
  out.standalone = window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone === true;
  return out;
}
export async function requestPersist() {
  try { return await navigator.storage?.persist?.(); } catch { return false; }
}

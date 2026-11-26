// Laden der vom täglichen Datenlauf erzeugten Dateien (gleicher Server, keine Fremdanbieter).
import { daysBetween, todayISO } from './fmt.js';
import { applyHiddenScreen, applyHiddenStage2, getHidden } from './hidden.js';

export const SUPPORTED_SCHEMA = 1;
const base = () => new URL('data/', document.baseURI);
const memo = new Map();

export class DataError extends Error {
  constructor(message, kind = 'netz') { super(message); this.kind = kind; }
}

export async function getJSON(name, { fresh = false, timeout = 20000 } = {}) {
  const url = new URL(name, base());
  if (fresh) url.searchParams.set('t', Date.now());
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(url, { cache: fresh ? 'no-store' : 'default', signal: ctrl.signal });
  } catch (e) {
    throw new DataError(e.name === 'AbortError' ? `Zeitüberschreitung beim Laden von ${name}` : `Keine Verbindung (${name})`, 'netz');
  } finally { clearTimeout(timer); }
  if (res.status === 404) throw new DataError(`${name} existiert noch nicht – der erste Datenlauf ist evtl. noch nicht fertig.`, 'fehlt');
  if (!res.ok) throw new DataError(`${name}: Server antwortet mit ${res.status}`, 'netz');
  try { return await res.json(); } catch { throw new DataError(`${name} ist beschädigt (kein gültiges JSON).`, 'format'); }
}

export async function loadStatus(fresh = false) {
  const s = await getJSON('status.json', { fresh });
  memo.set('status', s);
  return s;
}
export function cachedStatus() { return memo.get('status') || null; }

export function parseScreen(raw) {
  const required = ['schema', 'asof', 'fields', 'rows', 'candidates', 'methodology_version', 'status'];
  const missing = required.filter((k) => !(k in raw));
  if (missing.length) throw new DataError(`Screening-Daten unvollständig (fehlt: ${missing.join(', ')})`, 'format');
  if (raw.schema > SUPPORTED_SCHEMA) throw new DataError(`Datenformat ${raw.schema} ist neuer als diese App – bitte App aktualisieren.`, 'format');
  const F = raw.fields;
  const rows = raw.rows.map((r) => Object.fromEntries(F.map((f, i) => [f, r[i]])));
  const bySymbol = new Map(rows.map((r) => [r.symbol, r]));
  const bad = raw.candidates.filter((c) => !bySymbol.has(c));
  if (bad.length) throw new DataError(`Kandidaten ohne Datenzeile: ${bad.join(', ')}`, 'format');
  return { ...raw, rows, bySymbol };
}
export async function loadScreen(fresh = false) {
  if (!fresh && memo.has('screen')) return memo.get('screen');
  const s = applyHiddenScreen(parseScreen(await getJSON('screen.json', { fresh, timeout: 30000 })), await getHidden());
  memo.set('screen', s);
  return s;
}
export function cachedScreen() { return memo.get('screen') || null; }
/** Nach Ein-/Ausblenden einer Aktie: Listen neu aufbauen. */
export async function refreshHidden() {
  const h = await getHidden();
  if (memo.has('screen')) memo.set('screen', applyHiddenScreen(memo.get('screen'), h));
  if (memo.has('stage2raw')) memo.set('stage2', applyHiddenStage2(memo.get('stage2raw'), h));
}

export async function loadDetail(symbol) {
  const fn = `details/${symbol.replace(/[^A-Za-z0-9._-]/g, '_')}.json`;
  if (memo.has(fn)) return memo.get(fn);
  const d = await getJSON(fn);
  memo.set(fn, d);
  return d;
}
export async function loadBacktest() {
  if (memo.has('bt')) return memo.get('bt');
  const b = await getJSON('backtest.json', { timeout: 30000 });
  memo.set('bt', b);
  return b;
}
export async function loadMonthly() {
  if (memo.has('monthly')) return memo.get('monthly');
  const m = await getJSON('monthly.json', { timeout: 30000 });
  memo.set('monthly', m);
  return m;
}
export async function loadMethodology() {
  if (memo.has('meth')) return memo.get('meth');
  const m = await getJSON('methodology.json');
  memo.set('meth', m);
  return m;
}
/* Stage 2 (Fortsetzungsanalyse). Fehlt die Datei (älterer Datenlauf), liefert die Funktion null statt eines Fehlers. */
export function parseStage2(raw) {
  if (!raw || typeof raw !== 'object') throw new DataError('Stage-2-Daten fehlen.', 'format');
  if (raw.schema > 2) throw new DataError(`Stage-2-Format ${raw.schema} ist neuer als diese App – bitte App aktualisieren.`, 'format');
  const ranking = Array.isArray(raw.ranking) ? raw.ranking : [];
  const bySymbol = new Map(ranking.map((r) => [r.symbol, r]));
  const all = new Map();
  const F = raw.all?.fields || [];
  for (const row of raw.all?.rows || []) {
    const o = Object.fromEntries(F.map((f, i) => [f, row[i]]));
    all.set(o.symbol, o);
  }
  return { ...raw, ranking, bySymbol, allBySymbol: all, buy: raw.buy || [], messages: raw.messages || [] };
}
export async function loadStage2(fresh = false) {
  if (!fresh && memo.has('stage2')) return memo.get('stage2');
  let s;
  try {
    s = parseStage2(await getJSON('stage2.json', { fresh, timeout: 30000 }));
  } catch (e) {
    if (e instanceof DataError && e.kind === 'fehlt') s = null; else throw e;
  }
  memo.set('stage2raw', s);
  s = applyHiddenStage2(s, await getHidden());
  memo.set('stage2', s);
  return s;
}
export function cachedStage2() { return memo.has('stage2') ? memo.get('stage2') : undefined; }
export async function loadSimulator(fresh = false) {
  if (!fresh && memo.has('simulator')) return memo.get('simulator');
  let a;
  try {
    a = await getJSON('simulator.json', { fresh, timeout: 60000 });
    if (!a || typeof a !== 'object' || !Array.isArray(a.signal_dates)) a = null;
  } catch (e) {
    if (e instanceof DataError && e.kind === 'fehlt') a = null; else throw e;
  }
  memo.set('simulator', a);
  return a;
}
export function clearMemo() { memo.clear(); }

/* Aktualität: Kalendertage zwischen Datenstand (letzter Handelstag) und heute.
   <= 3 Tage: aktuell (Wochenende) · 4–6: leicht veraltet · 7–10: veraltet (keine Empfehlung als aktuell) · > 10: zu alt (Abbruch) */
export function freshness(asof, today = todayISO()) {
  if (!asof) return { level: 'unbekannt', age: null, label: 'Datenstand unbekannt', ok: false, abort: true };
  const age = daysBetween(asof, today);
  if (age <= 3) return { level: 'aktuell', age, label: 'aktuell', ok: true, abort: false };
  if (age <= 6) return { level: 'leicht veraltet', age, label: `${age} Tage alt`, ok: true, abort: false };
  if (age <= 10) return { level: 'veraltet', age, label: `${age} Tage alt`, ok: false, abort: false };
  return { level: 'zu alt', age, label: `${age} Tage alt`, ok: false, abort: true };
}

export const REASON_FALLBACK = {
  no_data: 'Keine Kursdaten', stale: 'Kurse veraltet', short_history: 'Historie < 2 Jahre', gaps: 'Datenlücken',
  jump: 'Unplausibler Kurssprung', adj_ratio: 'Anpassungsfehler', liquidity: 'Zu geringe Liquidität',
  zero_volume: 'Kein Umsatz', penny: 'Kurs < 1 €', crosscheck: 'Abweichung zur Zweitquelle', currency: 'Währung unbekannt',
  no_vol: 'Volatilität fehlt', duplicate: 'Doppelte Aktiengattung', watchlist: 'Beobachtungsliste',
};
export function reasonText(code, screen) {
  return screen?.reason_text?.[code] || REASON_FALLBACK[code] || code;
}

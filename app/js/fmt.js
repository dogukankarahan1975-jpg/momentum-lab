// Formatierung (de-DE) und Eingabe-Parsing (Komma oder Punkt als Dezimaltrenner)
const cache = new Map();
function nf(min, max, style = 'decimal', currency) {
  const key = `${min}|${max}|${style}|${currency || ''}`;
  if (!cache.has(key)) {
    const opts = { minimumFractionDigits: min, maximumFractionDigits: max };
    if (style === 'currency') { opts.style = 'currency'; opts.currency = currency; }
    cache.set(key, new Intl.NumberFormat('de-DE', opts));
  }
  return cache.get(key);
}
export const ok = (x) => x !== null && x !== undefined && Number.isFinite(Number(x));

export function fmtNum(x, d = 2) { return ok(x) ? nf(d, d).format(x) : '–'; }
export function fmtQty(x) {
  if (!ok(x)) return '–';
  const a = Math.abs(x);
  return nf(0, a < 1 ? 6 : a < 100 ? 4 : 2).format(x);
}
export function fmtEUR(x, d = 2) { return ok(x) ? nf(d, d, 'currency', 'EUR').format(Math.abs(x) < 0.5 * 10 ** -d ? 0 : x) : '–'; }
export function fmtMoney(x, cur = 'EUR', d = 2) {
  if (!ok(x)) return '–';
  try { return nf(d, d, 'currency', cur || 'EUR').format(x); } catch { return `${fmtNum(x, d)} ${cur}`; }
}
export function fmtPrice(x, cur) {
  if (!ok(x)) return '–';
  const d = Math.abs(x) >= 1000 ? 0 : Math.abs(x) >= 10 ? 2 : 3;
  return fmtMoney(x, cur, d);
}
export function fmtPct(x, d = 1, sign = true) {
  if (!ok(x)) return '–';
  const v = x * 100;
  return `${sign && v > 0.0000001 ? '+' : ''}${nf(d, d).format(v)} %`;
}
export function fmtSigned(x, d = 2) {
  if (!ok(x)) return '–';
  return `${x > 0 ? '+' : ''}${nf(d, d).format(x)}`;
}
export function fmtCompact(x) {
  if (!ok(x)) return '–';
  const a = Math.abs(x);
  if (a >= 1e12) return `${nf(1, 1).format(x / 1e12)} Bio.`;
  if (a >= 1e9) return `${nf(1, 1).format(x / 1e9)} Mrd.`;
  if (a >= 1e6) return `${nf(1, 1).format(x / 1e6)} Mio.`;
  if (a >= 1e3) return `${nf(0, 0).format(x / 1e3)} Tsd.`;
  return nf(0, 0).format(x);
}
export function fmtDate(iso) {
  if (!iso) return '–';
  const d = new Date(`${String(iso).slice(0, 10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? '–' : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}
export function fmtDateTime(isoTs) {
  if (!isoTs) return '–';
  const d = new Date(isoTs);
  return Number.isNaN(d.getTime()) ? '–' : d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
export function fmtRankPct(p) {
  if (!ok(p)) return '–';
  const v = p * 100;
  return `Top ${nf(v < 10 ? 1 : 0, v < 10 ? 1 : 0).format(Math.max(v, 0.1))} %`;
}
export function cls(x) { return !ok(x) ? '' : x > 0 ? 'pos' : x < 0 ? 'neg' : ''; }

export function parseDec(s) {
  if (typeof s === 'number') return s;
  let t = String(s ?? '').trim().replace(/[\s €$£¥]/g, '');
  if (!t) return NaN;
  if (t.includes(',') && t.includes('.')) {
    t = t.lastIndexOf(',') > t.lastIndexOf('.') ? t.replace(/\./g, '').replace(',', '.') : t.replace(/,/g, '');
  } else {
    t = t.replace(',', '.');
  }
  if (!/^[-+]?\d*\.?\d+(e[-+]?\d+)?$/i.test(t)) return NaN;
  return Number(t);
}
export function todayISO(d = new Date()) {
  const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return z.toISOString().slice(0, 10);
}
export function daysBetween(aIso, bIso) {
  const a = new Date(`${aIso}T12:00:00`), b = new Date(`${bIso}T12:00:00`);
  return Math.round((b - a) / 86400000);
}
export function addMonths(iso, n, day) {
  const [y, m, d] = iso.split('-').map(Number);
  const target = new Date(Date.UTC(y, m - 1 + n, 1));
  const dim = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(day ?? d, dim));
  return target.toISOString().slice(0, 10);
}
export function addDays(iso, n) {
  const t = new Date(`${iso}T12:00:00Z`);
  t.setUTCDate(t.getUTCDate() + n);
  return t.toISOString().slice(0, 10);
}
export function uid() {
  if (crypto?.randomUUID) return crypto.randomUUID();
  return 'id-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

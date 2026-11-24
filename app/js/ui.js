// Kleine UI-Bausteine. Alle externen Texte (z. B. Nachrichten) werden über html`` escaped.
import { fmtRankPct } from './fmt.js';

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(String(s ?? ''));
function val(v) {
  if (v === null || v === undefined || v === false) return '';
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(val).join('');
  return esc(v);
}
export function html(strings, ...vals) {
  let out = strings[0];
  for (let i = 0; i < vals.length; i++) out += val(vals[i]) + strings[i + 1];
  return new Raw(out);
}
export function safeUrl(u) {
  try { const x = new URL(u, location.href); return ['http:', 'https:'].includes(x.protocol) ? x.href : '#'; } catch { return '#'; }
}

export const SIGNALS = {
  'VERKAUF': { cls: 'b-sell', rank: 1 },
  'VERKAUF PRÜFEN': { cls: 'b-check', rank: 2 },
  'SPARPLAN STOPPEN': { cls: 'b-stop', rank: 3 },
  'NACHKAUFEN': { cls: 'b-buy', rank: 4 },
  'SPARPLAN FORTSETZEN': { cls: 'b-cont', rank: 5 },
  'HALTEN': { cls: 'b-hold', rank: 6 },
  'KEINE BEWERTUNG': { cls: 'b-none', rank: 7 },
  'KAUF-KANDIDAT': { cls: 'b-cand', rank: 8 },
  'TOP PICK': { cls: 'b-top', rank: 0 },
};
export function badge(sig) {
  const s = SIGNALS[sig] || { cls: 'b-none' };
  return html`<span class="badge ${s.cls}">${sig}</span>`;
}
export function srcTag(type, label) {
  const map = { official: 'offiziell', database: 'Datenbank', secondary: 'Sekundärquelle', calc: 'berechnet', demo: 'DEMO' };
  return html`<span class="src ${type}">${label || map[type] || type}</span>`;
}
export function note(level, text, icon) {
  const ic = icon || { info: 'i', warn: '!', error: '×', ok: '✓' }[level] || 'i';
  return html`<div class="note ${level}"><span class="ic">${ic}</span><div>${text}</div></div>`;
}
export function empty(title, text, action = '') {
  return html`<div class="empty"><h3>${title}</h3><p>${text}</p>${action}</div>`;
}
export const chevron = raw('<svg class="chev" width="8" height="14" viewBox="0 0 8 14" aria-hidden="true"><path d="M1 1l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>');

/* Halteband: Perzentil 0 (beste) bis 1. Zonen: Kauf (Top-10-Grenze), Halten (bis holdMax), Prüfen, Verkauf (> sellPct). */
export function holdBand(pct, { buyPct = 0.01, holdMax = 0.2, sellPct = 0.5, prevPct = null, label = true } = {}) {
  const W = 300, H = 30, y = 12, h = 8;
  const x = (p) => 4 + Math.min(Math.max(p, 0), 1) * (W - 8);
  const zones = [
    [0, buyPct, 'var(--good)', 0.9],
    [buyPct, holdMax, 'var(--good)', 0.35],
    [holdMax, sellPct, 'var(--warn)', 0.3],
    [sellPct, 1, 'var(--critical)', 0.28],
  ];
  let s = `<svg class="band" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Position im Ranking: ${pct == null ? 'ohne Rang' : fmtRankPct(pct)}">`;
  for (const [a, b, c, o] of zones) {
    s += `<rect x="${x(a)}" y="${y}" width="${Math.max(x(b) - x(a) - 1.5, 1)}" height="${h}" rx="2" fill="${c}" opacity="${o}"/>`;
  }
  if (prevPct != null && Number.isFinite(prevPct)) {
    s += `<circle cx="${x(prevPct)}" cy="${y + h / 2}" r="3.2" fill="none" stroke="var(--ink-3)" stroke-width="1.5"/>`;
  }
  if (pct != null && Number.isFinite(pct)) {
    const px = x(pct);
    s += `<rect x="${px - 2}" y="${y - 7}" width="4" height="${h + 14}" rx="2" fill="var(--brass)" stroke="var(--ground)" stroke-width="1.5"/>`;
  }
  s += '</svg>';
  const leg = label ? `<div class="band-legend"><span>Kauf</span><span>Halten bis ${Math.round(holdMax * 100)} %</span><span>Prüfen</span><span>Verkauf</span></div>` : '';
  return raw(s + leg);
}

let toastTimer;
export function toast(text, ms = 2600) {
  const root = document.getElementById('toast-root');
  root.innerHTML = `<div class="toast-wrap"><div class="toast" role="status">${esc(text)}</div></div>`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { root.innerHTML = ''; }, ms);
}

export function openSheet({ title, body, onMount, wide = false }) {
  const root = document.getElementById('sheet-root');
  const wrap = document.createElement('div');
  wrap.className = 'sheet-backdrop';
  wrap.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-label="${esc(title)}">
    <div class="sheet-grip"></div>
    <div class="sheet-head"><h2>${esc(title)}</h2><button class="icon-btn" data-close aria-label="Schließen">✕</button></div>
    <div class="sheet-body">${body}</div></div>`;
  const close = () => { wrap.remove(); document.body.style.overflow = ''; };
  wrap.addEventListener('click', (e) => { if (e.target === wrap || e.target.closest('[data-close]')) close(); });
  root.appendChild(wrap);
  document.body.style.overflow = 'hidden';
  if (onMount) onMount(wrap.querySelector('.sheet-body'), close);
  if (wide) wrap.querySelector('.sheet').style.maxWidth = '900px';
  return close;
}

export function confirmDialog({ title, text, confirm = 'Bestätigen', danger = false, requireText = null }) {
  return new Promise((resolve) => {
    let done = false;
    const body = `<p>${esc(text)}</p>
      ${requireText ? `<label class="field"><span>Zur Bestätigung „${esc(requireText)}“ eintippen</span><input data-req autocomplete="off"></label>` : ''}
      <div class="btn-row"><button class="btn" data-no>Abbrechen</button><button class="btn ${danger ? 'danger' : 'primary'}" data-yes ${requireText ? 'disabled' : ''}>${esc(confirm)}</button></div>`;
    const close = openSheet({
      title, body, onMount: (el, closeFn) => {
        const yes = el.querySelector('[data-yes]');
        el.querySelector('[data-no]').onclick = () => { done = true; closeFn(); resolve(false); };
        yes.onclick = () => { done = true; closeFn(); resolve(true); };
        const req = el.querySelector('[data-req]');
        if (req) req.oninput = () => { yes.disabled = req.value.trim() !== requireText; };
      },
    });
    const obs = new MutationObserver(() => {
      if (!document.querySelector('.sheet-backdrop')) { obs.disconnect(); if (!done) resolve(false); }
    });
    obs.observe(document.getElementById('sheet-root'), { childList: true });
    void close;
  });
}

export function onDelegate(root, event, selector, fn) {
  root.addEventListener(event, (e) => {
    const t = e.target.closest(selector);
    if (t && root.contains(t)) fn(e, t);
  });
}

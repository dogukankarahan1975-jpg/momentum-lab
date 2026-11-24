// Schlanke SVG-Diagramme ohne externe Bibliothek: Linien (optional log), Fläche, Balken, Mini-Linie.
// Dünne Linien, zurückhaltendes Raster, Legende + Endbeschriftung, Fadenkreuz mit Tooltip.
import { esc } from './ui.js';

export const SERIES_COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)'];
const NS = 'http://www.w3.org/2000/svg';

function niceStep(range, target) {
  const raw = range / Math.max(target, 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const n = raw / mag;
  return (n >= 5 ? 10 : n >= 2 ? 5 : n >= 1 ? 2 : 1) * mag;
}
function ticks(min, max, target = 4) {
  if (!(max > min)) return [min];
  const step = niceStep(max - min, target);
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}
const toMs = (d) => (typeof d === 'number' ? d : new Date(`${String(d).slice(0, 10)}T12:00:00`).getTime());
function bisect(xs, x) {
  let lo = 0, hi = xs.length - 1;
  if (x <= xs[0]) return 0;
  if (x >= xs[hi]) return hi;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
  return x - xs[lo] < xs[hi] - x ? lo : hi;
}

export function lineChart(el, opts) {
  const { height = 220, log = false, yFmt = (v) => v.toFixed(0), tipFmt = yFmt, area = false, zero = false,
    endLabels = true, xIsYear = true } = opts;
  const series = opts.series.filter((s) => s.points?.length > 1).map((s) => ({
    ...s, xs: s.points.map((p) => toMs(p[0])), ys: s.points.map((p) => p[1]),
  }));
  el.classList.add('chart');
  if (!series.length) { el.innerHTML = '<p class="muted small">Keine Daten für das Diagramm.</p>'; return; }
  const W = Math.max(el.clientWidth || 340, 260);
  const H = height;
  const showEnd = endLabels && series.length <= 4;
  const pad = { l: 46, r: showEnd ? 62 : 12, t: 10, b: 24 };
  const tf = (v) => (log ? Math.log10(Math.max(v, 1e-9)) : v);
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  for (const s of series) {
    xmin = Math.min(xmin, s.xs[0]); xmax = Math.max(xmax, s.xs[s.xs.length - 1]);
    for (const y of s.ys) if (Number.isFinite(y) && (!log || y > 0)) { ymin = Math.min(ymin, tf(y)); ymax = Math.max(ymax, tf(y)); }
  }
  if (zero) { ymin = Math.min(ymin, 0); ymax = Math.max(ymax, 0); }
  const yr = ymax - ymin || 1;
  ymin -= yr * 0.05; ymax += yr * 0.05;
  const X = (x) => pad.l + ((x - xmin) / (xmax - xmin || 1)) * (W - pad.l - pad.r);
  const Y = (v) => pad.t + (1 - (tf(v) - ymin) / (ymax - ymin)) * (H - pad.t - pad.b);
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', opts.label || 'Diagramm');
  let g = '';
  // y-Raster
  let yt;
  if (log) {
    const lo = 10 ** ymin, hi = 10 ** ymax;
    const cands = [];
    for (let e = Math.floor(ymin) - 1; e <= Math.ceil(ymax); e++) for (const m of [1, 2, 5]) cands.push(m * 10 ** e);
    yt = cands.filter((v) => v >= lo && v <= hi);
    if (yt.length > 6) yt = yt.filter((v, i) => i % 2 === 0);
  } else yt = ticks(ymin, ymax, 4);
  for (const v of yt) {
    const y = Y(v);
    g += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" stroke="var(--line-soft)" stroke-width="1"/>`;
    g += `<text x="${pad.l - 6}" y="${y + 4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${esc(yFmt(v))}</text>`;
  }
  if (zero) g += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--ink-3)" stroke-width="1"/>`;
  // x-Achse (Jahre)
  const y0 = new Date(xmin).getFullYear(), y1 = new Date(xmax).getFullYear();
  const span = y1 - y0;
  if (xIsYear && span >= 2) {
    const every = span > 16 ? 5 : span > 8 ? 2 : 1;
    for (let y = y0 + 1; y <= y1; y++) {
      if ((y - (y0 + 1)) % every !== 0) continue;
      const x = X(new Date(`${y}-01-01T00:00:00`).getTime());
      if (x < pad.l + 10 || x > W - pad.r - 10) continue;
      g += `<line x1="${x}" x2="${x}" y1="${H - pad.b}" y2="${H - pad.b + 4}" stroke="var(--line)"/>`;
      g += `<text x="${x}" y="${H - 6}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${y}</text>`;
    }
  } else {
    const n = Math.min(4, Math.floor((W - pad.l - pad.r) / 80));
    for (let i = 0; i <= n; i++) {
      const xm = xmin + (i / n) * (xmax - xmin);
      const d = new Date(xm);
      g += `<text x="${X(xm)}" y="${H - 6}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${d.toLocaleDateString('de-DE', { month: '2-digit', year: '2-digit' })}</text>`;
    }
  }
  // Linien
  const ends = [];
  series.forEach((s, i) => {
    const color = s.color || SERIES_COLORS[i % SERIES_COLORS.length];
    let d = '';
    let pen = false;
    for (let k = 0; k < s.xs.length; k++) {
      const v = s.ys[k];
      if (!Number.isFinite(v) || (log && v <= 0)) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${X(s.xs[k]).toFixed(1)},${Y(v).toFixed(1)}`;
      pen = true;
    }
    if (area && i === 0) {
      const base = zero ? Y(0) : H - pad.b;
      g += `<path d="${d}L${X(s.xs[s.xs.length - 1]).toFixed(1)},${base}L${X(s.xs[0]).toFixed(1)},${base}Z" fill="${color}" opacity=".16"/>`;
    }
    g += `<path d="${d}" fill="none" stroke="${color}" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round" ${s.dash ? `stroke-dasharray="${s.dash}"` : ''}/>`;
    const lastK = s.ys.length - 1;
    if (Number.isFinite(s.ys[lastK])) ends.push({ y: Y(s.ys[lastK]), name: s.short || s.name, color });
  });
  if (showEnd && ends.length) {
    ends.sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 13) ends[i].y = ends[i - 1].y + 13;
    for (const e of ends) {
      g += `<circle cx="${W - pad.r}" cy="${e.y}" r="3" fill="${e.color}" stroke="var(--surface)" stroke-width="2"/>`;
      g += `<text x="${W - pad.r + 7}" y="${e.y + 4}" font-size="11" fill="var(--ink-2)">${esc(String(e.name).slice(0, 9))}</text>`;
    }
  }
  g += `<line class="xh" x1="0" x2="0" y1="${pad.t}" y2="${H - pad.b}" stroke="var(--ink-3)" stroke-width="1" opacity="0"/>`;
  svg.innerHTML = g;
  el.innerHTML = '';
  el.appendChild(svg);
  const tip = document.createElement('div');
  tip.className = 'tip';
  el.appendChild(tip);
  const xh = svg.querySelector('.xh');
  const allX = series[0].xs;
  const move = (clientX) => {
    const rect = svg.getBoundingClientRect();
    const px = ((clientX - rect.left) / rect.width) * W;
    if (px < pad.l || px > W - pad.r) { hide(); return; }
    const xv = xmin + ((px - pad.l) / (W - pad.l - pad.r)) * (xmax - xmin);
    const k0 = bisect(allX, xv);
    const xs = X(allX[k0]);
    xh.setAttribute('x1', xs); xh.setAttribute('x2', xs); xh.setAttribute('opacity', '0.7');
    let rows = `<div class="muted">${new Date(allX[k0]).toLocaleDateString('de-DE')}</div>`;
    series.forEach((s, i) => {
      const k = bisect(s.xs, xv);
      if (Math.abs(s.xs[k] - xv) > 40 * 86400000 && s.xs.length > 50) return;
      const color = s.color || SERIES_COLORS[i % SERIES_COLORS.length];
      rows += `<div><span class="dot" style="background:${color}"></span> ${esc(s.short || s.name)}: <b>${esc(tipFmt(s.ys[k]))}</b></div>`;
    });
    tip.innerHTML = rows;
    tip.style.display = 'block';
    const left = Math.min(Math.max((xs / W) * rect.width, 80), rect.width - 80);
    tip.style.left = `${left}px`;
  };
  const hide = () => { tip.style.display = 'none'; xh.setAttribute('opacity', '0'); };
  svg.addEventListener('pointermove', (e) => move(e.clientX));
  svg.addEventListener('pointerdown', (e) => move(e.clientX));
  svg.addEventListener('pointerleave', hide);
  svg.addEventListener('touchmove', (e) => { if (e.touches[0]) move(e.touches[0].clientX); }, { passive: true });
}

/* Jahresrenditen als divergierende Balken (blau = positiv, rot = negativ), Tooltip beim Antippen */
export function barChart(el, { labels, values, height = 180, fmt = (v) => `${(v * 100).toFixed(1)} %` }) {
  el.classList.add('chart');
  const W = Math.max(el.clientWidth || 340, 260), H = height;
  const pad = { l: 40, r: 8, t: 8, b: 22 };
  const vals = values.map((v) => (Number.isFinite(v) ? v : 0));
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const Y = (v) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * (H - pad.t - pad.b);
  const bw = (W - pad.l - pad.r) / labels.length;
  let g = '';
  for (const t of ticks(lo, hi, 4)) {
    g += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="var(--line-soft)"/>`;
    g += `<text x="${pad.l - 6}" y="${Y(t) + 4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${esc(fmt(t).replace(/\.0 %/, ' %'))}</text>`;
  }
  labels.forEach((lab, i) => {
    const v = vals[i];
    const x = pad.l + i * bw + 1;
    const y = Math.min(Y(v), Y(0));
    const h = Math.max(Math.abs(Y(v) - Y(0)), 1);
    g += `<rect data-i="${i}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(bw - 2, 1).toFixed(1)}" height="${h.toFixed(1)}" rx="${Math.min(3, bw / 4)}" fill="${v >= 0 ? 'var(--s1)' : '#e66767'}"/>`;
    const every = labels.length > 16 ? 5 : labels.length > 8 ? 2 : 1;
    if (i % every === 0) g += `<text x="${(x + bw / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle" font-size="10.5" fill="var(--ink-3)">${esc(String(lab).slice(-2) === lab ? lab : `'${String(lab).slice(-2)}`)}</text>`;
  });
  g += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--ink-3)"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Jahresrenditen">${g}</svg><div class="tip"></div>`;
  const tip = el.querySelector('.tip');
  el.querySelector('svg').addEventListener('pointerdown', (e) => {
    const r = e.target.closest('rect[data-i]');
    if (!r) { tip.style.display = 'none'; return; }
    const i = +r.dataset.i;
    tip.innerHTML = `${esc(labels[i])}: <b>${esc(fmt(values[i]))}</b>`;
    tip.style.display = 'block';
    tip.style.left = `${Math.min(Math.max(((pad.l + (i + 0.5) * bw) / W) * el.clientWidth, 60), el.clientWidth - 60)}px`;
  });
}

export function sparkline(values, { w = 72, h = 24 } = {}) {
  const v = values.filter(Number.isFinite);
  if (v.length < 2) return '';
  const lo = Math.min(...v), hi = Math.max(...v);
  const pts = v.map((y, i) => `${((i / (v.length - 1)) * w).toFixed(1)},${(h - 2 - ((y - lo) / (hi - lo || 1)) * (h - 4)).toFixed(1)}`).join(' ');
  const up = v[v.length - 1] >= v[0];
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${up ? 'var(--pos)' : 'var(--neg)'}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
}

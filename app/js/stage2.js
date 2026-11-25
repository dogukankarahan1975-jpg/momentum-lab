// Stage 2 (Fortsetzungsanalyse): Beschriftungen, Abzeichen, Skalen und Kennzahl-Formatierung.
// Die Berechnung passiert im nächtlichen Datenlauf (pipeline/stage2.py). Die App zeigt nur an.
import { fmtNum, fmtPct, fmtSigned, ok } from './fmt.js';
import { html, raw } from './ui.js';

export const DECISIONS = {
  EXCEPTIONAL: { label: 'EXCEPTIONAL', cls: 'd-exc', rank: 0 },
  STRONG_BUY: { label: 'STRONG BUY CANDIDATE', cls: 'd-strong', rank: 1 },
  WATCHLIST: { label: 'WATCHLIST', cls: 'd-watch', rank: 2 },
  NO_ENTRY: { label: 'NO ENTRY', cls: 'd-noentry', rank: 3 },
  REJECT: { label: 'REJECT', cls: 'd-reject', rank: 4 },
  HARD_RISK: { label: 'HARD RISK', cls: 'd-hard', rank: 5 },
  INSUFFICIENT_DATA: { label: 'INSUFFICIENT DATA', cls: 'd-insuf', rank: 6 },
};
export const RISKS = {
  NORMAL: { label: 'Risiko NORMAL', cls: 'r-normal' }, ELEVATED: { label: 'Risiko ELEVATED', cls: 'r-elev' },
  HIGH: { label: 'Risiko HIGH', cls: 'r-high' }, CRITICAL: { label: 'Risiko CRITICAL', cls: 'r-crit' },
};
export const DQS = {
  HIGH: { label: 'Daten HIGH', cls: 'q-high' }, MEDIUM: { label: 'Daten MEDIUM', cls: 'q-med' },
  LOW: { label: 'Daten LOW', cls: 'q-low' }, INSUFFICIENT: { label: 'Daten INSUFFICIENT', cls: 'q-insuf' },
};
export const OUTPERF = {
  HIGH: { label: 'HIGH OUTPERFORMANCE POTENTIAL', short: 'Outperformance HIGH', cls: 'o-high' },
  MODERATE: { label: 'MODERATE OUTPERFORMANCE POTENTIAL', short: 'Outperformance MODERATE', cls: 'o-mod' },
  MARKET_LIKE: { label: 'MARKET-LIKE POTENTIAL', short: 'Marktähnlich', cls: 'o-market' },
  LOW: { label: 'LOW OUTPERFORMANCE POTENTIAL', short: 'Outperformance LOW', cls: 'o-low' },
  INSUFFICIENT: { label: 'INSUFFICIENT DATA', short: 'Outperformance n. v.', cls: 'o-insuf' },
};
export const CAT_ORDER = ['A', 'B', 'C', 'D', 'E', 'F'];

export function decisionBadge(code) {
  const d = DECISIONS[code];
  return d ? html`<span class="badge ${d.cls}">${d.label}</span>` : html`<span class="badge b-none">–</span>`;
}
export function riskBadge(level) {
  const r = RISKS[level];
  return r ? html`<span class="badge ${r.cls}">${r.label}</span>` : '';
}
export function dqBadge(level) {
  const q = DQS[level];
  return q ? html`<span class="badge ${q.cls}">${q.label}</span>` : '';
}
export function outBadge(level, long = false) {
  const o = OUTPERF[level];
  return o ? html`<span class="badge ${o.cls}">${long ? o.label : o.short}</span>` : '';
}

/* Score 0–10 mit Entscheidungszonen. Zonen: unter 6 REJECT, 6–7,5 NO ENTRY, 7,5–8,5 WATCHLIST, 8,5–9 STRONG BUY, ab 9 EXCEPTIONAL. */
export function scoreScale(score, { thresholds = [6, 7.5, 8.5, 9], label = true } = {}) {
  const W = 300, H = 26, y = 10, h = 7;
  const x = (v) => 3 + (Math.min(Math.max(v, 0), 10) / 10) * (W - 6);
  const [t1, t2, t3, t4] = thresholds;
  const zones = [[0, t1, 'var(--serious)', 0.22], [t1, t2, 'var(--ink-3)', 0.22], [t2, t3, 'var(--ice)', 0.28],
    [t3, t4, 'var(--good)', 0.38], [t4, 10, 'var(--good)', 0.75]];
  let s = `<svg class="sscale" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Stage-2-Score ${ok(score) ? fmtNum(score, 1) : 'nicht berechenbar'} von 10">`;
  for (const [a, b, c, o] of zones) s += `<rect x="${x(a)}" y="${y}" width="${Math.max(x(b) - x(a) - 1.5, 1)}" height="${h}" rx="2" fill="${c}" opacity="${o}"/>`;
  if (ok(score)) {
    const px = x(score);
    s += `<rect x="${px - 2}" y="${y - 6}" width="4" height="${h + 12}" rx="2" fill="var(--ink)" stroke="var(--ground)" stroke-width="1.5"/>`;
  }
  s += '</svg>';
  const leg = label ? `<div class="sscale-legend"><span>0</span><span style="left:${t1 * 10}%">${fmtNum(t1, 0)}</span><span style="left:${t2 * 10}%">${fmtNum(t2, 1)}</span><span style="left:${t3 * 10}%">${fmtNum(t3, 1)}</span><span style="left:${t4 * 10}%">${fmtNum(t4, 0)}</span><span style="left:100%">10</span></div>` : '';
  return raw(s + leg);
}

/* Profil der sechs Kategorien als Mini-Säulen (eine Farbe, Höhe = Score). Fehlende Kategorie = gestrichelt. */
export function profile(categories, { w = 132, h = 30 } = {}) {
  const n = CAT_ORDER.length, gap = 4;
  const bw = (w - gap * (n - 1)) / n;
  let s = `<svg class="profile" width="${w}" height="${h + 12}" viewBox="0 0 ${w} ${h + 12}" role="img" aria-label="Kategorie-Profil: ${CAT_ORDER.map((c) => `${c} ${ok(categories?.[c]?.score) ? fmtNum(categories[c].score, 1) : 'fehlt'}`).join(', ')}">`;
  CAT_ORDER.forEach((c, i) => {
    const v = categories?.[c]?.score;
    const x0 = i * (bw + gap);
    s += `<rect x="${x0}" y="0" width="${bw}" height="${h}" rx="3" fill="var(--raised)"/>`;
    if (ok(v)) {
      const hh = Math.max(2, (v / 10) * h);
      s += `<rect x="${x0}" y="${h - hh}" width="${bw}" height="${hh}" rx="3" fill="var(--ice)" opacity="${0.35 + 0.65 * (v / 10)}"/>`;
    } else {
      s += `<rect x="${x0 + 0.75}" y="0.75" width="${bw - 1.5}" height="${h - 1.5}" rx="3" fill="none" stroke="var(--ink-3)" stroke-dasharray="3 2"/>`;
    }
    s += `<text x="${x0 + bw / 2}" y="${h + 10}" text-anchor="middle" font-size="9.5" fill="var(--ink-3)">${c}</text>`;
  });
  return raw(`${s}</svg>`);
}

export function bar10(score) {
  if (!ok(score)) return html`<span class="bar10 empty" aria-hidden="true"></span>`;
  return html`<span class="bar10" aria-hidden="true"><span style="width:${Math.max(2, score * 10)}%"></span></span>`;
}

/* Kennzahl formatieren (Format kommt aus der Methodik-Definition). */
export function fmtMetric(v, fmt) {
  if (v === true) return 'ja';
  if (v === false) return 'nein';
  if (!ok(v)) return '–';
  switch (fmt) {
    case 'pct': return fmtPct(v, 1);
    case 'share': return fmtPct(v, 0, false);
    case 'share_signed': return fmtSigned(v, 2);
    case 'x': return `${fmtNum(v, 1)}×`;
    case 'pp': return `${fmtSigned(v * 100, 1)} Pp.`;
    case 'ratio': return `${fmtPct(v - 1, 1)} vom Hoch`;
    default: return fmtNum(v, 2);
  }
}

export function stage2Usable(s2, screen, fr) {
  if (!s2) return { ok: false, reason: 'Stage 2 wird beim nächsten Datenlauf zum ersten Mal berechnet.' };
  if (s2.status === 'fehler') return { ok: false, reason: s2.messages?.[0]?.text || 'Stage 2 konnte nicht berechnet werden.' };
  if (screen && s2.asof !== screen.asof) return { ok: false, reason: `Stage 2 hat einen anderen Datenstand (${s2.asof}) als Stage 1 (${screen.asof}).` };
  if (fr && !fr.ok) return { ok: false, reason: `Die Daten sind ${fr.label}. Es gibt keine aktuelle Sparplan-Entscheidung.` };
  return { ok: true, reason: '' };
}

export function decisionCounts(s2) {
  const c = {};
  for (const r of s2?.ranking || []) { const k = r.decision?.code || '–'; c[k] = (c[k] || 0) + 1; }
  return c;
}

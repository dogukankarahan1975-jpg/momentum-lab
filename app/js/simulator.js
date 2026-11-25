// Backtest-Simulator: rechnet Sparpläne mit echten historischen Kursen und den damals sichtbaren Screening-Listen.
// Datenquelle: simulator.json (Pipeline). Reine Rechenlogik, im Browser und in Node testbar.

export const STRATEGIES = {
  world: { label: 'MSCI World ETF-Sparplan', short: 'MSCI World', kind: 'etf', bench: 'msci_world' },
  sp500: { label: 'S&P 500 ETF-Sparplan', short: 'S&P 500', kind: 'etf', bench: 'sp500' },
  s1top5: { label: 'Stage 1: Top-5-Liste', short: 'Top 5', kind: 'list', n: 5, list: 'cand' },
  s1top10: { label: 'Stage 1: Top-10-Liste', short: 'Top 10', kind: 'list', n: 10, list: 'cand' },
  s2: { label: 'Stage 2 (Kursteil): Risiko normal und Outperformance hoch', short: 'Stage 2', kind: 'list', n: null, list: 's2' },
};

export const DEFAULTS = {
  startYear: 2011, budget: 500, dyn: 2, feeBuy: 1, feeSell: 1, feeEtf: 0, spread: 0.2, spreadEtf: 0.1,
  hold: 'signal', rest: 'etf', strategies: ['world', 'sp500', 's1top5', 's1top10', 's2'],
};

export const HOLD_LABEL = { signal: 'bis zum ersten Verkaufssignal der App', 6: 'immer 6 Monate', 12: 'immer 12 Monate' };
export const REST_LABEL = {
  etf: 'Rest fließt in den MSCI World ETF',
  cash: 'Rest bleibt auf dem Konto (0 % Zins) und wird im nächsten Monat mit angelegt',
  top: 'Immer die Bestplatzierten kaufen, auch ohne Kandidatenstatus',
};

const TAX = 0.26375;
const ALLOWANCE = 1000;
const ETF_EXEMPT = 0.3;

const yearOf = (iso) => Number(iso.slice(0, 4));

export function startIndex(data, year) {
  const i = data.signal_dates.findIndex((d) => yearOf(d) >= year);
  return i < 0 ? 0 : i;
}

function newBook() {
  return {
    cash: 0, lots: new Map(), etfUnits: 0, etfBasis: 0, gains: {}, carry: 0, taxedThrough: null,
    contrib: 0, fees: 0, spreadCost: 0, taxes: 0, trades: 0, hcount: new Map(), yearly: {}, flows: [],
  };
}

function buyStock(b, sym, amount, px, o, k) {
  if (!(px > 0) || amount <= o.feeBuy) return false;
  const sc = amount * (o.spread / 200);
  const shares = (amount - o.feeBuy - sc) / px;
  if (!b.lots.has(sym)) b.lots.set(sym, []);
  b.lots.get(sym).push({ shares, basis: amount, k });
  b.cash -= amount; b.fees += o.feeBuy; b.spreadCost += sc; b.trades += 1;
  return true;
}

function sellLots(b, sym, px, o, year, pred = () => true) {
  const lots = b.lots.get(sym) || [];
  const keep = [];
  let shares = 0, basis = 0;
  for (const l of lots) { if (pred(l)) { shares += l.shares; basis += l.basis; } else keep.push(l); }
  if (!shares || !(px > 0)) return false;
  const gross = shares * px;
  const sc = gross * (o.spread / 200);
  const proceeds = gross - sc - o.feeSell;
  b.cash += proceeds; b.fees += o.feeSell; b.spreadCost += sc; b.trades += 1;
  b.gains[year] = (b.gains[year] || 0) + (proceeds - basis);
  if (keep.length) b.lots.set(sym, keep); else { b.lots.delete(sym); b.hcount.delete(sym); }
  return true;
}

function buyEtf(b, amount, px, o) {
  if (!(px > 0) || amount <= o.feeEtf) return false;
  const sc = amount * (o.spreadEtf / 200);
  b.etfUnits += (amount - o.feeEtf - sc) / px;
  b.etfBasis += amount; b.cash -= amount; b.fees += o.feeEtf; b.spreadCost += sc; b.trades += 1;
  return true;
}

function settle(b, year) {
  // Steuer für abgeschlossene Jahre (Aktien-Verlusttopf, Pauschbetrag je Jahr), Zahlung aus dem Konto
  if (b.taxedThrough === null) b.taxedThrough = year - 1;
  for (let y = b.taxedThrough + 1; y < year; y++) {
    const g = (b.gains[y] || 0) + b.carry;
    if (g <= 0) { b.carry = g; continue; }
    b.carry = 0;
    const tax = Math.max(0, g - ALLOWANCE) * TAX;
    b.cash -= tax; b.taxes += tax;
    if (b.yearly[y]) b.yearly[y].tax += tax;
  }
  b.taxedThrough = Math.max(b.taxedThrough, year - 1);
}

function lastPx(data, i, k) {
  const row = data.px[i];
  for (let j = k; j >= 0; j--) if (row[j] > 0) return row[j];
  return null;
}

function stockValue(b, data, k, idx) {
  let v = 0;
  for (const [sym, lots] of b.lots) {
    const px = lastPx(data, idx.get(sym), k) || 0;
    for (const l of lots) v += l.shares * px;
  }
  return v;
}

function etfPx(data, k) {
  const s = data.bench?.msci_world?.px;
  return s ? s[k] : null;
}

/** Simuliert eine Strategie. Liefert Monatswerte, Kennzahlen und Jahresprotokoll. */
export function simulate(data, key, opts) {
  const o = { ...DEFAULTS, ...opts };
  const st = STRATEGIES[key];
  const idx = new Map(data.syms.map((s, i) => [s, i]));
  const k0 = startIndex(data, o.startYear);
  const K = data.signal_dates.length;
  const b = newBook();
  const series = [];
  const twr = [1];
  let prevVal = null, peak = 1, maxDD = 0;
  for (let k = k0; k < K; k++) {
    const date = data.points[k];
    const year = yearOf(date);
    settle(b, year);
    const budget = o.budget * Math.pow(1 + o.dyn / 100, Math.floor((k - k0) / 12));
    b.cash += budget; b.contrib += budget;
    b.flows.push([k, -budget]);
    if (!b.yearly[year]) b.yearly[year] = { contrib: 0, tax: 0, trades0: b.trades, value: 0, holdings: [], buys: [], sells: [] };
    b.yearly[year].contrib += budget;
    if (st.kind === 'etf') {
      const px = data.bench?.[st.bench]?.px?.[k];
      if (px > 0) {
        const sc = b.cash * (o.spreadEtf / 200);
        b.etfUnits += (b.cash - o.feeEtf - sc) / px; b.etfBasis += b.cash; b.fees += o.feeEtf; b.spreadCost += sc; b.trades += 1;
        b.cash = 0;
      }
    } else {
      // 1) Verkäufe
      const cur = (st.list === 's2' ? data.s2[k] : data.cand[k]) || [];
      let target = st.n ? cur.slice(0, st.n) : cur.slice();
      if (o.rest === 'top' && st.n && target.length < st.n) target = (data.rank[k] || []).slice(0, st.n);
      if (o.rest === 'top' && !st.n && !target.length) target = (data.cand[k] || []).slice(0, 5);
      const targetSyms = new Set(target.map((i) => data.syms[i]));
      for (const sym of [...b.lots.keys()]) {
        const i = idx.get(sym);
        const px = data.px[i][k];
        if (o.hold === 'signal') {
          const c = data.hold[k][i];
          const cond = c === '1' || c === '3';
          const n = cond ? (b.hcount.get(sym) || 0) + 1 : 0;
          b.hcount.set(sym, n);
          if ((cond && n >= 2) || c === '2') {
            if (sellLots(b, sym, px, o, year)) b.yearly[year].sells.push(sym);
          }
        } else {
          const h = Number(o.hold);
          const due = (l) => k - l.k >= h;
          if (targetSyms.has(sym)) {
            for (const l of b.lots.get(sym)) if (due(l)) l.k = k; // noch auf der Liste: weiter halten
          } else if ((b.lots.get(sym) || []).some(due)) {
            if (sellLots(b, sym, px, o, year, due)) b.yearly[year].sells.push(sym);
          }
        }
      }
      // 2) Käufe zu gleichen Teilen
      const slots = st.n || Math.max(target.length, 1);
      const invest = Math.max(0, b.cash);
      const each = invest / slots;
      let used = 0;
      for (const i of target) {
        const sym = data.syms[i];
        if (buyStock(b, sym, each, data.px[i][k], o, k)) { used += 1; b.yearly[year].buys.push(sym); }
      }
      const restShare = invest - used * each;
      if (restShare > 1 && o.rest === 'etf') buyEtf(b, restShare, etfPx(data, k), o);
    }
    const v = st.kind === 'etf'
      ? b.cash + b.etfUnits * (data.bench?.[st.bench]?.px?.[k] || 0)
      : b.cash + stockValue(b, data, k, idx) + b.etfUnits * (etfPx(data, k) || 0);
    if (prevVal !== null && prevVal > 0) {
      const r = (v - budget) / prevVal;
      const t = twr[twr.length - 1] * r;
      twr.push(t); peak = Math.max(peak, t); maxDD = Math.min(maxDD, t / peak - 1);
    }
    prevVal = v;
    series.push([date, v, b.contrib]);
    b.yearly[year].value = v;
    b.yearly[year].holdings = [...b.lots.keys()].map((sym) => data.names[idx.get(sym)]);
    b.yearly[year].etf = b.etfUnits > 0;
  }
  // Endbewertung am letzten Kurstag
  const kEnd = data.points.length - 1;
  const pxEtf = st.kind === 'etf' ? data.bench?.[st.bench]?.px?.[kEnd] : etfPx(data, kEnd);
  let stockVal = 0, unrealStock = 0;
  for (const [sym, lots] of b.lots) {
    const px = lastPx(data, idx.get(sym), kEnd) || 0;
    for (const l of lots) { stockVal += l.shares * px; unrealStock += l.shares * px - l.basis; }
  }
  const etfVal = b.etfUnits * (pxEtf || 0);
  const final = b.cash + stockVal + etfVal;
  series.push([data.points[kEnd], final, b.contrib]);
  // Steuer bei Verkauf am Ende
  const endYear = yearOf(data.points[kEnd]);
  settle(b, endYear);
  const akt = (b.gains[endYear] || 0) + b.carry + unrealStock;
  const etfGain = (etfVal - b.etfBasis) * (1 - ETF_EXEMPT);
  const base = Math.max(0, akt) + etfGain;
  const endTax = Math.max(0, base - ALLOWANCE) * TAX;
  const afterTax = final - endTax;
  const years = (Date.parse(data.points[kEnd]) - Date.parse(data.points[k0])) / (365.25 * 864e5);
  const holdingsEnd = [...b.lots.keys()].map((s) => data.names[idx.get(s)]);
  if (b.yearly[endYear]) b.yearly[endYear].holdings = holdingsEnd;
  const ys = Object.keys(b.yearly).map(Number).sort((a, c) => a - c);
  ys.forEach((y, j) => { b.yearly[y].trades = (j + 1 < ys.length ? b.yearly[ys[j + 1]].trades0 : b.trades) - b.yearly[y].trades0; });
  b.yearly[endYear] && (b.yearly[endYear].value = final);
  return {
    key, label: st.label, short: st.short, series, contrib: b.contrib, final, afterTax, endTax,
    taxesPaid: b.taxes, fees: b.fees, spreadCost: b.spreadCost, trades: b.trades, maxDD, years,
    irr: irr(b.flows, k0, kEnd, final, data), irrAfter: irr(b.flows, k0, kEnd, afterTax, data),
    yearly: b.yearly, holdingsEnd, start: data.points[k0], end: data.points[kEnd],
  };
}

/** Interner Zinsfuß p. a. (Einzahlungen monatlich, Endwert am letzten Tag). */
export function irr(flows, k0, kEnd, finalValue, data) {
  if (!(finalValue > 0) || !flows.length) return null;
  const t = (k) => (Date.parse(data.points[k]) - Date.parse(data.points[k0])) / (365.25 * 864e5);
  const T = t(kEnd);
  const npv = (r) => flows.reduce((s, [k, cf]) => s + cf * Math.pow(1 + r, T - t(k)), 0) + finalValue;
  let lo = -0.99, hi = 2;
  if (npv(lo) * npv(hi) > 0) return null;
  for (let it = 0; it < 120; it++) {
    const mid = (lo + hi) / 2;
    if (npv(lo) * npv(mid) <= 0) hi = mid; else lo = mid;
  }
  return (lo + hi) / 2;
}

/** Liste eines Monats so, wie das Screening sie damals gezeigt hätte. */
export function monthList(data, k) {
  const cand = new Set(data.cand[k]);
  const s2 = new Set(data.s2[k]);
  const s2n = new Set(data.s2_normal?.[k] || []);
  return (data.rank[k] || []).map((i, r) => ({
    rank: r + 1, symbol: data.syms[i], name: data.names[i], sector: data.sectors[i],
    cand: cand.has(i), s2: s2.has(i), riskNormal: s2n.has(i),
  }));
}

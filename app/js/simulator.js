// Backtest-Simulator: rechnet Sparpläne mit echten historischen Kursen und den damals sichtbaren Screening-Listen.
// Datenquelle: simulator.json (Pipeline). Reine Rechenlogik, im Browser und in Node testbar.

export const STRATEGIES = {
  world: { label: 'MSCI World ETF-Sparplan', short: 'MSCI World', kind: 'etf', bench: 'msci_world' },
  sp500: { label: 'S&P 500 ETF-Sparplan', short: 'S&P 500', kind: 'etf', bench: 'sp500' },
  s1top5: { label: 'Stage 1: Top-5-Liste', short: 'Top 5', kind: 'list', n: 5, list: 'cand' },
  s1top10: { label: 'Stage 1: Top-10-Liste', short: 'Top 10', kind: 'list', n: 10, list: 'cand' },
  s2: { label: 'Stage 2 (Kursteil): nur Aktien mit Risiko normal und Outperformance hoch', short: 'Stage 2', kind: 'list', n: null, list: 's2' },
};

export const DEFAULTS = {
  startYear: 2011, budget: 500, dyn: 2, feeBuy: 1, feeSell: 1, feeEtf: 0, spread: 0.2, spreadEtf: 0.1,
  hold: 'signal', rest: 'etf', budgetMode: 'reinvest', strategies: ['world', 'sp500', 's1top5', 's1top10', 's2'],
};

export const HOLD_LABEL = { signal: 'bis zum ersten Verkaufssignal der App', 6: 'immer 6 Monate', 12: 'immer 12 Monate' };
export const BUDGET_LABEL = {
  reinvest: 'Monatsbudget plus Verkaufserlöse werden angelegt',
  fixed: 'Nur das feste Monatsbudget wird angelegt, Verkaufserlöse bleiben auf dem Konto',
};
export const REST_LABEL = {
  etf: 'Rest fließt in den MSCI World ETF',
  cash: 'Rest bleibt auf dem Konto (0 % Zins) und wird im nächsten Monat mit angelegt',
  top: 'Immer die Bestplatzierten kaufen, auch ohne Kandidatenstatus',
};

const TAX = 0.26375;
const ALLOWANCE = 1000;
const ETF_EXEMPT = 0.3;

const yearOf = (iso) => Number(iso.slice(0, 4));
const eur = (x) => `${x.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const dmy = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;

export function startIndex(data, year) {
  const i = data.signal_dates.findIndex((d) => yearOf(d) >= year);
  return i < 0 ? 0 : i;
}

function newBook() {
  return {
    cash: 0, lots: new Map(), etfUnits: 0, etfBasis: 0, gains: {}, carry: 0, taxedThrough: null,
    contrib: 0, fees: 0, spreadCost: 0, taxes: 0, trades: 0, hcount: new Map(), yearly: {}, flows: [], log: [], months: [],
  };
}

function buyStock(b, data, i, amount, px, o, k, why) {
  if (!(px > 0) || amount <= o.feeBuy) return false;
  const sym = data.syms[i];
  const sc = amount * (o.spread / 200);
  const shares = (amount - o.feeBuy - sc) / px;
  if (!b.lots.has(sym)) b.lots.set(sym, []);
  b.lots.get(sym).push({ shares, basis: amount, k, px });
  b.cash -= amount; b.fees += o.feeBuy; b.spreadCost += sc; b.trades += 1;
  b.log.push({ k, type: 'Kauf', sym, name: data.names[i], px, shares, amount, fee: o.feeBuy, spread: sc, why, cash: b.cash });
  return true;
}

function sellLots(b, data, i, px, o, k, year, why, pred = () => true) {
  const sym = data.syms[i];
  const lots = b.lots.get(sym) || [];
  const keep = [];
  let shares = 0, basis = 0, firstK = null;
  for (const l of lots) {
    if (pred(l)) { shares += l.shares; basis += l.basis; firstK = firstK === null ? l.k : Math.min(firstK, l.k); } else keep.push(l);
  }
  if (!shares || !(px > 0)) return false;
  const gross = shares * px;
  const sc = gross * (o.spread / 200);
  const proceeds = gross - sc - o.feeSell;
  b.cash += proceeds; b.fees += o.feeSell; b.spreadCost += sc; b.trades += 1;
  b.gains[year] = (b.gains[year] || 0) + (proceeds - basis);
  if (keep.length) b.lots.set(sym, keep); else { b.lots.delete(sym); b.hcount.delete(sym); }
  b.log.push({ k, type: 'Verkauf', sym, name: data.names[i], px, shares, amount: proceeds, basis, gain: proceeds - basis,
    buyPx: basis / shares, firstK, fee: o.feeSell, spread: sc, why, cash: b.cash });
  return true;
}

function buyEtf(b, amount, px, o, k, why) {
  if (!(px > 0) || amount <= o.feeEtf) return false;
  const sc = amount * (o.spreadEtf / 200);
  const units = (amount - o.feeEtf - sc) / px;
  b.etfUnits += units;
  b.etfBasis += amount; b.cash -= amount; b.fees += o.feeEtf; b.spreadCost += sc; b.trades += 1;
  b.log.push({ k, type: 'ETF-Kauf', sym: 'ETF', name: why.name, px, shares: units, amount, fee: o.feeEtf, spread: sc, why: why.text, cash: b.cash });
  return true;
}

function settle(b, year, k) {
  // Abgeltungsteuer für abgeschlossene Jahre (Aktien-Verlusttopf, Pauschbetrag je Jahr), Zahlung vom Konto
  if (b.taxedThrough === null) b.taxedThrough = year - 1;
  let paid = 0;
  for (let y = b.taxedThrough + 1; y < year; y++) {
    const gain = b.gains[y] || 0;
    const g = gain + b.carry;
    if (g <= 0) {
      if (gain) b.log.push({ k, type: 'Steuer', name: `Abrechnung ${y}`, amount: 0, why: `Ergebnis ${y}: ${eur(gain)}. Kein Gewinn, also keine Steuer. Verlustvortrag jetzt ${eur(g)}`, cash: b.cash });
      b.carry = g; continue;
    }
    b.carry = 0;
    const tax = Math.max(0, g - ALLOWANCE) * TAX;
    b.cash -= tax; b.taxes += tax; paid += tax;
    if (b.yearly[y]) b.yearly[y].tax += tax;
    b.log.push({ k, type: 'Steuer', name: `Abrechnung ${y}`, amount: tax, why: `Gewinne ${y} nach Verlustverrechnung ${eur(g)}, minus 1.000 € Pauschbetrag, davon 26,375 %`, cash: b.cash });
  }
  b.taxedThrough = Math.max(b.taxedThrough, year - 1);
  return paid;
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

/** Liste, die eine Strategie im Monat k kaufen würde. */
export function targetList(data, key, k, rest) {
  const st = STRATEGIES[key];
  if (st.list === 's2') return (data.s2[k] || []).slice(); // nur echte Stage-2-Treffer, sonst nichts
  let t = (data.cand[k] || []).slice(0, st.n);
  if (rest === 'top' && t.length < st.n) t = (data.rank[k] || []).slice(0, st.n);
  return t;
}

/** Simuliert eine Strategie. Liefert Monatswerte, Kennzahlen, Jahres- und Transaktionsprotokoll. */
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
  const worldName = data.bench?.msci_world?.name || 'MSCI World ETF';
  for (let k = k0; k < K; k++) {
    const date = data.points[k];
    const year = yearOf(date);
    if (!b.yearly[year]) b.yearly[year] = { contrib: 0, tax: 0, trades0: b.trades, value: 0, holdings: [], buys: [], sells: [] };
    const taxPaid = st.kind === 'etf' ? 0 : settle(b, year, k);
    const budget = o.budget * Math.pow(1 + o.dyn / 100, Math.floor((k - k0) / 12));
    const cashBefore = b.cash;
    b.cash += budget; b.contrib += budget;
    b.flows.push([k, -budget]);
    b.yearly[year].contrib += budget;
    const m = { k, budget, carried: cashBefore + taxPaid, tax: taxPaid, proceeds: 0, invest: 0, each: 0, n: 0, bought: [], sold: [] };
    if (st.kind === 'etf') {
      // reiner Sparplan: jeden Monat kaufen, nie verkaufen
      const px = data.bench?.[st.bench]?.px?.[k];
      if (px > 0) {
        const sc = b.cash * (o.spreadEtf / 200);
        const units = (b.cash - o.feeEtf - sc) / px;
        b.log.push({ k, type: 'ETF-Kauf', sym: 'ETF', name: data.bench[st.bench].name, px, shares: units, amount: b.cash, fee: o.feeEtf, spread: sc, why: 'Sparrate', cash: 0 });
        b.etfUnits += units; b.etfBasis += b.cash; b.fees += o.feeEtf; b.spreadCost += sc; b.trades += 1;
        m.invest = b.cash; b.cash = 0;
      }
    } else {
      const target = targetList(data, key, k, o.rest);
      const targetSyms = new Set(target.map((i) => data.syms[i]));
      // 1) Verkäufe
      const cashPreSell = b.cash;
      for (const sym of [...b.lots.keys()]) {
        const i = idx.get(sym);
        const px = data.px[i][k];
        if (o.hold === 'signal') {
          const c = data.hold[k][i];
          const cond = c === '1' || c === '3';
          const n = cond ? (b.hcount.get(sym) || 0) + 1 : 0;
          b.hcount.set(sym, n);
          if ((cond && n >= 2) || c === '2') {
            const why = c === '2' ? 'Verkaufssignal sofort (Rang unter Median oder 12 M unter −10 %)'
              : c === '3' ? 'Datenproblem / nicht mehr im Universum (2. Monat)' : 'Verkaufssignal: 2. Monatsende außerhalb der besten 20 %';
            if (sellLots(b, data, i, px, o, k, year, why)) { b.yearly[year].sells.push(sym); m.sold.push(data.names[i]); }
          }
        } else {
          const h = Number(o.hold);
          const due = (l) => k - l.k >= h;
          if (targetSyms.has(sym)) {
            for (const l of b.lots.get(sym)) if (due(l)) l.k = k; // noch auf der Liste: weiter halten
          } else if ((b.lots.get(sym) || []).some(due)) {
            if (sellLots(b, data, i, px, o, k, year, `Haltedauer ${h} Monate erreicht, nicht mehr auf der Liste`, due)) {
              b.yearly[year].sells.push(sym); m.sold.push(data.names[i]);
            }
          }
        }
      }
      m.proceeds = b.cash - cashPreSell;
      // 2) Anlagebetrag: fest = nur Monatsbudget; mit Erlösen = alles verfügbare Geld
      const avail = Math.max(0, b.cash);
      const invest = o.budgetMode === 'fixed' ? Math.min(budget, avail) : avail;
      const slots = st.n || target.length;
      m.invest = invest; m.n = target.length;
      if (slots > 0 && invest > 0) {
        const each = invest / slots;
        m.each = each;
        let used = 0;
        for (const i of target) {
          if (buyStock(b, data, i, each, data.px[i][k], o, k, `auf der Liste vom ${dmy(data.signal_dates[k])}`)) {
            used += 1; b.yearly[year].buys.push(data.syms[i]); m.bought.push(data.names[i]);
          }
        }
        const rest = invest - used * each;
        if (rest > 1 && o.rest === 'etf') buyEtf(b, rest, etfPx(data, k), o, k, { name: worldName, text: `${slots - used} freie Plätze` });
      } else if (invest > 1 && o.rest === 'etf') {
        buyEtf(b, invest, etfPx(data, k), o, k, { name: worldName, text: 'kein Kandidat in diesem Monat' });
      }
    }
    m.cashAfter = b.cash;
    b.months.push(m);
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
    b.yearly[year].cash = b.cash;
    b.yearly[year].holdings = [...b.lots.keys()].map((sym) => data.names[idx.get(sym)]);
    b.yearly[year].etf = b.etfUnits > 0;
  }
  // Endbewertung am letzten Kurstag
  const kEnd = data.points.length - 1;
  const pxEtf = st.kind === 'etf' ? data.bench?.[st.bench]?.px?.[kEnd] : etfPx(data, kEnd);
  let stockVal = 0, unrealStock = 0;
  const open = [];
  for (const [sym, lots] of b.lots) {
    const i = idx.get(sym);
    const px = lastPx(data, i, kEnd) || 0;
    let sh = 0, bas = 0;
    for (const l of lots) { stockVal += l.shares * px; unrealStock += l.shares * px - l.basis; sh += l.shares; bas += l.basis; }
    open.push({ sym, name: data.names[i], shares: sh, basis: bas, value: sh * px, px, firstK: Math.min(...lots.map((l) => l.k)) });
  }
  const etfVal = b.etfUnits * (pxEtf || 0);
  const final = b.cash + stockVal + etfVal;
  series.push([data.points[kEnd], final, b.contrib]);
  // Steuer, falls am Ende alles verkauft würde (rein rechnerisch)
  const endYear = yearOf(data.points[kEnd]);
  if (st.kind !== 'etf') settle(b, endYear, kEnd);
  const akt = (b.gains[endYear] || 0) + b.carry + unrealStock;
  const etfGain = (etfVal - b.etfBasis) * (1 - ETF_EXEMPT);
  const base = Math.max(0, akt) + etfGain;
  const endTax = Math.max(0, base - ALLOWANCE) * TAX;
  const afterTax = final - endTax;
  const years = (Date.parse(data.points[kEnd]) - Date.parse(data.points[k0])) / (365.25 * 864e5);
  const ys = Object.keys(b.yearly).map(Number).sort((a, c) => a - c);
  ys.forEach((y, j) => { b.yearly[y].trades = (j + 1 < ys.length ? b.yearly[ys[j + 1]].trades0 : b.trades) - b.yearly[y].trades0; });
  if (b.yearly[endYear]) b.yearly[endYear].value = final;
  return {
    key, label: st.label, short: st.short, kind: st.kind, series, contrib: b.contrib, final, afterTax, endTax,
    taxesPaid: b.taxes, fees: b.fees, spreadCost: b.spreadCost, trades: b.trades, maxDD, years,
    irr: irr(b.flows, k0, kEnd, final, data), irrAfter: irr(b.flows, k0, kEnd, afterTax, data),
    yearly: b.yearly, log: b.log, months: b.months, open, cash: b.cash, etfValue: etfVal, etfBasis: b.etfBasis,
    start: data.points[k0], end: data.points[kEnd], k0, kEnd,
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
  const op = data.s2_op ? new Set(data.s2_op[k] || []) : null;
  const risk = data.s2_risk?.[k] || {};
  const top10 = new Set((data.cand[k] || []).slice(0, 10));
  return (data.rank[k] || []).map((i, r) => ({
    rank: r + 1, symbol: data.syms[i], name: data.names[i], sector: data.sectors[i],
    cand: cand.has(i), s2: s2.has(i), riskNormal: s2n.has(i), checked: top10.has(i),
    risk: risk[String(i)] || (s2n.has(i) ? 'NORMAL' : null), opHigh: op ? op.has(i) : (s2.has(i) ? true : null),
  }));
}

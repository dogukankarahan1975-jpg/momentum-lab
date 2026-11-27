// Backtest-Simulator: rechnet Sparpläne mit echten historischen Kursen und den damals sichtbaren Screening-Listen.
// Datenquelle: simulator.json (Pipeline). Reine Rechenlogik, im Browser und in Node testbar.

export const STRATEGIES = {
  world: { label: 'MSCI World ETF-Sparplan', short: 'MSCI World', kind: 'etf', bench: 'msci_world' },
  sp500: { label: 'S&P 500 ETF-Sparplan', short: 'S&P 500', kind: 'etf', bench: 'sp500' },
  s1top5: { label: 'Stage 1: Top-5-Liste', short: 'Stage 1 Top 5', kind: 'list', n: 5, list: 'cand' },
  s1top10: { label: 'Stage 1: Top-10-Liste', short: 'Stage 1 Top 10', kind: 'list', n: 10, list: 'cand' },
  s2top5: { label: 'Stage 2: Top 5 der Fortsetzungs-Rangfolge (Kursteil)', short: 'Stage 2 Top 5', kind: 'list', n: 5, list: 's2' },
  s1min4: { label: 'Stage 1: nur Kandidaten mit Momentum-Score ab 4', short: 'Minimum Score 4', kind: 'list', n: null, list: 'min' },
};

export const DEFAULTS = {
  startYear: 2011, budget: 500, dyn: 2, feeBuy: 1, feeSell: 1, feeEtf: 0, spread: 0.2, spreadEtf: 0.1,
  initial: 0, budgetMonths: null, hold: 'signal', rest: 'top', biasCorr: false, endYear: null, freq: 'monthly', budgetMode: 'reinvest', minScore: 4, strategies: ['world', 'sp500', 's1top5', 's1top10', 's2top5', 's1min4'],
};

export const HOLD_LABEL = {
  signal: 'bis zum ersten Verkaufssignal der App',
  1: 'immer 1 Monat, dann verkaufen (auch im Minus)', '1be': '1 Monat; im Minus weiter halten, bis wieder ±0 erreicht ist',
  3: 'immer 3 Monate, dann verkaufen (auch im Minus)', '3be': '3 Monate; im Minus weiter halten, bis wieder ±0 erreicht ist',
  6: 'immer 6 Monate, dann verkaufen (auch im Minus)', 12: 'immer 12 Monate, dann verkaufen (auch im Minus)',
  '6be': '6 Monate; im Minus weiter halten, bis wieder ±0 erreicht ist', '12be': '12 Monate; im Minus weiter halten, bis wieder ±0 erreicht ist',
};
export const BUDGET_LABEL = {
  reinvest: 'Monatsbudget plus Verkaufserlöse werden angelegt',
  fixed: 'Nur das feste Monatsbudget wird angelegt, Verkaufserlöse bleiben auf dem Konto (nach Ende der Starthilfe werden auch die Erlöse angelegt)',
};
export const REST_LABEL = {
  etf: 'Rest fließt in den MSCI World ETF',
  cash: 'Nur Kandidaten kaufen, Rest bleibt auf dem Konto (0 % Zins) und wird im nächsten Monat mit angelegt',
  top: 'Top 5/Top 10 kaufen immer 5 bzw. 10 Aktien (fehlende Kandidaten werden mit den nächsten der Momentum-Rangliste aufgefüllt)',
};

const TAX = 0.26375;
// Basiszins für die Vorabpauschale (BMF, § 18 Abs. 4 InvStG); negative Werte = 0. Vor 2018 gab es keine Vorabpauschale.
export const BASISZINS = { 2018: 0.0087, 2019: 0.0052, 2020: 0.0007, 2021: 0, 2022: 0, 2023: 0.0255, 2024: 0.0229, 2025: 0.0253, 2026: 0.032 };
// Sparer-Pauschbetrag (Einzelperson): 801 € bis 2022, 1.000 € ab 2023 (§ 20 Abs. 9 EStG)
export const allowance = (y) => (y >= 2023 ? 1000 : 801);
const ETF_EXEMPT = 0.3;

const yearOf = (iso) => Number(iso.slice(0, 4));
const eur = (x) => `${x.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const dmy = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;

/** Wie oft gescreent (und gekauft) wird. Stichtage: erster Handelstag im Januar/April/Juli/Oktober usw. */
export const FREQ_MONTHS = { monthly: null, quarterly: [1, 4, 7, 10], semiannual: [1, 7], annual: [1] };
export const FREQ_LABEL = { monthly: 'monatlich', quarterly: 'vierteljährlich (Jan, Apr, Jul, Okt)', semiannual: 'halbjährlich (Jan, Jul)', annual: 'jährlich (Januar)' };
export function isScreenMonth(date, freq) {
  const ms = FREQ_MONTHS[freq];
  return !ms || ms.includes(Number(String(date).slice(5, 7)));
}

/** Letzter Bewertungspunkt bis Ende des Endjahres (null = bis heute). */
export function endIndex(data, year) {
  const last = data.points.length - 1;
  if (!year || yearOf(data.points[last]) <= year) return last;
  let k = last;
  while (k > 0 && yearOf(data.points[k]) > year) k -= 1;
  return k;
}

export function startIndex(data, year) {
  const i = data.signal_dates.findIndex((d) => yearOf(d) >= year);
  return i < 0 ? 0 : i;
}

function newBook() {
  return {
    cash: 0, lots: new Map(), etfUnits: 0, etfBasis: 0, gains: {}, carry: 0, curYear: null, vpT: {}, paidYear: {}, monthTax: 0,
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
  withhold(b, year, k, `Verkauf ${data.names[i]}`);
  return true;
}

function buyEtf(b, amount, px, o, k, why) {
  if (!(px > 0) || amount <= o.feeEtf) return false;
  const sc = amount * (o.spreadEtf / 200);
  const units = (amount - o.feeEtf - sc) / px;
  b.etfUnits += units;
  b.etfBasis += amount; b.cash -= amount; b.fees += o.feeEtf; b.spreadCost += sc; b.trades += 1;
  if (b.etfYear) b.etfYear.buys.push({ amount, month: Number(why.date?.slice(5, 7) || 1) - 1 });
  b.log.push({ k, type: 'ETF-Kauf', sym: 'ETF', name: why.name, px, shares: units, amount, fee: o.feeEtf, spread: sc, why: why.text, cash: b.cash });
  return true;
}

// Steuer wie beim deutschen Broker: sofort bei jedem Verkauf einbehalten (bzw. erstattet), mit Aktien-Verlusttopf,
// allgemeinem Topf (ETF: Vorabpauschale) und Sparer-Pauschbetrag des laufenden Jahres. Die Vorabpauschale wird am
// ersten Handelstag des Folgejahres belastet. Nicht verrechnete Aktienverluste werden ins nächste Jahr vorgetragen.
function liability(b, y, extraStock = 0, extraGeneral = 0) {
  const g = (b.gains[y] || 0) + b.carry + extraStock;           // Aktien-Verlusttopf: nur mit Aktiengewinnen
  const general = (b.vpT[y] || 0) + extraGeneral;                // allgemeiner Topf (Vorabpauschale, ETF-Gewinne)
  const taxable = Math.max(0, g) + general;                       // allgemeine Verluste dürfen Aktiengewinne mindern
  return Math.max(0, taxable - allowance(y)) * TAX;
}

function withhold(b, y, k, what) {
  const due = liability(b, y);
  const d = due - (b.paidYear[y] || 0);
  if (Math.abs(d) < 0.005) return 0;
  b.paidYear[y] = due;
  b.cash -= d; b.taxes += d; b.monthTax += d;
  if (b.yearly[y]) b.yearly[y].tax += d;
  const g = (b.gains[y] || 0) + b.carry;
  const parts = [`Aktien ${y} bisher ${eur(b.gains[y] || 0)}${b.carry ? ` (Verlustvortrag ${eur(b.carry)})` : ''}`];
  if (b.vpT[y]) parts.push(`Vorabpauschale steuerpflichtig ${eur(b.vpT[y])}`);
  b.log.push({ k, type: 'Steuer', name: d > 0 ? `einbehalten (${what})` : `erstattet (${what})`, amount: d,
    why: `${parts.join('; ')}. Steuerpflichtig ${eur(Math.max(0, g) + (b.vpT[y] || 0))} − ${eur(allowance(y))} Sparer-Pauschbetrag → Steuer im Jahr ${eur(due)}, davon schon gezahlt ${eur(due - d)}.`, cash: b.cash });
  return d;
}

function newYear(b, year, k, pxE) {
  if (b.curYear === null) { b.curYear = year; return; }
  if (year === b.curYear) return;
  const prev = b.curYear;
  b.carry = Math.min(0, (b.gains[prev] || 0) + b.carry);          // Aktienverluste vortragen
  vorabpauschale(b, prev, pxE);
  const vp = b.vp?.[prev] || 0;
  b.curYear = year;
  if (vp > 0) {
    b.vpT[year] = vp * (1 - ETF_EXEMPT);
    b.log.push({ k, type: 'Info', name: `Vorabpauschale ${prev}`, amount: 0, why: `ETF-Vorabpauschale ${prev}: ${eur(vp)}, nach 30 % Teilfreistellung steuerpflichtig ${eur(b.vpT[year])}. Wird Anfang ${year} belastet.`, cash: b.cash });
    withhold(b, year, k, `Vorabpauschale ${prev}`);
  }
}

function vorabpauschale(b, y, pxNow) {
  // Basisertrag = Wert Jahresanfang × Basiszins × 0,7 (+ Käufe im Jahr anteilig je volle Monate), höchstens der Wertzuwachs
  const e = b.etfYear;
  if (!e || e.year !== y) return;
  const bz = BASISZINS[y] || 0;
  if (!bz || !(pxNow > 0)) return;
  const vEnd = b.etfUnits * pxNow;
  const bought = e.buys.reduce((s, x) => s + x.amount, 0);
  const gain = vEnd - e.v0 - bought;
  const base = e.v0 * bz * 0.7 + e.buys.reduce((s, x) => s + x.amount * bz * 0.7 * (12 - x.month) / 12, 0);
  const vp = Math.max(0, Math.min(gain, base));
  if (!b.vp) b.vp = {};
  b.vp[y] = vp;
  b.vpTotal = (b.vpTotal || 0) + vp;
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
export function targetList(data, key, k, rest, minScore = 4, ex = null) {
  const st = STRATEGIES[key];
  const okI = (i) => !ex || !ex.has(i);
  if (st.list === 'min') {
    // nur Stage-1-Kandidaten mit Momentum-Score ab minScore, sonst nichts
    const z = data.cand_z?.[k] || [];
    return (data.cand[k] || []).filter((i, j) => z[j] != null && z[j] >= minScore && okI(i));
  }
  const src = (st.list === 's2' ? (data.s2[k] || []) : (data.cand[k] || [])).filter(okI);
  let t = src.slice(0, st.n);
  if (rest === 'top' && t.length < st.n) {
    const extra = (data.rank[k] || []).filter((i) => !t.includes(i) && okI(i));
    t = t.concat(extra).slice(0, st.n);
  }
  return t;
}

// Korrektur Überlebenden-Effekt: alle Aktienkurse verlieren gleichmäßig den gemessenen Vorsprung pro Jahr
const dragCache = new WeakMap();
export function withDrag(data, pa) {
  const c = dragCache.get(data);
  if (c && c.pa === pa) return c.d;
  const t0 = Date.parse(data.points[0]);
  const f = data.points.map((p) => (1 + pa) ** (-(Date.parse(p) - t0) / (365.25 * 86400000)));
  const d = { ...data, px: data.px.map((row) => row.map((v, k) => (v == null ? v : v * f[k]))) };
  dragCache.set(data, { pa, d });
  return d;
}

/** Simuliert eine Strategie. Liefert Monatswerte, Kennzahlen, Jahres- und Transaktionsprotokoll. */
export function simulate(data, key, opts) {
  const o = { ...DEFAULTS, ...opts };
  if (o.biasCorr && data.bias?.pa > 0 && STRATEGIES[key].kind !== 'etf') data = withDrag(data, data.bias.pa);
  const st = STRATEGIES[key];
  const idx = new Map(data.syms.map((s, i) => [s, i]));
  const exSet = o.exclude?.length ? new Set(o.exclude.map((s) => idx.get(s)).filter((i) => i != null)) : null;
  const k0 = startIndex(data, o.startYear);
  const kStop = endIndex(data, o.endYear);
  const K = kStop === data.points.length - 1 ? data.signal_dates.length : Math.max(k0 + 1, kStop);
  const b = newBook();
  const series = [];
  const twr = [1];
  let prevVal = null, peak = 1, maxDD = 0;
  const worldName = data.bench?.msci_world?.name || 'MSCI World ETF';
  for (let k = k0; k < K; k++) {
    const date = data.points[k];
    const year = yearOf(date);
    if (!b.yearly[year]) b.yearly[year] = { contrib: 0, tax: 0, trades0: b.trades, value: 0, holdings: [], buys: [], sells: [] };
    const pxE = st.kind === 'etf' ? data.bench?.[st.bench]?.px?.[k] : etfPx(data, k);
    b.monthTax = 0;
    newYear(b, year, k, pxE);
    if (!b.etfYear || b.etfYear.year !== year) b.etfYear = { year, v0: b.etfUnits * (pxE || 0), buys: [] };
    const taxPaid = b.monthTax;
    // Monatsbudget nur in den ersten o.budgetMonths Monaten (Starthilfe), danach trägt sich die Strategie selbst
    const paying = !(o.budgetMonths > 0) || k - k0 < o.budgetMonths;
    const budget = (paying ? o.budget * Math.pow(1 + o.dyn / 100, Math.floor((k - k0) / 12)) : 0)
      + (k === k0 ? (o.initial || 0) : 0);
    if (!paying && k - k0 === o.budgetMonths && o.budget > 0) {
      b.log.push({ k, type: 'Info', name: 'Starthilfe beendet', amount: 0, why: `Nach ${o.budgetMonths} Monaten kein Monatsbudget mehr – ab jetzt werden nur noch die Verkaufserlöse angelegt.`, cash: b.cash });
    }
    const cashBefore = b.cash;
    b.cash += budget; b.contrib += budget;
    b.flows.push([k, -budget]);
    b.yearly[year].contrib += budget;
    const m = { k, budget, carried: cashBefore + taxPaid, tax: taxPaid, proceeds: 0, invest: 0, each: 0, n: 0, bought: [], sold: [] };
    if (st.kind === 'etf') {
      // reiner Sparplan: jeden Monat kaufen, nie verkaufen
      const px = data.bench?.[st.bench]?.px?.[k];
      if (px > 0 && b.cash > o.feeEtf) {
        const sc = b.cash * (o.spreadEtf / 200);
        const units = (b.cash - o.feeEtf - sc) / px;
        b.log.push({ k, type: 'ETF-Kauf', sym: 'ETF', name: data.bench[st.bench].name, px, shares: units, amount: b.cash, fee: o.feeEtf, spread: sc, why: 'Sparrate', cash: 0 });
        b.etfUnits += units; b.etfBasis += b.cash; b.fees += o.feeEtf; b.spreadCost += sc; b.trades += 1;
        b.etfYear.buys.push({ amount: b.cash, month: Number(date.slice(5, 7)) - 1 });
        m.invest = b.cash; b.cash = 0;
      }
    } else {
      const screenNow = k === k0 || isScreenMonth(date, o.freq);
      const target = screenNow ? targetList(data, key, k, o.rest, o.minScore, exSet) : [];
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
          // Verkaufssignale werden nur an Screening-Terminen gelesen (dazwischen schaut man nicht in die App)
          if (screenNow && ((cond && n >= 2) || c === '2')) {
            const endK = data.ended?.[i];
            const why = c === '2' ? 'Verkaufssignal sofort (Rang unter Median oder 12 M unter −10 %)'
              : c === '3' ? (endK != null && k > endK ? `Kursdaten enden am ${dmy(data.points[endK])} (Delisting/Übernahme) – Verkauf zum letzten bekannten Kurs angenommen, tatsächlicher Ausgang unbekannt`
                : 'Nicht mehr im Index oder Datenproblem (2. Monat)') : 'Verkaufssignal: 2. Monatsende außerhalb der besten 20 %';
            if (sellLots(b, data, i, px, o, k, year, why)) { b.yearly[year].sells.push(sym); m.sold.push(data.names[i]); }
          }
        } else {
          const be = String(o.hold).endsWith('be');
          const h = parseInt(o.hold, 10);
          const due = (l) => k - l.k >= h;
          const lots = b.lots.get(sym) || [];
          if (!lots.some(due) || !(px > 0)) continue;
          if (be) {
            // nur verkaufen, wenn der Erlös nach Spread und Gebühr mindestens den Einstand deckt
            const dl = lots.filter(due);
            const sh = dl.reduce((x, l) => x + l.shares, 0), bas = dl.reduce((x, l) => x + l.basis, 0);
            const net = sh * px * (1 - o.spread / 200) - o.feeSell;
            if (net < bas) {
              if (!b.waiting) b.waiting = new Set();
              if (!b.waiting.has(sym)) { b.waiting.add(sym); b.log.push({ k, type: 'Halten', sym, name: data.names[i], px, shares: sh, amount: 0, why: `Haltedauer ${h} Monate erreicht, aber im Minus (${eur(net - bas)}). Weiter halten bis ±0.`, cash: b.cash }); }
              continue;
            }
            const was = b.waiting?.has(sym);
            if (sellLots(b, data, i, px, o, k, year, was ? 'Wieder bei ±0 oder im Plus nach Wartezeit' : `Haltedauer ${h} Monate erreicht, im Plus`, due)) {
              b.waiting?.delete(sym); b.yearly[year].sells.push(sym); m.sold.push(data.names[i]);
            }
          } else if (sellLots(b, data, i, px, o, k, year, `Haltedauer ${h} Monate erreicht`, due)) {
            b.yearly[year].sells.push(sym); m.sold.push(data.names[i]);
          }
        }
      }
      m.proceeds = b.cash - cashPreSell + (b.monthTax - taxPaid);   // Erlöse vor Steuer
      // 2) Anlagebetrag: fest = nur Monatsbudget(s) seit dem letzten Screening; mit Erlösen = alles verfügbare Geld.
      //    Zwischen zwei Screening-Terminen wird nichts gekauft: Budget und Erlöse sammeln sich auf dem Konto.
      b.pendingBudget = (b.pendingBudget || 0) + budget;
      const avail = Math.max(0, b.cash);
      const invest = !screenNow ? 0 : o.budgetMode === 'fixed' && paying ? Math.min(b.pendingBudget, avail) : avail;
      if (screenNow) b.pendingBudget = 0;
      m.screen = screenNow;
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
        if (rest > 1 && o.rest === 'etf' && st.list !== 'min') buyEtf(b, rest, etfPx(data, k), o, k, { name: worldName, text: `${slots - used} freie Plätze`, date });
      } else if (screenNow && invest > 1 && o.rest === 'etf' && st.list !== 'min') {
        buyEtf(b, invest, etfPx(data, k), o, k, { name: worldName, text: 'kein Kandidat in diesem Monat', date });
      }
    }
    m.tax = b.monthTax;
    m.cashAfter = b.cash;
    b.months.push(m);
    const v = st.kind === 'etf'
      ? b.cash + b.etfUnits * (data.bench?.[st.bench]?.px?.[k] || 0)
      : b.cash + stockValue(b, data, k, idx) + b.etfUnits * (etfPx(data, k) || 0);
    if (prevVal !== null && prevVal > 0) {
      const r = (v - budget) / prevVal;
      const t = twr[twr.length - 1] * r;
      if (t > 0) { twr.push(t); peak = Math.max(peak, t); maxDD = Math.min(maxDD, t / peak - 1); }
    }
    prevVal = v;
    series.push([date, v, b.contrib]);
    b.yearly[year].value = v;
    b.yearly[year].cash = b.cash;
    b.yearly[year].holdings = [...b.lots.keys()].map((sym) => data.names[idx.get(sym)]);
    b.yearly[year].etf = b.etfUnits > 0;
  }
  // Endbewertung am letzten Kurstag
  const kEnd = Math.max(kStop, k0);
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
  // Kosten des Schlussverkaufs (Ordergebühr + halber Spread je Position) mindern Erlös und Gewinn
  const liqStock = open.reduce((a, p) => a + (p.value > 0 ? o.feeSell + p.value * (o.spread / 200) : 0), 0);
  const liqEtf = etfVal > 0 ? o.feeEtf + etfVal * (o.spreadEtf / 200) : 0;
  const etfGain = (etfVal - liqEtf - b.etfBasis - (b.vpTotal || 0)) * (1 - ETF_EXEMPT);
  const endTax = liability(b, endYear, unrealStock - liqStock, etfGain) - (b.paidYear[endYear] || 0);
  const afterTax = final - liqStock - liqEtf - endTax;
  const years = (Date.parse(data.points[kEnd]) - Date.parse(data.points[k0])) / (365.25 * 864e5);
  const ys = Object.keys(b.yearly).map(Number).sort((a, c) => a - c);
  ys.forEach((y, j) => { b.yearly[y].trades = (j + 1 < ys.length ? b.yearly[ys[j + 1]].trades0 : b.trades) - b.yearly[y].trades0; });
  if (b.yearly[endYear]) b.yearly[endYear].value = final;
  return {
    key, label: key === 's1min4' ? `Stage 1: nur Kandidaten mit Momentum-Score ab ${String(o.minScore).replace('.', ',')}` : st.label, short: key === 's1min4' ? `Minimum Score ${String(o.minScore).replace('.', ',')}` : st.short, kind: st.kind, series, contrib: b.contrib, final, afterTax, endTax,
    taxesPaid: b.taxes, vpTotal: b.vpTotal || 0, fees: b.fees, spreadCost: b.spreadCost, trades: b.trades, maxDD, years,
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
  const s2 = data.s2?.[k] || [];
  const s2sc = data.s2_score?.[k] || [];
  const zr = data.rank_z?.[k] || [];
  return (data.rank[k] || []).map((i, r) => {
    const p = s2.indexOf(i);
    return {
      rank: r + 1, symbol: data.syms[i], name: data.names[i], sector: data.sectors[i], score: zr[r] ?? null,
      cand: cand.has(i), s2rank: p >= 0 ? p + 1 : null, s2score: p >= 0 ? s2sc[p] ?? null : null, s2top: p >= 0 && p < 5,
    };
  });
}

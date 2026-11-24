// Depot-Berechnungen: FIFO-Tranchen (wie im deutschen Steuerrecht), Splits, Dividenden, Sparpläne, Historie.
import { addDays, addMonths, todayISO } from './fmt.js';

const TYPE_ORDER = { SPLIT: 0, BUY: 1, SELL: 2, DIV: 3 };
export const TX_LABEL = { BUY: 'Kauf', SELL: 'Verkauf', DIV: 'Dividende', SPLIT: 'Aktiensplit' };

export function sortTx(txs) {
  return [...txs].sort((a, b) => a.date.localeCompare(b.date)
    || (TYPE_ORDER[a.type] - TYPE_ORDER[b.type])
    || String(a.createdAt || '').localeCompare(String(b.createdAt || '')));
}
const fxOf = (t) => (!t.currency || t.currency === 'EUR' ? 1 : Number(t.fx));

/* Spielt Transaktionen bis einschließlich 'until' (ISO) ab. */
export function replay(txs, until = '9999-12-31') {
  const lots = [];
  const st = { realized: 0, realizedByYear: {}, dividends: 0, bought: 0, soldProceeds: 0, fees: 0, errors: [], sells: [] };
  for (const t of sortTx(txs)) {
    if (t.date > until) break;
    const fx = fxOf(t);
    if (t.type !== 'DIV' && t.type !== 'SPLIT' && !(fx > 0)) {
      st.errors.push(`${t.date}: Wechselkurs fehlt (${t.currency})`);
      continue;
    }
    if (t.type === 'BUY') {
      const cost = (t.qty * t.price + (t.fees || 0)) / fx;
      lots.push({ qty: t.qty, cost, date: t.date });
      st.bought += cost;
      st.fees += (t.fees || 0) / fx;
    } else if (t.type === 'SELL') {
      const held = lots.reduce((s, l) => s + l.qty, 0);
      if (t.qty > held + 1e-9) {
        st.errors.push(`${t.date}: Verkauf von ${t.qty} Stück übersteigt den Bestand (${+held.toFixed(6)})`);
        continue;
      }
      let rem = t.qty, basis = 0;
      while (rem > 1e-12 && lots.length) {
        const l = lots[0];
        const take = Math.min(l.qty, rem);
        const part = l.cost * (take / l.qty);
        basis += part; l.cost -= part; l.qty -= take; rem -= take;
        if (l.qty <= 1e-12) lots.shift();
      }
      const proceeds = (t.qty * t.price - (t.fees || 0)) / fx;
      const gain = proceeds - basis;
      st.realized += gain;
      const y = t.date.slice(0, 4);
      st.realizedByYear[y] = (st.realizedByYear[y] || 0) + gain;
      st.soldProceeds += proceeds;
      st.fees += (t.fees || 0) / fx;
      st.sells.push({ date: t.date, qty: t.qty, gain, proceeds, basis });
    } else if (t.type === 'SPLIT') {
      const r = Number(t.ratio);
      if (!(r > 0)) { st.errors.push(`${t.date}: ungültiges Split-Verhältnis`); continue; }
      for (const l of lots) l.qty *= r;
    } else if (t.type === 'DIV') {
      st.dividends += Number(t.amount) || 0;
    }
  }
  st.lots = lots;
  st.qty = lots.reduce((s, l) => s + l.qty, 0);
  if (st.qty < 1e-9) st.qty = 0;
  st.costOpen = lots.reduce((s, l) => s + l.cost, 0);
  return st;
}

/* mark: { price, currency, fxRate (Einheiten je EUR), date, source } */
export function computePosition(pos, txs, mark) {
  const st = replay(txs);
  let priceEUR = null, mvEUR = null;
  if (mark && Number.isFinite(mark.price)) {
    const f = mark.currency === 'EUR' ? 1 : Number(mark.fxRate);
    if (f > 0) { priceEUR = mark.price / f; mvEUR = st.qty * priceEUR; }
    else st.errors.push(`Kein Wechselkurs für ${mark.currency}`);
  }
  const unreal = mvEUR != null ? mvEUR - st.costOpen : null;
  const totalReturn = st.qty > 0 && mvEUR == null ? null : (unreal || 0) + st.realized + st.dividends;
  return {
    id: pos.id, pos, mark, qty: st.qty, costOpen: st.costOpen, avgCost: st.qty > 0 ? st.costOpen / st.qty : null,
    bought: st.bought, soldProceeds: st.soldProceeds, realized: st.realized, realizedByYear: st.realizedByYear,
    dividends: st.dividends, fees: st.fees, priceEUR, mvEUR, unreal,
    unrealPct: unreal != null && st.costOpen > 0 ? unreal / st.costOpen : null,
    totalReturn, totalReturnPct: totalReturn != null && st.bought > 0 ? totalReturn / st.bought : null,
    errors: st.errors, closed: st.qty === 0, lots: st.lots, sells: st.sells,
  };
}

export function markFor(pos, screen, today = todayISO()) {
  const row = screen?.bySymbol?.get(pos.symbol);
  const rates = screen?.fx?.rates || {};
  if (row && Number.isFinite(row.last_close)) {
    const cur = row.currency || pos.currency || 'EUR';
    return { price: row.last_close, currency: cur, fxRate: cur === 'EUR' ? 1 : rates[cur], date: row.last_date, source: 'Daten', row };
  }
  const m = pos.manualPrice;
  if (m && Number.isFinite(m.price)) {
    const cur = m.currency || 'EUR';
    return { price: m.price, currency: cur, fxRate: cur === 'EUR' ? 1 : (m.fx || rates[cur]), date: m.date || today, source: 'manuell', row: row || null };
  }
  return null;
}

export function computePortfolio(positions, txs, screen) {
  const byPos = groupBy(txs, 'positionId');
  const items = positions.map((p) => computePosition(p, byPos[p.id] || [], markFor(p, screen)));
  const open = items.filter((i) => !i.closed);
  const t = { mv: 0, costOpen: 0, unreal: 0, realized: 0, dividends: 0, bought: 0, fees: 0, missingPrices: 0 };
  for (const i of items) {
    t.realized += i.realized; t.dividends += i.dividends; t.bought += i.bought; t.fees += i.fees;
    if (i.closed) continue;
    t.costOpen += i.costOpen;
    if (i.mvEUR == null) { t.missingPrices += 1; continue; }
    t.mv += i.mvEUR; t.unreal += i.unreal;
  }
  for (const i of open) i.weight = i.mvEUR != null && t.mv > 0 ? i.mvEUR / t.mv : null;
  t.unrealPct = t.costOpen > 0 ? t.unreal / t.costOpen : null;
  t.totalReturn = t.unreal + t.realized + t.dividends;
  t.totalReturnPct = t.bought > 0 ? t.totalReturn / t.bought : null;
  t.positions = open.length;
  return { items, open, closed: items.filter((i) => i.closed), totals: t, byPos };
}

export function groupBy(arr, key) {
  const out = {};
  for (const x of arr) (out[x[key]] ||= []).push(x);
  return out;
}

// ---------------------------------------------------------------- Sparpläne
export const INTERVALS = { monthly: 'monatlich', biweekly: 'alle 2 Wochen', quarterly: 'vierteljährlich', weekly: 'wöchentlich' };
export function planDates(plan, until) {
  const out = [];
  const day = Number(plan.day) || Number(plan.start.slice(8, 10));
  for (let i = 0; i < 1200; i++) {
    let d;
    if (plan.interval === 'weekly') d = addDays(plan.start, 7 * i);
    else if (plan.interval === 'biweekly') d = addDays(plan.start, 14 * i);
    else if (plan.interval === 'quarterly') d = addMonths(plan.start, 3 * i, day);
    else d = addMonths(plan.start, i, day);
    if (d > until) break;
    if (d >= plan.start) out.push(d);
  }
  return out;
}
export function planOverview(plan, txs, today = todayISO()) {
  const horizon = addMonths(today, 4);
  const dates = planDates(plan, horizon);
  const mine = txs.filter((t) => t.type === 'BUY' && t.planId === plan.id);
  const used = new Set();
  const rows = dates.map((d) => {
    let best = null;
    for (const t of mine) {
      if (used.has(t.id)) continue;
      const diff = Math.abs((new Date(t.date) - new Date(d)) / 86400000);
      if (diff <= 7 && (!best || diff < best.diff)) best = { t, diff };
    }
    if (best) used.add(best.t.id);
    const status = best ? 'erfasst' : d <= today ? (plan.active === false && d > (plan.stoppedAt || '9999') ? 'gestoppt' : 'offen') : 'geplant';
    return { date: d, amount: plan.amount, status, tx: best?.t || null };
  }).filter((r) => !(r.status === 'geplant' && plan.active === false));
  const recorded = mine.length;
  const invested = mine.reduce((s, t) => s + (t.qty * t.price + (t.fees || 0)) / fxOf(t), 0);
  const qty = mine.reduce((s, t) => s + t.qty, 0);
  return {
    rows, recorded, invested, avgPrice: qty > 0 ? invested / qty : null,
    open: rows.filter((r) => r.status === 'offen' && (plan.active !== false)).length,
    next: rows.find((r) => r.status === 'geplant')?.date || null,
  };
}

// ---------------------------------------------------------------- Historie
/* Rekonstruiert Monatsend-Werte aus Transaktionen und splitbereinigten Monatskursen. */
export function reconstructHistory(positions, txs, monthly) {
  if (!monthly?.dates?.length) return [];
  const byPos = groupBy(txs, 'positionId');
  const firstTx = txs.reduce((m, t) => (!m || t.date < m ? t.date : m), null);
  if (!firstTx) return [];
  const out = [];
  monthly.dates.forEach((d, k) => {
    if (d < firstTx.slice(0, 7) + '-01') return;
    let value = 0, invested = 0, complete = true, any = false;
    for (const p of positions) {
      const list = byPos[p.id] || [];
      const st = replay(list, d);
      invested += st.costOpen;
      if (st.qty <= 0) continue;
      any = true;
      const after = list.filter((t) => t.type === 'SPLIT' && t.date > d).reduce((f, t) => f * Number(t.ratio || 1), 1);
      const px = monthly.prices?.[p.symbol]?.[k];
      const cur = monthly.currency?.[p.symbol] || p.currency || 'EUR';
      const rate = cur === 'EUR' ? 1 : monthly.fx?.[cur]?.[k];
      if (!Number.isFinite(px) || !(rate > 0)) { complete = false; continue; }
      value += (st.qty * after) * px / rate;
    }
    if (any || invested > 0) out.push({ date: d, value, invested, complete });
  });
  return out;
}

export function taxRate(settings) { return settings?.churchTax ? 0.2799 : 0.26375; }
export function estimateSaleTax(gain, settings) {
  if (!Number.isFinite(gain) || gain <= 0) return 0;
  const taxable = Math.max(0, gain - (Number(settings?.taxAllowanceLeft) || 0));
  return taxable * taxRate(settings);
}

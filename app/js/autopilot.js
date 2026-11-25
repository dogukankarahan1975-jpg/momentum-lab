// Autopilot: setzt den Monatsplan aus autopilot.json auf das eigene Depot um (reine Rechenlogik, testbar).
// Gleiche Regeln wie im Backtest (pipeline/autopilot.py):
//  1. Verkaufen: Status V (Halteregel an zwei Monatsenden verletzt oder "schwer"); bei PARKEN alles.
//  2. Kaufen: freie Plätze bis n mit der Kaufliste füllen (gehaltene überspringen, Branchengrenze).
//     Zielbetrag je Aktie = (Depotwert + neues Geld) / n; in Rangfolge kaufen, solange das Geld reicht.
//  3. Restgeld: Positionen auffüllen, die mehr als 25 % unter dem Zielbetrag liegen. Gewinner nie kürzen.

export const ACTION_TEXT = {
  NORMAL: { label: 'Normaler Monat', cls: 'ok' },
  KEINE_KAEUFE: { label: 'Keine Neukäufe', cls: 'warn' },
  PARKEN: { label: 'Alles parken', cls: 'bad' },
};
export const STATUS_TEXT = {
  H: 'Halten', W: 'Halten (Warnung)', V: 'Verkaufen', P: 'Selbst prüfen', X: 'Nicht im Universum',
};

const TOL = 0.25;
const MIN_ORDER = 50;

/*
 holdings: [{ symbol, name, mvEUR, sector }]  – offene Depotpositionen (mvEUR null = kein Kurs)
 plan: autopilot.plan, newCash: frei verfügbares Geld in EUR
*/
export function buildPlan(plan, holdings, newCash = 0) {
  const n = plan.rule.n;
  const cap = plan.rule.sector_cap || null;
  const park = plan.action === 'PARKEN';
  const noBuys = plan.action === 'KEINE_KAEUFE';
  const rows = holdings.map((h) => {
    const st = plan.status?.[h.symbol];
    const code = st ? st[0] : 'X';
    let todo = 'halten';
    if (park || code === 'V') todo = 'verkaufen';
    else if (code === 'P' || code === 'X') todo = 'pruefen';
    return { ...h, code, pct: st ? st[1] : null, todo };
  });
  const sells = rows.filter((r) => r.todo === 'verkaufen');
  const kept = rows.filter((r) => r.todo !== 'verkaufen');
  const proceeds = sells.reduce((s, r) => s + (Number.isFinite(r.mvEUR) ? r.mvEUR : 0), 0);
  const keptValue = kept.reduce((s, r) => s + (Number.isFinite(r.mvEUR) ? r.mvEUR : 0), 0);
  const cash0 = Math.max(0, Number(newCash) || 0) + proceeds;
  const total = keptValue + cash0;
  const target = n > 0 ? total / n : 0;
  let cash = cash0;
  const buys = [];
  const skipped = [];
  const topups = [];
  const waiting = [];
  if (!park && !noBuys) {
    const free = Math.max(0, n - kept.length);
    const cnt = {};
    for (const r of kept) if (r.sector) cnt[r.sector] = (cnt[r.sector] || 0) + 1;
    const heldSet = new Set(rows.map((r) => r.symbol));
    const picks = [];
    for (const c of plan.buy_list || []) {
      if (picks.length >= free) break;
      if (heldSet.has(c.symbol)) continue;
      if (cap && c.sector && (cnt[c.sector] || 0) >= cap) {
        skipped.push({ ...c, reason: `Branchengrenze: schon ${cnt[c.sector]} × ${c.sector}` });
        continue;
      }
      picks.push(c);
      if (c.sector) cnt[c.sector] = (cnt[c.sector] || 0) + 1;
    }
    for (const c of picks) {
      if (cash < MIN_ORDER) { waiting.push(c); continue; }
      const amt = Math.min(Math.max(target, MIN_ORDER), cash);
      buys.push({ ...c, amount: amt }); cash -= amt;
    }
    if (cash > MIN_ORDER) {
      const short = kept.filter((r) => r.code === 'H' || r.code === 'W')
        .filter((r) => Number.isFinite(r.mvEUR) && r.mvEUR < target * (1 - TOL))
        .map((r) => ({ ...r, need: target - r.mvEUR }));
      const need = short.reduce((s, r) => s + r.need, 0);
      if (need > 0) {
        const budget = Math.min(cash, need);
        for (const r of short) {
          const amt = budget * r.need / need;
          if (amt >= MIN_ORDER) { topups.push({ ...r, amount: amt }); cash -= amt; }
        }
      }
    }
  }
  return {
    n, cap, park, noBuys, rows, sells, kept, buys, skipped, waiting, topups, proceeds, total, target,
    rest: Math.max(0, cash), freeSlots: Math.max(0, n - kept.length),
  };
}

export function monthName(iso) {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString('de-DE', { month: 'long', year: 'numeric' });
}

// Begründungen, Risiken und Fundamentaldaten-Aufbereitung je Aktie (regelbasiert, ohne KI).
import { fmtDate, fmtNum, fmtPct, fmtRankPct } from './fmt.js';

const DATA_CODES = new Set(['no_data', 'stale', 'gaps', 'jump', 'adj_ratio', 'crosscheck', 'currency']);
export const isDataProblem = (row) => (row.reasons || []).some((c) => DATA_CODES.has(c));

const pcache = new WeakMap();
export function universeStats(screen) {
  if (pcache.has(screen)) return pcache.get(screen);
  const el = screen.rows.filter((r) => r.eligible && Number.isFinite(r.Z));
  const q = (arr, p) => { const a = arr.filter(Number.isFinite).sort((x, y) => x - y); if (!a.length) return null; return a[Math.min(a.length - 1, Math.floor(p * (a.length - 1)))]; };
  const ranked = [...el].sort((a, b) => a.rank - b.rank);
  const st = {
    n: el.length,
    volP80: q(el.map((r) => r.vol), 0.8),
    volMed: q(el.map((r) => r.vol), 0.5),
    m12Med: q(el.map((r) => r.m12), 0.5),
    m6Med: q(el.map((r) => r.m6), 0.5),
    zMed: q(el.map((r) => r.Z), 0.5),
    firstOut: ranked.find((r) => !screen.candidates.includes(r.symbol)) || null,
    sectorCount: screen.candidates.reduce((m, s) => { const sec = screen.bySymbol.get(s)?.sector || '?'; m[sec] = (m[sec] || 0) + 1; return m; }, {}),
  };
  pcache.set(screen, st);
  return st;
}

export function whySelected(row, screen) {
  const st = universeStats(screen);
  const out = [];
  out.push(`Rang ${row.rank} von ${st.n} zulässigen Aktien (${fmtRankPct(row.pct)}) beim risikoadjustierten Momentum.`);
  out.push(`12-Monats-Momentum ohne letzten Monat: ${fmtPct(row.m12)} (Median des Universums ${fmtPct(st.m12Med)}).`);
  out.push(`6-Monats-Momentum ohne letzten Monat: ${fmtPct(row.m6)} (Median ${fmtPct(st.m6Med)}).`);
  out.push(`Volatilität ${fmtPct(row.vol, 0, false)} p. a. Das Momentum wird durch diese Schwankung geteilt, deshalb zählen ruhige Aufwärtstrends mehr als wilde Sprünge.`);
  out.push('Alle Daten-, Liquiditäts- und Ausschlussregeln sind erfüllt. Beide Momentum-Zeiträume sind positiv.');
  if (row.verified === true) out.push('Der aktuelle Kurs stimmt mit der Zweitquelle (iShares-Bestandsliste) überein.');
  return out;
}
export function whyBetter(row, screen) {
  const st = universeStats(screen);
  const out = [];
  if (st.firstOut) out.push(`Score ${fmtNum(row.Z, 2)} gegenüber ${fmtNum(st.firstOut.Z, 2)} beim besten Nicht-Kandidaten (${st.firstOut.name}, Rang ${st.firstOut.rank}).`);
  out.push(`Score-Median im Universum: ${fmtNum(st.zMed, 2)}. Der Score ist eine Standardisierung: 0 ist Durchschnitt, 1 liegt eine Standardabweichung darüber.`);
  const z6 = row.z6, z12 = row.z12;
  if (Number.isFinite(z6) && Number.isFinite(z12)) out.push(`Teilscores: 6 Monate ${fmtNum(z6, 2)}, 12 Monate ${fmtNum(z12, 2)}. Die Kombination gewichtet beide gleich, wie bei MSCI.`);
  return out;
}

export function riskFlags(row, detail, screen, { isCandidate = false, market = true } = {}) {
  const st = universeStats(screen);
  const f = [];
  const add = (level, text) => f.push({ level, text });
  if (Number.isFinite(row.vol) && st.volP80 && row.vol > st.volP80) add('mittel', `Hohe Volatilität (${fmtPct(row.vol, 0, false)} p. a., oberes Fünftel des Universums).`);
  if (Number.isFinite(row.dd_52w) && row.dd_52w < -0.2) add('mittel', `Kurs ${fmtPct(-row.dd_52w, 0, false)} unter dem 52-Wochen-Hoch.`);
  if (Number.isFinite(row.maxdd_1y) && row.maxdd_1y < -0.35) add('mittel', `Starker Rückschlag im letzten Jahr (maximal ${fmtPct(row.maxdd_1y, 0)}).`);
  if (row.above_ma200 === false) add('mittel', 'Kurs unter der 200-Tage-Linie (möglicher Trendbruch).');
  if (Number.isFinite(row.dist_ma200) && row.dist_ma200 > 0.5) add('info', `Kurs ${fmtPct(row.dist_ma200, 0, false)} über der 200-Tage-Linie. Die Aktie ist sehr stark gestiegen, Rückschläge fallen dann oft heftiger aus.`);
  if (row.verified === false) add('hoch', 'Kurs weicht von der Zweitquelle ab. Die Daten sind nicht verifiziert.');
  if (row.verified == null) add('info', 'Keine Gegenprüfung des Kurses verfügbar.');
  if (isCandidate) {
    const n = st.sectorCount[row.sector] || 0;
    if (n >= 4) add('mittel', `Sektor-Klumpen: ${n} der Top-Kandidaten stammen aus ${row.sector}.`);
  }
  if (market && screen.market?.bear_state) add('mittel', 'Der Markt ist über 24 Monate im Minus. Nach solchen Phasen kam es historisch öfter zu Momentum-Crashs (Daniel & Moskowitz 2016).');
  if (market && screen.market?.vol_shock) add('mittel', 'Volatilitätsschock am Gesamtmarkt (MSCI-Regel ausgelöst).');
  const fm = fundamentals(detail);
  if (fm) {
    const m = fm.metrics;
    if (Number.isFinite(m.net_income) && m.net_income < 0) add('mittel', 'Verlust im letzten Geschäftsjahr.');
    if (Number.isFinite(m.fcf) && m.fcf < 0) add('mittel', 'Negativer Free Cashflow.');
    if (Number.isFinite(m.debt_to_equity) && m.debt_to_equity > 2) add('mittel', `Hohe Verschuldung (Finanzschulden ${fmtNum(m.debt_to_equity, 1)}-fach Eigenkapital).`);
    if (Number.isFinite(m.dilution) && m.dilution > 0.03) add('info', `Aktienanzahl um ${fmtPct(m.dilution, 1, false)} gestiegen (Verwässerung).`);
    if (Number.isFinite(m.pe) && m.pe > 60) add('info', `Hohe Bewertung (KGV ${fmtNum(m.pe, 0)}).`);
    if (fm.earningsDate) {
      const days = Math.round((new Date(fm.earningsDate) - Date.now()) / 86400000);
      if (days >= 0 && days <= 21) add('info', `Quartalszahlen voraussichtlich am ${fmtDate(fm.earningsDate)}. Um diesen Termin sind Kurssprünge möglich.`);
    }
  }
  const filings = detail?.fund?.sec_filings?.filings || [];
  const recent8k = filings.find((x) => x.form === '8-K' && (Date.now() - new Date(x.date)) / 86400000 <= 14);
  if (recent8k) add('info', `Neue Pflichtmitteilung (8-K) vom ${fmtDate(recent8k.date)}. Bitte lesen.`);
  return f;
}

/* Vereinheitlicht Fundamentaldaten: SEC (offiziell) bevorzugt, sonst Yahoo (Datenbank). */
export function fundamentals(detail) {
  const fund = detail?.fund;
  if (!fund) return null;
  if (fund.demo) return { source: 'demo', metrics: fund.demo.metrics, summary: fund.yahoo?.longBusinessSummary, unit: 'DEMO' };
  const sec = fund.sec?.metrics;
  const y = fund.yahoo || {};
  const earn = y.earningsTimestampStart || y.earningsTimestamp;
  const earningsDate = earn ? new Date(earn * 1000).toISOString().slice(0, 10) : null;
  if (sec && Object.keys(sec).length > 2) {
    return { source: 'official', metrics: sec, summary: y.longBusinessSummary, unit: fund.sec.unit || 'USD',
      yahoo: y, earningsDate, sic: fund.sec_filings?.sic, edgar: fund.sec_filings?.edgar_url };
  }
  if (Object.keys(y).length) {
    const m = {
      revenue: y.totalRevenue, revenue_growth: y.revenueGrowth, net_margin: y.profitMargins, op_margin: y.operatingMargins,
      gross_margin: y.grossMargins, roe: y.returnOnEquity, eps_diluted: y.trailingEps, eps_growth: y.earningsGrowth,
      fcf: y.freeCashflow, debt_to_equity: Number.isFinite(y.debtToEquity) ? y.debtToEquity / 100 : null, pe: y.trailingPE,
    };
    return { source: 'database', metrics: m, summary: y.longBusinessSummary, unit: y.financialCurrency || '', yahoo: y, earningsDate };
  }
  return null;
}

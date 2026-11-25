// JavaScript-Tests ohne Abhängigkeiten: node tests/js/run.mjs
import assert from 'node:assert/strict';
import { computePosition, planDates, planOverview, reconstructHistory, replay, estimateSaleTax } from '../../app/js/depot.js';
import { evaluateHolding } from '../../app/js/signals.js';
import { addMonths, parseDec } from '../../app/js/fmt.js';
import { freshness } from '../../app/js/data.js';
import { validateBackup } from '../../app/js/store.js';
import { parseStage2 } from '../../app/js/data.js';
import { decisionCounts, fmtMetric, stage2Usable } from '../../app/js/stage2.js';
import { buildPlan } from '../../app/js/autopilot.js';
import { simulate as simRun, irr as simIrr, monthList } from '../../app/js/simulator.js';

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; } catch (e) { failed++; console.error(`✗ ${name}\n  ${e.message}`); }
}
const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≉ ${b}`);
const tx = (o) => ({ id: Math.random().toString(36).slice(2), positionId: 'p1', currency: 'EUR', fx: 1, fees: 0, createdAt: '', ...o });

// ---------------------------------------------------------------- Zahlen
test('parseDec deutsch und englisch', () => {
  assert.equal(parseDec('1.234,56'), 1234.56);
  assert.equal(parseDec('1,234.56'), 1234.56);
  assert.equal(parseDec('12,5'), 12.5);
  assert.equal(parseDec(' 100 € '), 100);
  assert.ok(Number.isNaN(parseDec('abc')));
  assert.ok(Number.isNaN(parseDec('')));
});
test('addMonths kappt Monatsende', () => {
  assert.equal(addMonths('2025-01-31', 1), '2025-02-28');
  assert.equal(addMonths('2024-01-31', 1), '2024-02-29');
  assert.equal(addMonths('2025-11-15', 3, 1), '2026-02-01');
});

// ---------------------------------------------------------------- Depot
test('FIFO: zwei Tranchen, Teilverkauf, realisierter Gewinn', () => {
  const t = [
    tx({ type: 'BUY', date: '2024-01-10', qty: 10, price: 100, fees: 1 }),
    tx({ type: 'BUY', date: '2024-06-10', qty: 10, price: 150, fees: 1 }),
    tx({ type: 'SELL', date: '2025-01-10', qty: 12, price: 200, fees: 1 }),
  ];
  const s = replay(t);
  near(s.qty, 8);
  // Kosten: erste Tranche 1001, zweite 1501; verkauft 10 aus Tranche 1 + 2 aus Tranche 2
  const basis = 1001 + 1501 * (2 / 10);
  near(s.realized, 12 * 200 - 1 - basis);
  near(s.costOpen, 1501 * 0.8);
  near(s.realizedByYear['2025'], s.realized);
});
test('Verkauf über Bestand wird abgelehnt', () => {
  const s = replay([tx({ type: 'BUY', date: '2024-01-01', qty: 1, price: 10 }), tx({ type: 'SELL', date: '2024-02-01', qty: 2, price: 10 })]);
  assert.equal(s.errors.length, 1);
  near(s.qty, 1);
});
test('Split verdoppelt Stückzahl, Einstand bleibt', () => {
  const s = replay([tx({ type: 'BUY', date: '2024-01-01', qty: 5, price: 100 }), tx({ type: 'SPLIT', date: '2024-03-01', ratio: 2 })]);
  near(s.qty, 10); near(s.costOpen, 500);
});
test('Split am selben Tag wird vor dem Kauf verarbeitet', () => {
  const s = replay([tx({ type: 'BUY', date: '2024-03-01', qty: 5, price: 50 }), tx({ type: 'SPLIT', date: '2024-03-01', ratio: 2 }),
    tx({ type: 'BUY', date: '2024-01-01', qty: 1, price: 100 })]);
  near(s.qty, 7); // 1 alte Aktie -> 2, plus 5 neue
});
test('Fremdwährung: Einstand und Marktwert in EUR', () => {
  const p = { id: 'p1' };
  const it = computePosition(p, [tx({ type: 'BUY', date: '2024-01-01', qty: 10, price: 110, currency: 'USD', fx: 1.1, fees: 0 }),
    tx({ type: 'DIV', date: '2024-06-01', amount: 5 })], { price: 132, currency: 'USD', fxRate: 1.2 });
  near(it.costOpen, 1000);
  near(it.mvEUR, 1100);
  near(it.unreal, 100);
  near(it.unrealPct, 0.1);
  near(it.totalReturn, 105);
  near(it.totalReturnPct, 0.105);
});
test('Ohne Kurs kein Marktwert, Gesamtrendite unbekannt', () => {
  const it = computePosition({ id: 'p1' }, [tx({ type: 'BUY', date: '2024-01-01', qty: 1, price: 10 })], null);
  assert.equal(it.mvEUR, null);
  assert.equal(it.totalReturn, null);
});
test('Steuerschätzung mit Pauschbetrag', () => {
  near(estimateSaleTax(3000, { taxAllowanceLeft: 1000, churchTax: false }), 2000 * 0.26375);
  near(estimateSaleTax(-50, { taxAllowanceLeft: 0 }), 0);
});
test('Sparplan: Termine und Zuordnung erfasster Käufe', () => {
  const plan = { id: 'sp', start: '2025-01-01', day: 1, interval: 'monthly', amount: 100, active: true };
  const d = planDates(plan, '2025-04-15');
  assert.deepEqual(d, ['2025-01-01', '2025-02-01', '2025-03-01', '2025-04-01']);
  assert.deepEqual(planDates({ ...plan, interval: 'quarterly' }, '2025-12-31'), ['2025-01-01', '2025-04-01', '2025-07-01', '2025-10-01']);
  assert.equal(planDates({ ...plan, interval: 'biweekly' }, '2025-02-01').length, 3);
  const txs = [tx({ type: 'BUY', date: '2025-01-03', qty: 1, price: 99, planId: 'sp' }), tx({ type: 'BUY', date: '2025-03-01', qty: 1, price: 98, planId: 'sp' })];
  const ov = planOverview(plan, txs, '2025-04-15');
  const st = Object.fromEntries(ov.rows.map((r) => [r.date, r.status]));
  assert.equal(st['2025-01-01'], 'erfasst');
  assert.equal(st['2025-02-01'], 'offen');
  assert.equal(st['2025-03-01'], 'erfasst');
  assert.equal(ov.recorded, 2);
  near(ov.invested, 197);
  assert.equal(ov.open, 2);
});
test('Historie: Monatswerte mit späterem Split', () => {
  const positions = [{ id: 'p1', symbol: 'AAA' }];
  const txs = [tx({ type: 'BUY', date: '2024-01-15', qty: 10, price: 100 }), tx({ type: 'SPLIT', date: '2024-03-10', ratio: 2 })];
  const monthly = { dates: ['2024-01-31', '2024-02-29', '2024-03-28'], prices: { AAA: [52, 55, 60] }, currency: { AAA: 'EUR' }, fx: {} };
  const h = reconstructHistory(positions, txs, monthly);
  assert.equal(h.length, 3);
  near(h[0].value, 20 * 52); // 10 Stück vor Split = 20 Stück auf heutiger Basis
  near(h[2].value, 20 * 60);
  near(h[0].invested, 1000);
});

// ---------------------------------------------------------------- Signale
const fresh = { ok: true, abort: false, level: 'aktuell', label: 'aktuell' };
const base = { last_close: 10, Z: 1.5, pct: 0.05, m12: 0.3, m6: 0.1, data_ok: true, above_ma200: true, H: false, severe: false, H_prev: false, verified: true, reasons: [] };
const ev = (row, extra = {}) => evaluateHolding({ row: row === null ? null : { ...base, ...row }, fresh, globalStatus: 'ok', inCandidates: false, weight: 0.1, maxWeight: 0.2, plan: null, ...extra });

test('Signal: Kandidat mit Platz => NACHKAUFEN', () => assert.equal(ev({}, { inCandidates: true }).signal, 'NACHKAUFEN'));
test('Signal: kein Kandidat, im Halteband => HALTEN', () => assert.equal(ev({ pct: 0.15 }).signal, 'HALTEN'));
test('Signal: Klumpenrisiko verhindert Nachkauf', () => {
  const r = ev({}, { inCandidates: true, weight: 0.3 });
  assert.equal(r.signal, 'HALTEN');
  assert.ok(r.reasons.some((x) => x.includes('Klumpenrisiko')));
});
test('Signal: erstes H => VERKAUF PRÜFEN', () => assert.equal(ev({ H: true, pct: 0.25 }).signal, 'VERKAUF PRÜFEN'));
test('Signal: bestätigtes H => VERKAUF', () => assert.equal(ev({ H: true, H_prev: true, pct: 0.25 }).signal, 'VERKAUF'));
test('Signal: schwer => sofort VERKAUF', () => assert.equal(ev({ H: true, severe: true, pct: 0.6 }).signal, 'VERKAUF'));
test('Signal: Datenproblem => nie automatisch VERKAUF', () => {
  const r = ev({ data_ok: false, H: true, H_prev: true, reasons: ['stale'] }, { reasonLabel: () => 'Kurse veraltet' });
  assert.equal(r.signal, 'VERKAUF PRÜFEN');
  assert.ok(r.criteria[0].value.includes('Kurse veraltet'));
});
test('Signal: keine Daten => KEINE BEWERTUNG', () => assert.equal(ev(null).signal, 'KEINE BEWERTUNG'));
test('Signal: alte Daten => KEINE BEWERTUNG', () => assert.equal(ev({}, { fresh: { ok: false, abort: false, level: 'veraltet', label: '8 Tage alt' } }).signal, 'KEINE BEWERTUNG'));
test('Signal: Datenlauf fehlerhaft => KEINE BEWERTUNG', () => assert.equal(ev({}, { globalStatus: 'fehler' }).signal, 'KEINE BEWERTUNG'));
test('Rang allein ist kein Verkaufsgrund (Rang 15 % im Halteband)', () => assert.equal(ev({ pct: 0.15, rank: 180 }).signal, 'HALTEN'));
test('Sparplan: Top 5 % => FORTSETZEN', () => assert.equal(ev({ pct: 0.03 }, { plan: { active: true } }).plan.signal, 'SPARPLAN FORTSETZEN'));
test('Sparplan: aus Top 5 % gefallen => STOPPEN, Position HALTEN, Wechselkandidat', () => {
  const r = ev({ pct: 0.12 }, { plan: { active: true }, bestAlternative: { symbol: 'X', name: 'X AG' } });
  assert.equal(r.signal, 'HALTEN');
  assert.equal(r.plan.signal, 'SPARPLAN STOPPEN');
  assert.equal(r.plan.switchTo.symbol, 'X');
});
test('Sparplan: Verkaufssignal => STOPPEN', () => assert.equal(ev({ H: true, H_prev: true, pct: 0.3 }, { plan: { active: true } }).plan.signal, 'SPARPLAN STOPPEN'));
test('Sparplan: unter 200-Tage-Linie => STOPPEN', () => assert.equal(ev({ pct: 0.02, above_ma200: false }, { plan: { active: true } }).plan.signal, 'SPARPLAN STOPPEN'));
test('Inaktiver Sparplan erzeugt kein Sparplan-Signal', () => assert.equal(ev({}, { plan: { active: false } }).plan, null));

// ---------------------------------------------------------------- Daten / Backup
test('Aktualität: Grenzen', () => {
  assert.equal(freshness('2026-11-20', '2026-11-23').level, 'aktuell');
  assert.equal(freshness('2026-11-20', '2026-11-25').level, 'leicht veraltet');
  assert.equal(freshness('2026-11-20', '2026-11-28').level, 'veraltet');
  assert.equal(freshness('2026-11-20', '2026-12-05').abort, true);
  assert.equal(freshness(null).abort, true);
});
test('Backup-Prüfung', () => {
  assert.equal(validateBackup({ app: 'momentum-lab', schema: 1, data: { positions: [{ id: 'a' }], transactions: [{ id: 't', positionId: 'a', type: 'BUY', date: '2024-01-01' }] } }).ok, true);
  assert.equal(validateBackup({ app: 'andere-app', schema: 1, data: {} }).ok, false);
  assert.equal(validateBackup({ app: 'momentum-lab', schema: 99, data: {} }).ok, false);
  assert.equal(validateBackup({ app: 'momentum-lab', schema: 1, data: { positions: [], transactions: [{ id: 't', positionId: 'x', type: 'BUY', date: '2024-01-01' }] } }).ok, false);
});

// ---------------------------------------------------------------- Stage 2
const s2raw = { schema: 1, asof: '2026-11-20', status: 'ok', eligible: ['AAA'], messages: [],
  ranking: [{ symbol: 'AAA', decision: { code: 'STRONG_BUY' } }, { symbol: 'BBB', decision: { code: 'HARD_RISK' } }],
  all: { fields: ['symbol', 'score', 'A'], rows: [['AAA', 8.7, 9.1], ['CCC', 5.2, 4.0]] } };
test('Stage 2: Daten einlesen', () => {
  const s = parseStage2(s2raw);
  assert.equal(s.bySymbol.get('BBB').decision.code, 'HARD_RISK');
  assert.equal(s.allBySymbol.get('CCC').score, 5.2);
  assert.throws(() => parseStage2({ ...s2raw, schema: 99 }));
  assert.deepEqual(decisionCounts(s), { STRONG_BUY: 1, HARD_RISK: 1 });
});
test('Stage 2: keine Entscheidung bei alten oder abweichenden Daten', () => {
  const s = parseStage2(s2raw);
  assert.equal(stage2Usable(s, { asof: '2026-11-20' }, fresh).ok, true);
  assert.equal(stage2Usable(s, { asof: '2026-11-21' }, fresh).ok, false);
  assert.equal(stage2Usable(s, { asof: '2026-11-20' }, { ok: false, label: '8 Tage alt' }).ok, false);
  assert.equal(stage2Usable(null, { asof: '2026-11-20' }, fresh).ok, false);
  assert.equal(stage2Usable({ ...s, status: 'fehler' }, { asof: '2026-11-20' }, fresh).ok, false);
});
test('Stage 2: Kennzahlen formatieren', () => {
  assert.equal(fmtMetric(0.1234, 'pct'), '+12,3 %');
  assert.equal(fmtMetric(0.75, 'share'), '75 %');
  assert.equal(fmtMetric(0.4, 'share_signed'), '+0,40');
  assert.equal(fmtMetric(2.5, 'x'), '2,5×');
  assert.equal(fmtMetric(0.012, 'pp'), '+1,2 Pp.');
  assert.equal(fmtMetric(0.97, 'ratio'), '-3,0 % vom Hoch');
  assert.equal(fmtMetric(null, 'pct'), '–');
});

// ---------------------------------------------------------------- Autopilot
const apPlan = (o = {}) => ({
  rule: { n: 4, sector_cap: 2, market: 'soft' }, action: 'NORMAL',
  status: { A: ['H', 0.05], B: ['V', 0.4], C: ['W', 0.25], D: ['P', null] },
  buy_list: [
    { rank: 1, symbol: 'A', name: 'A', sector: 'Energie' },
    { rank: 2, symbol: 'E', name: 'E', sector: 'Energie' },
    { rank: 3, symbol: 'F', name: 'F', sector: 'IT' },
    { rank: 4, symbol: 'G', name: 'G', sector: 'IT' },
  ], ...o,
});
test('Autopilot: Verkauf, Branchengrenze und Beträge', () => {
  const hold = [{ symbol: 'A', mvEUR: 1000, sector: 'Energie' }, { symbol: 'B', mvEUR: 800, sector: 'IT' }];
  const r = buildPlan(apPlan({ status: { A: ['H', 0.05], B: ['V', 0.4] } }), hold, 1200);
  assert.deepEqual(r.sells.map((x) => x.symbol), ['B']);
  // 3 freie Plätze: E (Energie 2/2), F, G
  assert.deepEqual(r.buys.map((x) => x.symbol), ['E', 'F', 'G']);
  near(r.total, 1000 + 800 + 1200);
  near(r.target, 750);
  assert.deepEqual(r.buys.map((b) => Math.round(b.amount)), [750, 750, 500]);
});
test('Autopilot: Branchengrenze überspringt', () => {
  const hold = [{ symbol: 'A', mvEUR: 1000, sector: 'Energie' }, { symbol: 'X', mvEUR: 1000, sector: 'Energie' }];
  const r = buildPlan(apPlan({ status: { A: ['H', 0.05], X: ['H', 0.1] } }), hold, 1000);
  assert.deepEqual(r.buys.map((x) => x.symbol), ['F', 'G']);
  assert.equal(r.skipped[0].symbol, 'E');
});
test('Autopilot: wenig Geld -> keine Mini-Orders', () => {
  const r = buildPlan(apPlan({ status: {} }), [], 120);
  assert.deepEqual(r.buys.map((b) => b.amount), [50, 50]);
  assert.equal(r.waiting.length, 2);
});
test('Autopilot: Parken verkauft alles, keine Käufe', () => {
  const hold = [{ symbol: 'A', mvEUR: 1000, sector: 'Energie' }];
  const r = buildPlan(apPlan({ action: 'PARKEN' }), hold, 500);
  assert.equal(r.sells.length, 1);
  assert.equal(r.buys.length, 0);
});
test('Autopilot: Keine Neukäufe bei Abwärtstrend (soft)', () => {
  const r = buildPlan(apPlan({ action: 'KEINE_KAEUFE' }), [], 5000);
  assert.equal(r.buys.length, 0);
  near(r.rest, 5000);
});
test('Autopilot: volle Plätze -> untergewichtete auffüllen, Gewinner nicht', () => {
  const st = { A: ['H', 0.01], C: ['W', 0.2], F: ['H', 0.03], G: ['H', 0.04] };
  const hold = [{ symbol: 'A', mvEUR: 3000 }, { symbol: 'C', mvEUR: 500 }, { symbol: 'F', mvEUR: 1400 }, { symbol: 'G', mvEUR: 1400 }];
  const r = buildPlan(apPlan({ status: st }), hold, 500);
  assert.equal(r.buys.length, 0);
  assert.deepEqual(r.topups.map((t) => t.symbol), ['C']);
  near(r.topups[0].amount, 500);
});
test('Autopilot: unbekannte Aktie -> prüfen, zählt als Platz', () => {
  const r = buildPlan(apPlan(), [{ symbol: 'ZZZ', mvEUR: 100 }], 0);
  assert.equal(r.rows[0].todo, 'pruefen');
  assert.equal(r.freeSlots, 3);
});

// ---------------------------------------------------------------- Simulator
const simData = () => {
  // 25 Monate, 3 Aktien; A steigt 2 %/Monat, B fällt, C konstant; ETF steigt 1 %/Monat
  const K = 25;
  const pts = Array.from({ length: K + 1 }, (_, k) => new Date(Date.UTC(2010, k, 2)).toISOString().slice(0, 10));
  const sig = pts.slice(0, K);
  return {
    signal_dates: sig, points: pts, syms: ['A', 'B', 'C'], names: ['Alpha', 'Beta', 'Gamma'], sectors: ['IT', 'IT', 'Energie'],
    px: [pts.map((_, k) => 100 * 1.02 ** k), pts.map((_, k) => 100 * 0.97 ** k), pts.map(() => 50)],
    rank: sig.map(() => [0, 1, 2]), cand: sig.map((_, k) => (k < 12 ? [0, 1] : [0])), s2: sig.map(() => [0]), s2_normal: sig.map(() => [0]),
    hold: sig.map((_, k) => (k >= 3 ? '010' : '000')),
    bench: { msci_world: { name: 'W', start: pts[0], px: pts.map((_, k) => 10 * 1.01 ** k) }, sp500: { name: 'S', start: pts[0], px: pts.map(() => 20) } },
  };
};
const simOpts = { startYear: 2010, budget: 100, dyn: 0, feeBuy: 0, feeSell: 0, feeEtf: 0, spread: 0, spreadEtf: 0, hold: 'signal', rest: 'cash' };
test('Simulator: ETF-Sparplan = Summe der Anteile', () => {
  const r = simRun(simData(), 'sp500', simOpts);
  near(r.contrib, 2500);
  near(r.final, 2500);          // Kurs konstant
  assert.equal(r.taxesPaid, 0);
});
test('Simulator: Verkauf nach zwei Signalen, Erlös neu verteilt', () => {
  const r = simRun(simData(), 's1top10', simOpts);
  // B hat ab Monat 3 die Bedingung -> Verkauf in Monat 4
  assert.ok(r.yearly[2010].sells.includes('B'));
  assert.ok(r.final > r.contrib * 0.9);
});
test('Simulator: Restgeld ETF statt Cash', () => {
  const a = simRun(simData(), 's1top10', { ...simOpts, rest: 'etf' });
  const b = simRun(simData(), 's1top10', { ...simOpts, rest: 'cash' });
  assert.ok(a.final !== b.final);
});
test('Simulator: Gebühren und Dynamik', () => {
  const r = simRun(simData(), 'world', { ...simOpts, feeEtf: 1, dyn: 10 });
  near(r.fees, 25);
  near(r.contrib, 12 * 100 + 12 * 110 + 1 * 121);
});
test('Simulator: IRR stimmt bei 0 % und Monatsliste', () => {
  const d = simData();
  const flows = d.signal_dates.map((_, k) => [k, -100]);
  near(simIrr(flows, 0, d.points.length - 1, 2500, d), 0, 1e-6);
  const ml = monthList(d, 13);
  assert.equal(ml[0].name, 'Alpha'); assert.equal(ml[0].cand, true); assert.equal(ml[1].cand, false);
});
test('Simulator: feste Haltedauer verkauft nach 6 Monaten (nicht mehr auf der Liste)', () => {
  const r = simRun(simData(), 's1top10', { ...simOpts, hold: '6' });
  const sells = Object.values(r.yearly).flatMap((y) => y.sells);
  assert.ok(sells.includes('B'));
  assert.ok(!sells.includes('A'));   // A bleibt auf der Liste -> wird weiter gehalten
});

console.log(`${passed} bestanden, ${failed} fehlgeschlagen`);
process.exit(failed ? 1 : 0);

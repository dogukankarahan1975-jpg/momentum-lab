// JavaScript-Tests ohne Abhängigkeiten: node tests/js/run.mjs
import assert from 'node:assert/strict';
import { computePosition, planDates, planOverview, reconstructHistory, replay, estimateSaleTax } from '../../app/js/depot.js';
import { evaluateHolding } from '../../app/js/signals.js';
import { addMonths, parseDec } from '../../app/js/fmt.js';
import { freshness } from '../../app/js/data.js';
import { validateBackup } from '../../app/js/store.js';
import { parseStage2 } from '../../app/js/data.js';
import { fmtSignal, stage2Usable } from '../../app/js/stage2.js';
import { applyHiddenScreen, applyHiddenStage2 } from '../../app/js/hidden.js';
import { holdEnd, holdStatus, buildICS, splitBuy, nextScreeningDay } from '../../app/js/holding.js';
import { simulate as simRun, irr as simIrr, monthList, allowance as simAllowance, screenMonths, isScreenMonth, freqText } from '../../app/js/simulator.js';

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
test('Sparer-Pauschbetrag: 801 € bis 2022, 1.000 € ab 2023', () => {
  assert.equal(simAllowance(2022), 801);
  assert.equal(simAllowance(2023), 1000);
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

// ---------------------------------------------------------------- Stage 2 (v2)
const s2raw = { schema: 2, asof: '2026-11-20', status: 'ok', buy: ['AAA'], messages: [],
  ranking: [{ symbol: 'AAA', buy: true, stage2: { rank: 1, score: 7.1 } }, { symbol: 'BBB', buy: false, stage2: { rank: 6, score: 4.2 } }] };
test('Stage 2: Daten einlesen', () => {
  const s = parseStage2(s2raw);
  assert.equal(s.bySymbol.get('BBB').stage2.rank, 6);
  assert.deepEqual(s.buy, ['AAA']);
  assert.throws(() => parseStage2({ ...s2raw, schema: 99 }));
});
test('Stage 2: keine Rangfolge bei alten, abweichenden oder alten Schema-Daten', () => {
  const s = parseStage2(s2raw);
  assert.equal(stage2Usable(s, { asof: '2026-11-20' }, fresh).ok, true);
  assert.equal(stage2Usable(s, { asof: '2026-11-21' }, fresh).ok, false);
  assert.equal(stage2Usable(s, { asof: '2026-11-20' }, { ok: false, label: '8 Tage alt' }).ok, false);
  assert.equal(stage2Usable(null, { asof: '2026-11-20' }, fresh).ok, false);
  assert.equal(stage2Usable({ ...s, schema: 1 }, { asof: '2026-11-20' }, fresh).ok, false);
});
test('Stage 2: Signale formatieren', () => {
  assert.equal(fmtSignal('prox_52w', 0.95), '-5,0 %');
  assert.equal(fmtSignal('x', null), '–');
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
    rank: sig.map(() => [0, 1, 2]), cand: sig.map((_, k) => (k < 12 ? [0, 1] : [0])), s2: sig.map(() => [0]),
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
test('Screening-Monate verschieben', () => {
  assert.deepEqual(screenMonths('quarterly', 0), [1, 4, 7, 10]);
  assert.deepEqual(screenMonths('quarterly', 1), [2, 5, 8, 11]);
  assert.deepEqual(screenMonths('semiannual', 5), [6, 12]);
  assert.equal(screenMonths('monthly', 2), null);
  assert.ok(isScreenMonth('2024-03-01', 'quarterly', 2) && !isScreenMonth('2024-04-01', 'quarterly', 2));
  assert.equal(freqText('quarterly', 1), 'vierteljährlich (Feb, Mai, Aug, Nov)');
  assert.equal(freqText('annual', 6), 'jährlich (Juli)');
  const a = simRun(simData(), 's1top10', { ...simOpts, freq: 'quarterly', shift: 0 });
  const b = simRun(simData(), 's1top10', { ...simOpts, freq: 'quarterly', shift: 1 });
  assert.notEqual(a.months.filter((m) => m.screen).map((m) => m.k).join(), b.months.filter((m) => m.screen).map((m) => m.k).join());
});
test('Simulator: Startkapital + Budget nur als Starthilfe', () => {
  const r = simRun(simData(), 'sp500', { ...simOpts, initial: 1000, budgetMonths: 6 });
  near(r.contrib, 1000 + 6 * 100);           // danach keine Einzahlungen mehr
  const r2 = simRun(simData(), 's1top10', { ...simOpts, initial: 1000, budget: 0 });
  near(r2.contrib, 1000);
  const r3 = simRun(simData(), 's1top10', { ...simOpts, budgetMode: 'fixed', budgetMonths: 3 });
  near(r3.contrib, 300);
  assert.ok(r3.log.some((l) => l.name === 'Starthilfe beendet'));
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

test('Simulator: ETF-Sparplan verkauft nie, Wert = Anteile × Kurs', () => {
  const d = simData();
  const r = simRun(d, 'world', simOpts);
  assert.ok(r.log.every((x) => x.type === 'ETF-Kauf'));
  assert.equal(r.log.length, 25);
  const units = r.log.reduce((s, x) => s + x.shares, 0);
  near(r.final, units * d.bench.msci_world.px[d.points.length - 1]);
  assert.ok(r.final > r.contrib);
  assert.equal(r.taxesPaid, 0);
});
test('Steuer: sofort beim Verkauf einbehalten, Verlust im selben Jahr wird erstattet', () => {
  const d = simData();
  // A: +50 % bis Monat 1, dann -60 % bis Monat 2 (nur A auf der Liste, 1 Monat halten)
  d.px[0] = d.points.map((_, k) => (k === 0 ? 100 : k === 1 ? 150 : 60));
  d.cand = d.cand.map(() => [0]); d.rank = d.rank.map(() => [0]);
  const r = simRun(d, 's1top5', { ...simOpts, budget: 20000, hold: '1' });
  const tax = r.log.filter((x) => x.type === 'Steuer' && x.k <= 2);
  assert.ok(tax[0].k === 1 && tax[0].amount > 0);          // Gewinn im Februar -> sofort Steuer
  assert.ok(tax.some((x) => x.k === 2 && x.amount < 0));   // Verlust im März -> Erstattung
  const net = tax.filter((x) => Number(d.points[x.k].slice(0, 4)) === 2010).reduce((s, x) => s + x.amount, 0);
  assert.ok(net >= -1e-6);                                 // nie mehr erstattet als gezahlt
});
test('Simulator: festes Budget lässt Verkaufserlöse auf dem Konto', () => {
  const fx = simRun(simData(), 's1top10', { ...simOpts, budgetMode: 'fixed' });
  const re = simRun(simData(), 's1top10', { ...simOpts, budgetMode: 'reinvest' });
  assert.ok(fx.cash > 50);           // Erlös aus B liegt auf dem Konto
  assert.ok(re.cash < fx.cash);
  fx.months.forEach((m) => assert.ok(m.invest <= m.budget + 1e-9));
});
test('Simulator: Stage 2 Top 5 kauft die 5 besten der Stage-2-Rangfolge', () => {
  const d = simData();
  d.s2 = d.s2.map(() => [1, 0]);  // B vor A
  const r = simRun(d, 's2top5', { ...simOpts, rest: 'cash' });
  const first = r.log.filter((x) => x.type === 'Kauf' && x.k === 0).map((x) => x.sym);
  assert.deepEqual(first, ['B', 'A']);
});
test('Simulator: Protokoll stimmt mit Kontostand überein', () => {
  const r = simRun(simData(), 's1top5', { ...simOpts, feeBuy: 1, feeSell: 1, spread: 0.2 });
  const inflow = r.contrib + r.log.filter((x) => x.type === 'Verkauf').reduce((s, x) => s + x.amount, 0);
  const outflow = r.log.filter((x) => x.type !== 'Verkauf').reduce((s, x) => s + x.amount, 0);
  near(r.cash, inflow - outflow, 1e-6);
});

test('Simulator: normaler ETF-Sparplan mit Dynamik (Zinseszins, nie Verlust bei steigendem Kurs)', () => {
  const d = simData();
  const r = simRun(d, 'world', { ...simOpts, dyn: 2 });
  // Handrechnung: Anteile je Monat = Rate / Kurs
  let units = 0, paid = 0;
  for (let k = 0; k < 25; k++) { const rate = 100 * 1.02 ** Math.floor(k / 12); units += rate / d.bench.msci_world.px[k]; paid += rate; }
  near(r.contrib, paid);
  near(r.final, units * d.bench.msci_world.px[25]);
  assert.ok(r.final > r.contrib);
});
test('Simulator: Haltedauer 6 Monate mit Warten bis ±0', () => {
  const d = simData();
  // B fällt stetig -> bei "6" wird mit Verlust verkauft, bei "6be" gewartet
  const hard = simRun(d, 's1top10', { ...simOpts, hold: '6' });
  const be = simRun(d, 's1top10', { ...simOpts, hold: '6be' });
  assert.ok(hard.log.some((x) => x.type === 'Verkauf' && x.sym === 'B' && x.gain < 0));
  assert.ok(!be.log.some((x) => x.type === 'Verkauf' && x.sym === 'B'));
  assert.ok(be.log.some((x) => x.type === 'Halten' && x.sym === 'B'));
  // A steigt -> wird nach 6 Monaten im Plus verkauft
  assert.ok(be.log.some((x) => x.type === 'Verkauf' && x.sym === 'A' && x.gain > 0));
});

// ---------------------------------------------------------------- Haltedauer & Rechner
test('Haltedauer: Verkaufstermin = erster Werktag nach Ablauf', () => {
  assert.equal(holdEnd('2026-11-25', 6), '2026-06-01'.replace('2026', '2027'));   // 25.05.2027 -> 01.06.2027 (Di)
  assert.equal(holdEnd('2026-12-01', 6), '2027-06-01');                          // genau am Screening-Tag
  assert.equal(holdEnd('2026-01-15', 12), '2027-02-01');
  assert.equal(nextScreeningDay('2026-11-26'), '2026-12-01');
});
test('Haltedauer: Plus -> verkaufen, Minus mit ±0-Regel -> halten', () => {
  const it = { qty: 10, firstOpen: '2026-01-02', costOpen: 1000, mvEUR: 1100 };
  assert.equal(holdStatus({ holdMonths: 6, holdBE: true }, it, '2026-07-02').state, 'verkaufen');
  assert.equal(holdStatus({ holdMonths: 6, holdBE: true }, { ...it, mvEUR: 950 }, '2026-07-02').state, 'warten');
  assert.equal(holdStatus({ holdMonths: 6, holdBE: false }, { ...it, mvEUR: 950 }, '2026-07-02').state, 'verkaufen');
  assert.equal(holdStatus({ holdMonths: 6, holdBE: true }, { ...it, mvEUR: 1000.5 }, '2026-07-02').state, 'warten'); // 1 € Verkaufsgebühr
  assert.equal(holdStatus({ holdMonths: 6, holdBE: true }, it, '2026-03-01').state, 'laeuft');
  assert.equal(holdStatus({ holdMonths: null }, it, '2026-07-02'), null);
});
test('Kauf-Rechner: Gebühr je Kauf', () => {
  const r = splitBuy(2505, 5, 1);
  near(r.orderEach, 500); near(r.each, 501); near(r.fees, 5);
});
test('Kalender: gültige ICS-Datei mit Wecker', () => {
  const t = buildICS([{ uid: 'x', date: '2027-06-01', title: 'Verkaufen: A, B', desc: 'Test; mit Komma, ok' }]);
  assert.ok(t.startsWith('BEGIN:VCALENDAR') && t.includes('DTSTART;TZID=Europe/Berlin:20270601T080000') && t.includes('BEGIN:VALARM'));
  assert.ok(t.includes('Verkaufen: A\\, B'));
});

test('Simulator: Vorabpauschale ab 2018 und Haltedauer 3 Monate', () => {
  // 2018-2019: ETF steigt 1 %/Monat -> Vorabpauschale > 0, aber unter Pauschbetrag -> keine Steuer
  const K = 30;
  const pts = Array.from({ length: K + 1 }, (_, k) => new Date(Date.UTC(2018, k, 2)).toISOString().slice(0, 10));
  const d = { ...simData(), signal_dates: pts.slice(0, K), points: pts,
    px: [pts.map((_, k) => 100 * 1.02 ** k), pts.map((_, k) => 100 * 0.97 ** k), pts.map(() => 50)],
    rank: pts.slice(0, K).map(() => [0, 1, 2]), cand: pts.slice(0, K).map(() => [0, 1]), s2: pts.slice(0, K).map(() => [0]),
    hold: pts.slice(0, K).map(() => '000'),
    bench: { msci_world: { name: 'W', start: pts[0], px: pts.map((_, k) => 10 * 1.01 ** k) }, sp500: { name: 'S', start: pts[0], px: pts.map(() => 20) } } };
  const r = simRun(d, 'world', { ...simOpts, startYear: 2018, budget: 100000 });
  assert.ok(r.vpTotal > 0);
  assert.ok(r.taxesPaid > 0);         // großer Sparplan -> Vorabpauschale über Pauschbetrag
  const small = simRun(d, 'world', { ...simOpts, startYear: 2018 });
  assert.equal(small.taxesPaid, 0);
  const h3 = simRun(d, 's1top10', { ...simOpts, startYear: 2018, hold: '3' });
  assert.ok(h3.log.some((x) => x.type === 'Verkauf' && x.why.includes('3 Monate')));
});

test('Simulator: Min. Score kauft nur Kandidaten ab Mindestwert, sonst bleibt das Budget liegen', () => {
  const d = simData();
  d.cand_z = d.cand.map((c) => c.map((_, j) => (j === 0 ? 4.5 : 2.1)));
  const r = simRun(d, 's1min4', { ...simOpts, rest: 'etf', minScore: 4 });
  const buys = r.log.filter((x) => x.type === 'Kauf');
  assert.ok(buys.length && buys.every((x) => x.sym === 'A'));
  d.cand_z = d.cand.map((c) => c.map(() => 1.0));
  const none = simRun(d, 's1min4', { ...simOpts, rest: 'etf', minScore: 4 });
  assert.equal(none.log.filter((x) => x.type === 'Kauf' || x.type === 'ETF-Kauf').length, 0);
  near(none.cash, none.contrib);
});

test('Ausblenden: Kandidat fällt weg, nächster rückt nach; Stage 2 zählt neu', () => {
  const rows = ['A', 'B', 'C', 'D'].map((x, i) => ({ symbol: x, rank: i + 1, pct: 0.01 * (i + 1), Z: 3 - i, eligible: true, m6: 0.1, m12: 0.2 }));
  const scr = { rows, bySymbol: new Map(rows.map((r) => [r.symbol, r])), candidates: ['A', 'B', 'C'], top_pick: 'A',
    params: { candidate_max_pct: 0.1, require_positive_m6: true, require_positive_m12: true } };
  const h = applyHiddenScreen(scr, new Set(['A']));
  assert.deepEqual(h.candidates, ['B', 'C', 'D']);
  assert.equal(h.top_pick, null);
  const back = applyHiddenScreen(h, new Set());
  assert.deepEqual(back.candidates, ['A', 'B', 'C']); assert.equal(back.top_pick, 'A');
  const s2 = { top_n: 2, ranking: ['B', 'A', 'C'].map((x, i) => ({ symbol: x, buy: i < 2, stage2: { rank: i + 1, score: 5 - i } })) };
  const s2h = applyHiddenStage2(s2, new Set(['A']));
  assert.deepEqual(s2h.buy, ['B', 'C']); assert.equal(s2h.bySymbol.get('C').stage2.rank, 2);
});
test('Simulator: ausgeblendete Aktie wird auch rückwirkend nicht gekauft', () => {
  const r = simRun(simData(), 's1top5', { ...simOpts, exclude: ['A'] });
  assert.ok(!r.log.some((x) => x.type === 'Kauf' && x.sym === 'A'));
});

test('Korrektur Überlebenden-Effekt senkt nur Aktien-Strategien', () => {
  const d = { ...simData(), bias: { pa: 0.05 } };
  const a = simRun(d, 's1top5', { ...simOpts }), b = simRun(d, 's1top5', { ...simOpts, biasCorr: true });
  assert.ok(b.final < a.final);
});

test('Simulator: Enddatum begrenzt den Zeitraum', () => {
  const d = simData();
  const full = simRun(d, 's1top5', { ...simOpts });
  const yEnd = Number(d.points[2].slice(0, 4));
  const part = simRun(d, 's1top5', { ...simOpts, endYear: yEnd });
  assert.ok(part.end <= `${yEnd}-12-31` && part.contrib <= full.contrib);
});

test('Simulator: halbjährliches Screening kauft nur im Januar und Juli, Erlöse warten bis dahin', () => {
  const d = simData();
  const r = simRun(d, 's1top5', { ...simOpts, freq: 'semiannual', hold: '3' });
  const buyKs = [...new Set(r.log.filter((x) => x.type === 'Kauf').map((x) => x.k))];
  const k0 = Math.min(...buyKs);
  assert.ok(buyKs.every((k) => k === k0 || [1, 7].includes(Number(d.points[k].slice(5, 7)))));
  assert.ok(r.log.some((x) => x.type === 'Verkauf'));
});

console.log(`${passed} bestanden, ${failed} fehlgeschlagen`);
process.exit(failed ? 1 : 0);

// JavaScript-Tests ohne Abhängigkeiten: node tests/js/run.mjs
import assert from 'node:assert/strict';
import { computePosition, planDates, planOverview, reconstructHistory, replay, estimateSaleTax } from '../../app/js/depot.js';
import { evaluateHolding } from '../../app/js/signals.js';
import { addMonths, parseDec } from '../../app/js/fmt.js';
import { freshness } from '../../app/js/data.js';
import { validateBackup } from '../../app/js/store.js';
import { parseStage2 } from '../../app/js/data.js';
import { decisionCounts, fmtMetric, stage2Usable } from '../../app/js/stage2.js';

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

console.log(`${passed} bestanden, ${failed} fehlgeschlagen`);
process.exit(failed ? 1 : 0);

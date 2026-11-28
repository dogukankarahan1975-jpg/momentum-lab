// Unabhängige Prüfung des Simulators auf echten Daten (läuft im Datenlauf, Ergebnis in archive/audit/).
// Aufruf: node tools/audit_sim.mjs <simulator-xyz.json> [<membership.json>]
// Geprüft wird je Strategie und Einstellung:
//  1. Jeder Kauf/Verkauf zum Kurs des Tages aus den Daten (keine erfundenen oder verschobenen Kurse)
//  2. Gekaufte Aktien standen am Stichtag auf der Liste (Kandidaten/Rangliste) – und waren laut Indexliste Mitglied
//  3. Eingezahlt = Startkapital + Monatsbudgets laut Einstellung
//  4. Endwert = Konto + Stückzahl × letzter Kurs (Buchhaltung geht auf)
//  5. Steuer unabhängig nachgerechnet (Jahr für Jahr aus den Verkaufsgewinnen, Dividenden, Verlustvortrag, Pauschbetrag)
import fs from 'node:fs';
import { simulate, allowance } from '../app/js/simulator.js';

const [file, memFile] = process.argv.slice(2);
const data = JSON.parse(fs.readFileSync(file, 'utf8'));
const membership = memFile && fs.existsSync(memFile) ? JSON.parse(fs.readFileSync(memFile, 'utf8')) : null;
const TAX = 0.26375;
const yearOf = (d) => Number(String(d).slice(0, 4));
const rel = (a, b) => Math.abs(a - b) / Math.max(1, Math.abs(b));

const settings = [
  { name: 'monatlich, Verkaufssignal', o: { hold: 'signal', freq: 'monthly' } },
  { name: 'vierteljährlich, Verkaufssignal', o: { hold: 'signal', freq: 'quarterly' } },
  { name: 'vierteljährlich, fest 3 Monate', o: { hold: '3', freq: 'quarterly' } },
  { name: 'monatlich, fest 1 Monat', o: { hold: '1', freq: 'monthly' } },
  { name: 'Startkapital + 24 Monate Budget', o: { hold: 'signal', freq: 'quarterly', initial: 10000, budgetMonths: 24 } },
];
const strategies = ['s1top5', 's1top10', 's1min4', 's2top5', 'hold1', 'world', 'sp500'];
const firstYear = yearOf(data.signal_dates[0]);
const results = [];
let fails = 0;

for (const st of strategies) {
  if ((st === 'world' && !data.bench?.msci_world) || (st === 'sp500' && !data.bench?.sp500)) continue;
  for (const s of settings) {
    const o = { startYear: firstYear, budget: 500, dyn: 0, feeBuy: 1, feeSell: 1, feeEtf: 0, spread: 0.2, spreadEtf: 0.1,
      rest: 'top', minScore: 3, ...s.o };
    const issues = [];
    let r;
    try {
      r = simulate(data, st, o);
    } catch (e) {
      issues.push(`Absturz: ${e.message}`);
      results.push({ strategy: st, setting: s.name, ok: false, issues });
      fails += 1;
      continue;
    }
    const idx = new Map(data.syms.map((x, i) => [x, i]));
    // 1 + 2: Kurse und Listen
    let nBuy = 0, nSell = 0, badPx = 0, offList = 0, notMember = 0;
    for (const l of r.log) {
      if (l.type !== 'Kauf' && l.type !== 'Verkauf') continue;
      const i = idx.get(l.sym);
      const px = data.px[i]?.[l.k];
      if (!(px > 0) || rel(l.px, px) > 1e-9) badPx += 1;
      if (l.type === 'Kauf') {
        nBuy += 1;
        const lists = new Set([...(data.cand[l.k] || []), ...(data.rank[l.k] || []), ...(data.s2[l.k] || [])]);
        if (!lists.has(i)) offList += 1;
        if (membership) {
          const m = String(data.signal_dates[l.k]).slice(0, 7);
          const keys = Object.keys(membership).filter((x) => x <= m).sort();
          const mem = keys.length ? membership[keys[keys.length - 1]] : null;
          if (mem && !mem.includes(l.sym)) notMember += 1;
        }
      } else nSell += 1;
    }
    if (badPx) issues.push(`${badPx} Orders mit Kurs, der nicht dem Tageskurs entspricht`);
    if (offList) issues.push(`${offList} Käufe nicht auf der Liste des Stichtags`);
    if (notMember) issues.push(`${notMember} Käufe von Aktien, die am Stichtag NICHT im Index waren`);
    // 3: Einzahlungen
    let expect = 0;
    for (let k = r.k0; k < r.k0 + r.months.length; k++) {
      const paying = !(o.budgetMonths > 0) || k - r.k0 < o.budgetMonths;
      expect += (paying ? o.budget : 0) + (k === r.k0 && st !== 'hold1' ? (o.initial || 0) : 0);
    }
    if (st === 'hold1') {   // „Gewinner halten“: nie verkaufen (außer Datenende), je Termin genau eine Aktie
      const badSell = r.log.filter((l) => l.type === 'Verkauf' && !/Kursdaten enden/.test(l.why || '')).length;
      if (badSell) issues.push(`${badSell} Verkäufe bei „Gewinner halten“ ohne Datenende`);
      const perK = new Map();
      for (const l of r.log) if (l.type === 'Kauf') perK.set(l.k, (perK.get(l.k) || 0) + 1);
      const multi = [...perK.values()].filter((n) => n > 1).length;
      if (multi) issues.push(`${multi} Termine mit mehr als einem Kauf`);
    }
    if (rel(r.contrib, expect) > 1e-9) issues.push(`Eingezahlt ${r.contrib.toFixed(2)} statt ${expect.toFixed(2)}`);
    // 4: Endwert
    let hold = 0;
    for (const p of r.open || []) hold += p.value || 0;
    const recon = r.cash + hold + (r.etfValue || 0);
    if (rel(r.final, recon) > 1e-6) issues.push(`Endwert ${r.final.toFixed(2)} ≠ Konto + Bestand ${recon.toFixed(2)}`);
    // 5: Steuer unabhängig (nur Aktien-Strategien; ETF: Vorabpauschale wird separat in den Einheitstests geprüft)
    if (st !== 'world' && st !== 'sp500') {
      const gains = {};
      for (const l of r.log) if (l.type === 'Verkauf') { const y = yearOf(data.points[l.k]); gains[y] = (gains[y] || 0) + l.gain; }
      const years = Object.keys(r.yearly).map(Number).sort((a, b) => a - b);
      let carry = 0, tax = 0;
      for (const y of years) {
        const g = (gains[y] || 0) + carry;
        const div = r.yearly[y].div || 0;
        tax += Math.max(0, Math.max(0, g) + div - allowance(y)) * TAX;
        carry = Math.min(0, g);
      }
      if (Math.abs(tax - r.taxesPaid) > 0.05) issues.push(`Steuer nachgerechnet ${tax.toFixed(2)} €, Simulator ${r.taxesPaid.toFixed(2)} €`);
    }
    if (!Number.isFinite(r.final) || !Number.isFinite(r.afterTax)) issues.push('Endwert nicht berechenbar');
    const ok = issues.length === 0;
    if (!ok) fails += 1;
    results.push({ strategy: st, setting: s.name, ok, issues, buys: nBuy, sells: nSell,
      final: Math.round(r.final), contrib: Math.round(r.contrib), taxes: Math.round(r.taxesPaid), dividends: Math.round(r.divTotal || 0),
      irr: Number.isFinite(r.irr) ? Math.round(r.irr * 1000) / 10 : null, start: r.start, end: r.end });
  }
}
process.stdout.write(JSON.stringify({ file: file.split('/').pop(), checks: results.length, failed: fails, results }));

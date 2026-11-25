// Simulator-Abschnitt im Backtest: Strategien wählen, Budget und Kosten einstellen, Vermögensverlauf nachvollziehen.
import { lineChart } from '../charts.js';
import { fmtDate, fmtEUR, fmtNum, fmtPct, parseDec } from '../fmt.js';
import { DEFAULTS, HOLD_LABEL, REST_LABEL, STRATEGIES, monthList, simulate, startIndex } from '../simulator.js';
import { getSetting, setSetting } from '../store.js';
import { html, note } from '../ui.js';

const COLORS = { world: 'var(--s1)', sp500: 'var(--s4)', s1top5: 'var(--s2)', s1top10: 'var(--s3)', s2: 'var(--s5)' };

export async function renderSimulator(el, data) {
  if (!data) {
    el.innerHTML = String(note('info', 'Die Simulator-Daten entstehen beim nächsten Monatswechsel bzw. nach dem nächsten Backtest-Lauf.'));
    return;
  }
  const saved = await getSetting('simOpts', null);
  const o = { ...DEFAULTS, ...(saved || {}) };
  const firstYear = Number(data.signal_dates[0].slice(0, 4));
  const lastYear = Number(data.signal_dates[data.signal_dates.length - 1].slice(0, 4)) - 2;
  const benchStart = (k) => data.bench?.[k]?.start || null;

  const form = html`
    <div class="panel">
      <h3 style="margin-top:0">Was wird hier getestet?</h3>
      <ul class="small" style="padding-left:18px;margin:0">
        <li><b>Echte Kurse von damals</b> (Yahoo Finance, in Euro umgerechnet mit EZB-Kursen). Keine erfundenen Zahlen${data.demo ? html` – <b>außer jetzt: DEMO-Daten</b>` : ''}.</li>
        <li>Für <b>jeden Monat seit ${fmtDate(data.signal_dates[0])}</b> wird das Screening mit den Daten von damals nachgestellt. Es entsteht genau die Liste, die die App am jeweiligen Monatsende gezeigt hätte. Ganz unten kannst du jede Monatsliste ansehen.</li>
        <li>Gekauft wird am nächsten Handelstag zum Schlusskurs. Das Monatsbudget wird <b>zu gleichen Teilen</b> auf die Aktien der aktuellen Liste verteilt, Verkaufserlöse kommen dazu.</li>
        <li><b>Stage 2</b> ist nur mit seinem Kursteil testbar. ${data.notes?.stage2 || ''}</li>
        <li><b>Haken:</b> ${data.notes?.survivorship || ''}</li>
      </ul>
    </div>
    <h3>Einstellungen</h3>
    <div class="panel" id="simform">
      <div class="small" style="margin-bottom:6px">Strategien vergleichen</div>
      <div class="legend" id="simstrat">${Object.entries(STRATEGIES).map(([k, s]) => html`<button data-k="${k}" aria-pressed="${o.strategies.includes(k)}"><span class="swatch" style="background:${COLORS[k]}"></span>${s.short}</button>`)}</div>
      <div class="grid2" style="margin-top:10px">
        <label class="field"><span>Start</span><select name="startYear">${Array.from({ length: lastYear - firstYear + 1 }, (_, i) => firstYear + i).map((y) => html`<option value="${y}" ${y === o.startYear ? 'selected' : ''}>${y}</option>`)}</select></label>
        <label class="field"><span>Monatsbudget (€)</span><input name="budget" inputmode="decimal" value="${o.budget}"></label>
        <label class="field"><span>Dynamik pro Jahr (%)</span><input name="dyn" inputmode="decimal" value="${String(o.dyn).replace('.', ',')}"></label>
        <label class="field"><span>Gebühr je Kauf (€)</span><input name="feeBuy" inputmode="decimal" value="${String(o.feeBuy).replace('.', ',')}"></label>
        <label class="field"><span>Gebühr je Verkauf (€)</span><input name="feeSell" inputmode="decimal" value="${String(o.feeSell).replace('.', ',')}"></label>
        <label class="field"><span>ETF-Sparplan je Ausführung (€)</span><input name="feeEtf" inputmode="decimal" value="${String(o.feeEtf).replace('.', ',')}"></label>
        <label class="field"><span>Spread Aktien (%)</span><input name="spread" inputmode="decimal" value="${String(o.spread).replace('.', ',')}"></label>
        <label class="field"><span>Spread ETF (%)</span><input name="spreadEtf" inputmode="decimal" value="${String(o.spreadEtf).replace('.', ',')}"></label>
      </div>
      <label class="field"><span>Wie lange werden Aktien gehalten?</span><select name="hold">
        ${['signal', '6', '12'].map((h) => html`<option value="${h}" ${String(o.hold) === h ? 'selected' : ''}>${h === 'signal' ? 'Bis zum Verkaufssignal der App' : `Immer ${h} Monate`}</option>`)}</select></label>
      <label class="field"><span>Weniger Kandidaten als Plätze?</span><select name="rest">
        ${['etf', 'cash', 'top'].map((r) => html`<option value="${r}" ${o.rest === r ? 'selected' : ''}>${{ etf: 'Rest in MSCI World ETF', cash: 'Rest auf dem Konto (0 %)', top: 'Immer Top 5/10 kaufen' }[r]}</option>`)}</select></label>
      <p class="xs muted" style="margin:-4px 0 8px">Verkaufssignal = Aktie an zwei Monatsenden hintereinander nicht mehr im besten Fünftel (sofort bei schwerer Verschlechterung). Bei 6 oder 12 Monaten wird danach verkauft, außer die Aktie steht dann noch auf der Liste. Bei weniger Kandidaten als Plätzen: Rest in den ETF, aufs Konto (wird im nächsten Monat mit angelegt) oder immer die Bestplatzierten kaufen, auch ohne Kandidatenstatus. Stage 2 kauft alle Aktien, die beide Bedingungen erfüllen; ohne Treffer gilt die gleiche Regel.</p>
      <p class="xs muted" style="margin:0">Voreinstellung Trade Republic: 1 € je Order, ETF-Sparplan kostenlos. Der Spread ist eine Annahme: Er wird je zur Hälfte beim Kauf und beim Verkauf berechnet. Steuer: 26,375 % auf realisierte Gewinne, 1.000 € Pauschbetrag pro Jahr, Verluste werden vorgetragen. ETF: 30 % Teilfreistellung, Vorabpauschale nicht berücksichtigt.</p>
    </div>
    <div id="simout"></div>`;
  el.innerHTML = String(form);

  const out = el.querySelector('#simout');
  const run = async () => {
    const opts = { ...o };
    // gemeinsamer Start: wenn ein Vergleichsindex später beginnt, verschiebt sich der Start für alle
    const notes = [];
    for (const k of opts.strategies) {
      const st = STRATEGIES[k];
      if (st.kind === 'etf') {
        const s = benchStart(st.bench);
        if (!s) { notes.push(`${st.label}: keine Kursdaten vorhanden.`); continue; }
        const minY = Number(s.slice(0, 4)) + 1;
        if (opts.startYear < minY) { notes.push(`Start auf ${minY} verschoben: ${data.bench[st.bench].name} hat erst ab ${fmtDate(s)} Kurse.`); opts.startYear = minY; }
      }
    }
    const keys = opts.strategies.filter((k) => STRATEGIES[k].kind !== 'etf' || benchStart(STRATEGIES[k].bench));
    if (!keys.length) { out.innerHTML = String(note('info', 'Wähle oben mindestens eine Strategie.')); return; }
    const res = keys.map((k) => simulate(data, k, opts));
    const best = res.reduce((a, r) => (r.afterTax > (a?.afterTax ?? -Infinity) ? r : a), null);
    const k0 = startIndex(data, opts.startYear);
    const parts = [];
    for (const n of notes) parts.push(note('info', n));
    parts.push(html`<h3>Ergebnis: ${fmtEUR(opts.budget, 0)} pro Monat ab ${fmtDate(data.points[k0])}${opts.dyn ? `, +${fmtNum(opts.dyn, 1)} % pro Jahr` : ''}</h3>
      <p class="xs muted">Haltedauer: ${HOLD_LABEL[opts.hold]}. ${REST_LABEL[opts.rest]}.</p>
      <div class="panel"><div id="simchart"></div><p class="xs muted" style="margin:6px 0 0">Depotwert in Euro vor Steuern. Graue Linie = eingezahltes Geld.</p></div>`);
    for (const r of res) {
      const gain = r.afterTax - r.contrib;
      parts.push(html`<div class="panel" style="border-left:4px solid ${COLORS[r.key]}">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline"><h3 style="margin:0">${r.label}</h3>${r === best && res.length > 1 ? html`<span class="badge b-buy">Höchstes Endvermögen</span>` : ''}</div>
        <div class="grid2" style="margin-top:8px">
          <div class="stat"><div class="l">Nach Steuern (alles verkauft)</div><div class="v">${fmtEUR(r.afterTax, 0)}</div></div>
          <div class="stat"><div class="l">Eingezahlt</div><div class="v">${fmtEUR(r.contrib, 0)}</div></div>
          <div class="stat"><div class="l">Gewinn nach Steuern</div><div class="v ${gain >= 0 ? 'pos' : 'neg'}">${fmtEUR(gain, 0)}</div></div>
          <div class="stat"><div class="l">Rendite p. a. nach Steuern</div><div class="v">${fmtPct(r.irrAfter)}</div></div>
        </div>
        <p class="xs muted" style="margin:8px 0 0">Vor Steuern ${fmtEUR(r.final, 0)} (${fmtPct(r.irr)} p. a.). Größter Rückgang ${fmtPct(r.maxDD, 0)}. ${fmtNum(r.trades, 0)} Orders, Gebühren ${fmtEUR(r.fees, 0)}, Spread ${fmtEUR(r.spreadCost, 0)}, laufend gezahlte Steuern ${fmtEUR(r.taxesPaid, 0)}, Steuer beim Verkauf am Ende ${fmtEUR(r.endTax, 0)}.</p>
      </div>`);
    }
    // Jahresprotokoll
    parts.push(html`<h3>Jahr für Jahr</h3>
      <label class="field"><span>Strategie</span><select id="simyear">${res.map((r) => html`<option value="${r.key}">${r.label}</option>`)}</select></label>
      <div id="simyt"></div>`);
    // Monatslisten
    const months = data.signal_dates.map((d, k) => [k, d]).filter(([k]) => k >= k0).reverse();
    parts.push(html`<h3>Welche Aktien standen damals auf der Liste?</h3>
      <label class="field"><span>Monatsende</span><select id="simmonth">${months.map(([k, d]) => html`<option value="${k}">${fmtDate(d)}</option>`)}</select></label>
      <div id="simml"></div>`);
    out.innerHTML = parts.join('');
    lineChart(out.querySelector('#simchart'), {
      height: 240, label: 'Depotwert im Simulator', yFmt: (v) => `${fmtNum(v / 1000, 0)} T`, tipFmt: (v) => fmtEUR(v, 0),
      series: [...res.map((r) => ({ name: r.label, short: r.short, points: r.series.map((p) => [p[0], p[1]]), color: COLORS[r.key] })),
        { name: 'Eingezahlt', short: 'Einzahlung', points: res[0].series.map((p) => [p[0], p[2]]), color: 'var(--ink-3)' }],
    });
    const drawYears = () => {
      const r = res.find((x) => x.key === out.querySelector('#simyear').value) || res[0];
      const ys = Object.keys(r.yearly).sort();
      let cum = 0;
      const rows = ys.map((y) => {
        const v = r.yearly[y];
        cum += v.contrib;
        const hold = v.holdings?.length ? v.holdings.join(', ') : (STRATEGIES[r.key].kind === 'etf' ? 'ETF' : '–');
        return html`<tr><td class="sticky">${y}</td><td class="n">${fmtEUR(cum, 0)}</td><td class="n">${fmtEUR(v.value, 0)}</td><td class="n">${fmtEUR(v.tax, 0)}</td><td class="n">${v.trades}</td><td style="min-width:220px;white-space:normal" class="xs">${hold}${v.etf && STRATEGIES[r.key].kind !== 'etf' ? ' + MSCI World ETF' : ''}</td></tr>`;
      });
      out.querySelector('#simyt').innerHTML = String(html`<div class="table-wrap"><table><thead><tr><th class="sticky">Jahr</th><th class="n">Eingezahlt</th><th class="n">Wert Jahresende</th><th class="n">Steuer</th><th class="n">Orders</th><th>Bestand am Jahresende</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="xs muted">Steuer = im Folgejahr gezahlte Abgeltungsteuer auf die Gewinne dieses Jahres. Letzte Zeile: Wert am letzten Kurstag.</p>`);
    };
    const drawMonth = () => {
      const k = Number(out.querySelector('#simmonth').value);
      const list = monthList(data, k);
      out.querySelector('#simml').innerHTML = String(html`<div class="group">${list.map((x) => html`<div class="row"><div class="grow"><div class="title">${x.rank}. ${x.name}</div><div class="sub">${x.sector || ''}</div></div>
        <div class="end">${x.cand ? html`<span class="badge b-buy">Kandidat</span>` : html`<span class="badge b-hold">kein Kandidat</span>`}${x.s2 ? html` <span class="badge b-cont">Stage 2</span>` : ''}</div></div>`)}</div>
        <p class="xs muted">Rangfolge nach Stage-1-Score am ${fmtDate(data.signal_dates[k])}, nur mit Kursen bis zu diesem Tag. "Kandidat" = erfüllt alle Stage-1-Regeln. Gekauft wurde am ${fmtDate(data.points[k])}.</p>`);
    };
    out.querySelector('#simyear').onchange = drawYears;
    out.querySelector('#simmonth').onchange = drawMonth;
    drawYears();
    drawMonth();
  };

  const num = (v, d) => { const x = parseDec(String(v)); return Number.isFinite(x) && x >= 0 ? x : d; };
  el.querySelector('#simform').addEventListener('change', async (e) => {
    const t = e.target;
    if (!t.name) return;
    if (t.name === 'hold' || t.name === 'rest') o[t.name] = t.value;
    else if (t.name === 'startYear') o.startYear = Number(t.value);
    else o[t.name] = num(t.value, DEFAULTS[t.name]);
    await setSetting('simOpts', o);
    run();
  });
  el.querySelector('#simstrat').addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-k]');
    if (!b) return;
    const k = b.dataset.k;
    o.strategies = o.strategies.includes(k) ? o.strategies.filter((x) => x !== k) : [...o.strategies, k];
    b.setAttribute('aria-pressed', String(o.strategies.includes(k)));
    await setSetting('simOpts', o);
    run();
  });
  run();
}

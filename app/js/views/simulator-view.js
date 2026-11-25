// Simulator-Abschnitt im Backtest: Strategien wählen, Budget und Kosten einstellen, Vermögensverlauf nachvollziehen.
import { lineChart } from '../charts.js';
import { fmtDate, fmtEUR, fmtNum, fmtPct, parseDec } from '../fmt.js';
import { BUDGET_LABEL, DEFAULTS, HOLD_LABEL, REST_LABEL, STRATEGIES, monthList, simulate, startIndex } from '../simulator.js';
import { getSetting, setSetting } from '../store.js';
import { html, note } from '../ui.js';

const COLORS = { world: 'var(--s1)', sp500: 'var(--s4)', s1top5: 'var(--s2)', s1top10: 'var(--s3)', s2: 'var(--s5)' };

function toastFee() {
  import('../ui.js').then((u) => u.toast?.('Gebühr oder Spread unrealistisch hoch – auf Standard zurückgesetzt'));
}

export async function renderSimulator(el, data) {
  if (!data) {
    el.innerHTML = String(note('info', 'Die Simulator-Daten entstehen beim nächsten Monatswechsel bzw. nach dem nächsten Backtest-Lauf.'));
    return;
  }
  const saved = await getSetting('simOpts', null);
  const o = { ...DEFAULTS, ...(saved || {}) };
  if (!['signal', '6', '12', '6be', '12be'].includes(String(o.hold))) o.hold = DEFAULTS.hold;
  // Schutz gegen versehentlich hohe Gebühren (z. B. Sparrate ins Gebührenfeld getippt)
  for (const f of ['feeBuy', 'feeSell', 'feeEtf']) if (!(o[f] >= 0) || o[f] > Math.min(Math.max(0, o.budget * 0.1), 50)) o[f] = DEFAULTS[f];
  for (const f of ['spread', 'spreadEtf']) if (!(o[f] >= 0) || o[f] > 5) o[f] = DEFAULTS[f];
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
        <label class="field"><span>Gebühr je ETF-Sparrate (€)</span><input name="feeEtf" inputmode="decimal" value="${String(o.feeEtf).replace('.', ',')}"></label>
        <label class="field"><span>Spread Aktien (%)</span><input name="spread" inputmode="decimal" value="${String(o.spread).replace('.', ',')}"></label>
        <label class="field"><span>Spread ETF (%)</span><input name="spreadEtf" inputmode="decimal" value="${String(o.spreadEtf).replace('.', ',')}"></label>
      </div>
      <label class="field"><span>Budget der Aktien-Strategien</span><select name="budgetMode">
        ${['reinvest', 'fixed'].map((m) => html`<option value="${m}" ${o.budgetMode === m ? 'selected' : ''}>${m === 'reinvest' ? 'Budget + Verkaufserlöse anlegen' : 'Nur festes Monatsbudget anlegen'}</option>`)}</select></label>
      <label class="field"><span>Wie lange werden Aktien gehalten?</span><select name="hold">
        ${['signal', '6', '6be', '12', '12be'].map((h) => html`<option value="${h}" ${String(o.hold) === h ? 'selected' : ''}>${{ signal: 'Bis zum Verkaufssignal der App', 6: '6 Monate, dann verkaufen', '6be': '6 Monate, im Minus warten bis ±0', 12: '12 Monate, dann verkaufen', '12be': '12 Monate, im Minus warten bis ±0' }[h]}</option>`)}</select></label>
      <label class="field"><span>Weniger Kandidaten als Plätze?</span><select name="rest">
        ${['etf', 'cash', 'top'].map((r) => html`<option value="${r}" ${o.rest === r ? 'selected' : ''}>${{ etf: 'Rest in MSCI World ETF', cash: 'Rest auf dem Konto (0 %)', top: 'Immer Top 5/10 kaufen' }[r]}</option>`)}</select></label>
      <p class="xs muted" style="margin:-4px 0 8px">Verkaufssignal = Aktie an zwei Monatsenden hintereinander nicht mehr im besten Fünftel (sofort bei schwerer Verschlechterung). Bei 6 oder 12 Monaten wird am ersten Monatsende nach Ablauf verkauft, im Plus wie im Minus; mit „warten bis ±0“ wird eine Aktie im Minus weiter gehalten und erst verkauft, wenn der Erlös nach Kosten wieder den Einstand deckt. Steht die Aktie dann noch auf der Liste, wird sie mit dem neuen Geld wieder gekauft. Bei weniger Kandidaten als Plätzen: Rest in den ETF, aufs Konto (wird im nächsten Monat mit angelegt) oder immer die Bestplatzierten kaufen, auch ohne Kandidatenstatus. Stage 2 kauft nur Aktien, die beide Bedingungen erfüllen, auch wenn es nur eine ist; gibt es keine, wird keine Aktie gekauft (der Betrag geht in den ETF bzw. bleibt auf dem Konto). ETF-Sparpläne: jeden Monat wird das Monatsbudget (mit Dynamik) in den ETF gesteckt, nie verkauft; „Gebühr je ETF-Sparrate“ ist nur die Ausführungsgebühr (Trade Republic: 0 €). Bei „Nur festes Monatsbudget“ bleiben Verkaufserlöse auf dem Konto (0 % Zins) und zählen zum Vermögen.</p>
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
      <p class="xs muted">Haltedauer: ${HOLD_LABEL[opts.hold]}. ${REST_LABEL[opts.rest]}. ${BUDGET_LABEL[opts.budgetMode]}.</p>
      <div class="panel"><div id="simchart"></div><p class="xs muted" style="margin:6px 0 0">Depotwert in Euro vor Steuern. Graue Linie = eingezahltes Geld.</p></div>`);
    for (const r of res) {
      const isEtf = r.kind === 'etf';
      const gainNow = r.final - r.contrib;
      const gainAfter = r.afterTax - r.contrib;
      parts.push(html`<div class="panel" style="border-left:4px solid ${COLORS[r.key]}">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline"><h3 style="margin:0">${r.label}</h3>${r === best && res.length > 1 ? html`<span class="badge b-buy">Am meisten nach Steuern</span>` : ''}</div>
        <div class="grid2" style="margin-top:8px">
          <div class="stat"><div class="l">Vermögen heute${isEtf ? ' (nie verkauft)' : ''}</div><div class="v">${fmtEUR(r.final, 0)}</div></div>
          <div class="stat"><div class="l">Eingezahlt</div><div class="v">${fmtEUR(r.contrib, 0)}</div></div>
          <div class="stat"><div class="l">${isEtf ? 'Buchgewinn' : 'Gewinn'}</div><div class="v ${gainNow >= 0 ? 'pos' : 'neg'}">${fmtEUR(gainNow, 0)}</div></div>
          <div class="stat"><div class="l">Rendite pro Jahr</div><div class="v">${fmtPct(r.irr)}</div></div>
        </div>
        <p class="xs muted" style="margin:8px 0 0">${isEtf
          ? html`Jeden Monat gekauft, nie etwas verkauft, keine Steuer gezahlt. Nur falls du heute alles verkaufen würdest: ${fmtEUR(r.afterTax, 0)} nach Steuern (Gewinn ${fmtEUR(gainAfter, 0)}, ${fmtPct(r.irrAfter)} p. a.).`
          : html`Darin ${fmtEUR(r.cash, 0)} auf dem Konto${r.etfValue > 1 ? html` und ${fmtEUR(r.etfValue, 0)} im MSCI World ETF` : ''}. Bereits gezahlte Steuern ${fmtEUR(r.taxesPaid, 0)}. Falls du heute alles verkaufst: ${fmtEUR(r.afterTax, 0)} nach Steuern (Gewinn ${fmtEUR(gainAfter, 0)}, ${fmtPct(r.irrAfter)} p. a.).`}
          Größter Rückgang ${fmtPct(r.maxDD, 0)}. ${fmtNum(r.trades, 0)} Orders, Gebühren ${fmtEUR(r.fees, 0)}, Spread ${fmtEUR(r.spreadCost, 0)}.</p>
      </div>`);
    }
    // Jahresübersicht
    parts.push(html`<h3>Jahr für Jahr</h3>
      <label class="field"><span>Strategie</span><select id="simyear">${res.map((r) => html`<option value="${r.key}">${r.label}</option>`)}</select></label>
      <div id="simyt"></div>`);
    // Protokoll
    parts.push(html`<h3>Jede Order nachvollziehen</h3>
      <div class="grid2"><label class="field"><span>Strategie</span><select id="logstrat">${res.map((r) => html`<option value="${r.key}">${r.short}</option>`)}</select></label>
      <label class="field"><span>Jahr</span><select id="logyear"></select></label></div>
      <div id="simlog"></div>`);
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
        return html`<tr><td class="sticky">${y}</td><td class="n">${fmtEUR(cum, 0)}</td><td class="n">${fmtEUR(v.value, 0)}</td><td class="n">${fmtEUR(v.tax, 0)}</td><td class="n">${v.trades}</td><td class="n">${fmtEUR(v.cash, 0)}</td><td style="min-width:220px;white-space:normal" class="xs">${hold}${v.etf && STRATEGIES[r.key].kind !== 'etf' ? ' + MSCI World ETF' : ''}</td></tr>`;
      });
      out.querySelector('#simyt').innerHTML = String(html`<div class="table-wrap"><table><thead><tr><th class="sticky">Jahr</th><th class="n">Eingezahlt</th><th class="n">Wert Jahresende</th><th class="n">Steuer</th><th class="n">Orders</th><th class="n">Konto</th><th>Bestand am Jahresende</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="xs muted">Steuer = im Folgejahr gezahlte Abgeltungsteuer auf die Gewinne dieses Jahres. Letzte Zeile: Wert am letzten Kurstag.</p>`);
    };
    const drawMonth = () => {
      const k = Number(out.querySelector('#simmonth').value);
      const list = monthList(data, k);
      const riskTxt = (x) => (!x.checked ? 'nicht geprüft' : x.risk ? `Risiko ${x.risk}` : 'Risiko –');
      out.querySelector('#simml').innerHTML = String(html`<div class="group">${list.map((x) => html`<div class="row"><div class="grow"><div class="title">${x.rank}. ${x.name}</div>
          <div class="sub" style="white-space:normal">${x.sector || ''}${x.checked ? html` · ${riskTxt(x)} · Outperformance ${x.opHigh === true ? 'hoch' : x.opHigh === false ? 'nicht hoch' : '–'}` : ''}</div></div>
        <div class="end">${x.cand ? html`<span class="badge b-buy">Kandidat</span>` : html`<span class="badge b-hold">kein Kandidat</span>`}${x.s2 ? html` <span class="badge b-cont">Stage 2 ✓</span>` : ''}</div></div>`)}</div>
        <p class="xs muted">Rangfolge nach Stage-1-Score am ${fmtDate(data.signal_dates[k])}, nur mit Kursen bis zu diesem Tag. <b>Kandidat</b> = erfüllt alle Stage-1-Regeln (Top-Liste). <b>Stage 2 ✓</b> = einer der Top-10-Kandidaten mit Risiko NORMAL <i>und</i> hoher Outperformance im Kursteil: stärker als der MSCI World über 3, 6 und 12 Monate, in mindestens 7 von 12 Monaten besser und risikobereinigt besser. Die anderen hatten ein höheres Risiko (ELEVATED, HIGH oder CRITICAL, zum Beispiel überhitzt, zu volatil oder Trend schwächer werdend) oder keine hohe Outperformance. Plätze nach den Top 10 werden für Stage 2 nicht geprüft. Gekauft wurde am ${fmtDate(data.points[k])}.</p>`);
    };
    const fillLogYears = () => {
      const r = res.find((x) => x.key === out.querySelector('#logstrat').value) || res[0];
      const ys = Object.keys(r.yearly).sort().reverse();
      out.querySelector('#logyear').innerHTML = ys.map((y) => `<option value="${y}">${y}</option>`).join('');
    };
    const drawLog = () => {
      const r = res.find((x) => x.key === out.querySelector('#logstrat').value) || res[0];
      const y = out.querySelector('#logyear').value;
      const ms = r.months.filter((m) => data.points[m.k].startsWith(y));
      const byK = new Map();
      for (const e of r.log) { if (!byK.has(e.k)) byK.set(e.k, []); byK.get(e.k).push(e); }
      const z = (x) => (Math.abs(x) < 0.005 ? 0 : x);
      const blocks = ms.map((m) => {
        const ev = byK.get(m.k) || [];
        const head = r.kind === 'etf'
          ? html`<b>${fmtDate(data.points[m.k])}</b>: Sparrate ${fmtEUR(m.budget, 2)} in den ETF.`
          : html`<b>${fmtDate(data.points[m.k])}</b>: Konto vorher ${fmtEUR(z(m.carried), 2)}${m.tax ? html`, Steuer −${fmtEUR(m.tax, 2)}` : ''}, Budget +${fmtEUR(m.budget, 2)}${m.proceeds ? html`, Verkaufserlöse +${fmtEUR(m.proceeds, 2)}` : ''} → angelegt ${fmtEUR(m.invest, 2)}${m.n ? html`, je Aktie ${fmtEUR(m.each, 2)} (${m.n} auf der Liste)` : html` (keine Aktie auf der Liste)`} → Konto danach ${fmtEUR(z(m.cashAfter), 2)}.`;
        const rows = ev.map((e) => {
          if (e.type === 'Halten') {
            return html`<div class="row"><div class="grow"><div class="title">Halten: ${e.name}</div><div class="sub" style="white-space:normal">${e.why}</div></div><div class="end"><span class="badge b-stop">wartet</span></div></div>`;
          }
          if (e.type === 'Steuer') {
            return html`<div class="row"><div class="grow"><div class="title">Steuer: ${e.name}</div><div class="sub" style="white-space:normal">${e.why}</div></div><div class="end"><b class="${e.amount ? 'neg' : ''}">${e.amount ? `−${fmtEUR(e.amount, 2)}` : '0 €'}</b></div></div>`;
          }
          const sell = e.type === 'Verkauf';
          return html`<div class="row"><div class="grow"><div class="title">${e.type}: ${e.name}</div>
            <div class="sub" style="white-space:normal">${fmtNum(e.shares, 3)} Stück × ${fmtNum(e.px, 2)} €${sell ? html` · gekauft ab ${fmtDate(data.points[e.firstK])} zu Ø ${fmtNum(e.buyPx, 2)} € · Gewinn <b class="${e.gain >= 0 ? 'pos' : 'neg'}">${fmtEUR(e.gain, 2)}</b>` : ''}</div>
            <div class="xs muted" style="white-space:normal">${e.why}</div></div>
            <div class="end"><b class="${sell ? 'pos' : ''}">${sell ? '+' : '−'}${fmtEUR(e.amount, 2)}</b></div></div>`;
        });
        return html`<div class="panel small" style="margin-bottom:8px"><p style="margin:0 0 6px">${head}</p>${rows.length ? html`<div class="group">${rows}</div>` : ''}</div>`;
      });
      const openRows = r.open.map((p) => html`<tr><td style="white-space:normal">${p.name}</td><td>${fmtDate(data.points[p.firstK])}</td><td class="n">${fmtEUR(p.basis, 0)}</td><td class="n">${fmtEUR(p.value, 0)}</td><td class="n ${p.value - p.basis >= 0 ? 'pos' : 'neg'}">${fmtEUR(p.value - p.basis, 0)}</td></tr>`);
      out.querySelector('#simlog').innerHTML = String(html`${blocks}
        ${r.kind !== 'etf' && y === String(new Date(data.points[r.kEnd]).getFullYear()) ? html`<h3>Bestand am ${fmtDate(data.points[r.kEnd])}</h3><div class="table-wrap"><table><thead><tr><th>Aktie</th><th>seit</th><th class="n">Einstand</th><th class="n">Wert</th><th class="n">Gewinn</th></tr></thead><tbody>${openRows}</tbody></table></div>
          <p class="xs muted">Konto ${fmtEUR(r.cash, 2)}${r.etfValue > 1 ? `, MSCI World ETF ${fmtEUR(r.etfValue, 0)} (Einstand ${fmtEUR(r.etfBasis, 0)})` : ''}.</p>` : ''}
        <p class="xs muted">Kurse in Euro (Schlusskurs am Ausführungstag). Betrag rechts = Kaufbetrag inklusive Gebühr und halbem Spread bzw. Verkaufserlös nach Gebühr und halbem Spread. Gewinn = Erlös minus Einstand (inklusive Kaufkosten). Steuern werden jeweils im ersten Monat des Folgejahres abgerechnet.</p>`);
    };
    out.querySelector('#simyear').onchange = drawYears;
    out.querySelector('#logstrat').onchange = () => { fillLogYears(); drawLog(); };
    out.querySelector('#logyear').onchange = drawLog;
    fillLogYears();
    drawLog();
    out.querySelector('#simmonth').onchange = drawMonth;
    drawYears();
    drawMonth();
  };

  const num = (v, d) => { const x = parseDec(String(v)); return Number.isFinite(x) && x >= 0 ? x : d; };
  el.querySelector('#simform').addEventListener('change', async (e) => {
    const t = e.target;
    if (!t.name) return;
    if (t.name === 'hold' || t.name === 'rest' || t.name === 'budgetMode') o[t.name] = t.value;
    else if (t.name === 'startYear') o.startYear = Number(t.value);
    else o[t.name] = num(t.value, DEFAULTS[t.name]);
    const maxFee = Math.max(0, o.budget * 0.1);
    for (const f of ['feeBuy', 'feeSell', 'feeEtf']) {
      if (o[f] > Math.min(maxFee, 50)) { o[f] = DEFAULTS[f]; const inp = el.querySelector(`[name=${f}]`); if (inp) inp.value = String(o[f]).replace('.', ','); toastFee(); }
    }
    for (const f of ['spread', 'spreadEtf']) if (o[f] > 5) { o[f] = DEFAULTS[f]; el.querySelector(`[name=${f}]`).value = String(o[f]).replace('.', ','); toastFee(); }
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

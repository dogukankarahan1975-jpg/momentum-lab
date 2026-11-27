// Simulator-Abschnitt im Backtest: Strategien wählen, Budget und Kosten einstellen, Vermögensverlauf nachvollziehen.
import { lineChart } from '../charts.js';
import { fmtDate, fmtEUR, fmtNum, fmtPct, parseDec } from '../fmt.js';
import { getHidden } from '../hidden.js';
import { FREQ_LABEL, BUDGET_LABEL, DEFAULTS, HOLD_LABEL, REST_LABEL, STRATEGIES, monthList, simulate, startIndex } from '../simulator.js';
import { getSetting, setSetting } from '../store.js';
import { html, note } from '../ui.js';

const COLORS = { world: 'var(--s1)', sp500: 'var(--s4)', s1top5: 'var(--s2)', s1top10: 'var(--s3)', s2top5: 'var(--s5)', s1min4: 'var(--ink-2)' };

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
  if (!['signal', '1', '1be', '3', '3be', '6', '12', '6be', '12be'].includes(String(o.hold))) o.hold = DEFAULTS.hold;
  o.biasCorr = o.biasCorr === true;
  if (!FREQ_LABEL[o.freq]) o.freq = 'monthly';
  if (!(Number.isInteger(o.endYear))) o.endYear = null;
  if (!(Number.isInteger(o.budgetMonths) && o.budgetMonths > 0)) o.budgetMonths = null;
  if (!(o.initial >= 0)) o.initial = 0;
  o.rest = 'top'; // feste Regel: Top 5/Top 10/Stage 2 Top 5 kaufen immer 5 bzw. 10 Aktien, unabhängig vom Momentum-Score
  o.strategies = [...new Set((o.strategies || []).map((x) => (x === 's2' ? 's2top5' : x)).filter((x) => STRATEGIES[x]))];
  if (saved && !saved.v6) { for (const x of ['s2top5', 's1min4']) if (!o.strategies.includes(x)) o.strategies.push(x); o.v6 = true; }
  if (!(o.minScore >= 0 && o.minScore <= 10)) o.minScore = 4;
  // Schutz gegen versehentlich hohe Gebühren (z. B. Sparrate ins Gebührenfeld getippt)
  for (const f of ['feeBuy', 'feeSell', 'feeEtf']) if (!(o[f] >= 0) || o[f] > Math.min(Math.max(0, Math.max(o.budget, (o.initial || 0) / 12) * 0.1), 50)) o[f] = DEFAULTS[f];
  for (const f of ['spread', 'spreadEtf']) if (!(o[f] >= 0) || o[f] > 5) o[f] = DEFAULTS[f];
  const firstYear = Number(data.signal_dates[0].slice(0, 4));
  const lastYear = Number(data.signal_dates[data.signal_dates.length - 1].slice(0, 4)) - 2;
  const dataLastYear = Number(data.points[data.points.length - 1].slice(0, 4));
  const benchStart = (k) => data.bench?.[k]?.start || null;

  const form = html`
    <div class="panel">
      <h3 style="margin-top:0">Was wird hier getestet?</h3>
      <ul class="small" style="padding-left:18px;margin:0">
        <li><b>Echte Kurse von damals</b> (Yahoo Finance, in Euro umgerechnet mit EZB-Kursen). Keine erfundenen Zahlen${data.demo ? html` – <b>außer jetzt: DEMO-Daten</b>` : ''}.</li>
        <li>Für <b>jeden Monat seit ${fmtDate(data.signal_dates[0])}</b> wird das Screening mit den Daten von damals nachgestellt. Es entsteht genau die Liste, die die App am jeweiligen Monatsende gezeigt hätte. Ganz unten kannst du jede Monatsliste ansehen.</li>
        <li>Gekauft wird am nächsten Handelstag zum Schlusskurs. Das Monatsbudget wird <b>zu gleichen Teilen</b> auf die Aktien der aktuellen Liste verteilt, Verkaufserlöse kommen dazu.</li>
        <li><b>Stage 2</b> ist nur mit seinem Kursteil testbar. ${data.notes?.stage2 || ''}</li>
        <li><b>Welche Aktien:</b> ${data.notes?.survivorship || ''}${data.pit?.active ? ` Zeitraum ${data.pit.coverage_from.slice(5)}/${data.pit.coverage_from.slice(0, 4)} bis ${data.pit.coverage_to.slice(5)}/${data.pit.coverage_to.slice(0, 4)}; ${data.pit.former_members_used} ehemalige Mitglieder mit Kursen einbezogen, ${data.pit.members_without_prices} ehemalige ohne passende Kurse (fehlen).` : data.pit && !data.pit.active ? ` Die historische Zusammensetzung wird gerade aufgebaut (${data.pit.months || 0} Monate).` : ''}</li>
      </ul>
    </div>
    <h3>Einstellungen</h3>
    <div class="panel" id="simform">
      ${data.bias?.pa > 0 ? html`<label class="check" style="display:flex;gap:10px;align-items:flex-start;margin-bottom:12px"><input type="checkbox" name="biasCorr" ${o.biasCorr ? 'checked' : ''} style="width:22px;height:22px;flex:none;margin-top:2px">
        <span class="small"><b>Überlebenden-Effekt herausrechnen (−${fmtNum(data.bias.pa * 100, 1)} % p. a. je Aktie)</b><br><span class="muted">Gemessen aus deinen Daten: Alle Aktien der Backtest-Liste gleich gewichtet, ganz ohne Momentum, erzielten ${fmtNum(data.bias.ew_cagr * 100, 1)} % p. a., der echte ${data.bias.ref_name} ${fmtNum(data.bias.ref_cagr * 100, 1)} % p. a. (${fmtDate(data.bias.from)} bis ${fmtDate(data.bias.to)}). Diesen Vorsprung zieht die Korrektur von jeder Aktie ab. ETF-Sparpläne bleiben unverändert.</span></span></label>` : ''}
      <div class="small" style="margin-bottom:6px">Strategien vergleichen</div>
      <div class="legend" id="simstrat">${Object.entries(STRATEGIES).map(([k, s]) => html`<button data-k="${k}" aria-pressed="${o.strategies.includes(k)}"><span class="swatch" style="background:${COLORS[k]}"></span>${s.short}</button>`)}</div>
      <div class="grid2" style="margin-top:10px">
        <label class="field"><span>Start</span><select name="startYear">${Array.from({ length: lastYear - firstYear + 1 }, (_, i) => firstYear + i).map((y) => html`<option value="${y}" ${y === o.startYear ? 'selected' : ''}>${y}</option>`)}</select></label>
        <label class="field"><span>Ende</span><select name="endYear"><option value="" ${!o.endYear ? 'selected' : ''}>bis heute</option>${Array.from({ length: dataLastYear - firstYear }, (_, i) => firstYear + i).map((y) => html`<option value="${y}" ${y === o.endYear ? 'selected' : ''}>Ende ${y}</option>`)}</select></label>
        <label class="field"><span>Monatsbudget (€)</span><input name="budget" inputmode="decimal" value="${o.budget}"></label>
        <label class="field"><span>Dynamik pro Jahr (%)</span><input name="dyn" inputmode="decimal" value="${String(o.dyn).replace('.', ',')}"></label>
        <label class="field"><span>Startkapital (€, einmalig)</span><input name="initial" inputmode="decimal" value="${o.initial || 0}"></label>
        <label class="field"><span>Monatsbudget einzahlen</span><select name="budgetMonths">
          ${[null, 6, 12, 24, 36, 48, 60, 120].map((n) => html`<option value="${n ?? ''}" ${o.budgetMonths === n ? 'selected' : ''}>${n ? `nur die ersten ${n} Monate (Starthilfe)` : 'immer (jeden Monat)'}</option>`)}</select></label>
        <label class="field"><span>Gebühr je Kauf (€)</span><input name="feeBuy" inputmode="decimal" value="${String(o.feeBuy).replace('.', ',')}"></label>
        <label class="field"><span>Gebühr je Verkauf (€)</span><input name="feeSell" inputmode="decimal" value="${String(o.feeSell).replace('.', ',')}"></label>
        <label class="field"><span>Gebühr je ETF-Sparrate (€)</span><input name="feeEtf" inputmode="decimal" value="${String(o.feeEtf).replace('.', ',')}"></label>
        <label class="field"><span>Spread Aktien (%)</span><input name="spread" inputmode="decimal" value="${String(o.spread).replace('.', ',')}"></label>
        <label class="field"><span>Spread ETF (%)</span><input name="spreadEtf" inputmode="decimal" value="${String(o.spreadEtf).replace('.', ',')}"></label>
      </div>
      <label class="field"><span>Budget der Aktien-Strategien</span><select name="budgetMode">
        ${['reinvest', 'fixed'].map((m) => html`<option value="${m}" ${o.budgetMode === m ? 'selected' : ''}>${m === 'reinvest' ? 'Budget + Verkaufserlöse anlegen' : 'Nur festes Monatsbudget anlegen'}</option>`)}</select></label>
      <label class="field"><span>Wie oft wird gescreent und gekauft?</span><select name="freq">${Object.entries(FREQ_LABEL).map(([k, v]) => html`<option value="${k}" ${o.freq === k ? 'selected' : ''}>${v[0].toUpperCase() + v.slice(1)}</option>`)}</select></label>
      <label class="field"><span>Wie lange werden Aktien gehalten?</span><select name="hold">
        ${['signal', '1', '1be', '3', '3be', '6', '6be', '12', '12be'].map((h) => html`<option value="${h}" ${String(o.hold) === h ? 'selected' : ''}>${{ signal: 'Bis zum Verkaufssignal der App', 1: '1 Monat, dann verkaufen', '1be': '1 Monat, im Minus warten bis ±0', 3: '3 Monate, dann verkaufen', '3be': '3 Monate, im Minus warten bis ±0', 6: '6 Monate, dann verkaufen', '6be': '6 Monate, im Minus warten bis ±0', 12: '12 Monate, dann verkaufen', '12be': '12 Monate, im Minus warten bis ±0' }[h]}</option>`)}</select></label>
      <label class="field"><span>Mindest-Score für „Minimum Score“ (Stage 1)</span><input name="minScore" inputmode="decimal" value="${String(o.minScore).replace('.', ',')}">
        <div class="hint">Strategie „Minimum Score“: Gekauft werden nur Stage-1-Kandidaten mit mindestens diesem Momentum-Score (wie in der Top-10-Liste, z. B. 4,52), zu gleichen Teilen. Gibt es keinen, wird nicht gehandelt und das Budget bleibt auf dem Konto.${data.cand_z ? '' : ' Diese Daten entstehen beim nächsten Datenlauf.'}</div></label>
      <p class="xs muted" style="margin:-4px 0 8px">Verkaufssignal = Aktie an zwei Monatsenden hintereinander nicht mehr im besten Fünftel (sofort bei schwerer Verschlechterung). Screening seltener als monatlich: gekauft wird nur am ersten Handelstag von Januar (jährlich), Januar und Juli (halbjährlich) bzw. Januar, April, Juli und Oktober (vierteljährlich); dazwischen sammeln sich Monatsbudget und Verkaufserlöse auf dem Konto und werden beim nächsten Screening auf die Liste verteilt. Verkaufssignale der App werden nur an diesen Terminen gelesen, feste Haltedauern dagegen pünktlich verkauft. Bei 1, 3, 6 oder 12 Monaten wird am ersten Monatsende nach Ablauf verkauft, im Plus wie im Minus; mit „warten bis ±0“ wird eine Aktie im Minus weiter gehalten und erst verkauft, wenn der Erlös nach Kosten wieder den Einstand deckt. Steht die Aktie dann noch auf der Liste, wird sie mit dem neuen Geld wieder gekauft. Top 5, Top 10 und Stage 2 Top 5 kaufen jeden Monat immer 5 bzw. 10 Aktien zu gleichen Teilen, unabhängig vom Momentum-Score: Gibt es weniger Kandidaten, wird mit den nächsten der Momentum-Rangliste aufgefüllt. Nur „Minimum Score“ kauft ausschließlich Kandidaten ab dem Mindest-Score. Stage 2 Top 5: die 5 besten der Top-10-Kandidaten nach der Fortsetzungs-Rangfolge (gleichmäßiger Anstieg, Nähe zum 52-Wochen-Hoch, Stärke gegenüber dem Markt). ETF-Sparpläne: jeden Monat wird das Monatsbudget (mit Dynamik) in den ETF gesteckt, nie verkauft; „Gebühr je ETF-Sparrate“ ist nur die Ausführungsgebühr (Trade Republic: 0 €). Bei „Nur festes Monatsbudget“ bleiben Verkaufserlöse auf dem Konto (0 % Zins) und zählen zum Vermögen.</p>
      <p class="xs muted" style="margin:0">Voreinstellung Trade Republic: 1 € je Order, ETF-Sparplan kostenlos. Der Spread ist eine Annahme: Er wird je zur Hälfte beim Kauf und beim Verkauf berechnet. Steuer: 26,375 % (Abgeltungsteuer + Soli, ohne Kirchensteuer). Aktien: Verluste nur mit Aktiengewinnen verrechnet und vorgetragen. ETF: 30 % Teilfreistellung, Vorabpauschale ab 2018 mit dem Basiszins des BMF, wird beim Verkauf angerechnet. Sparer-Pauschbetrag pro Jahr (801 € bis 2022, 1.000 € ab 2023), gemeinsam für Aktiengewinne und Vorabpauschale; ETF-Verluste dürfen mit Aktiengewinnen verrechnet werden, Aktienverluste nicht mit ETF-Gewinnen, je Strategie eigenständig gerechnet. Steuer wird wie beim Broker sofort bei jedem Verkauf einbehalten (Verluste im selben Jahr führen zu Erstattung), die Vorabpauschale Anfang Januar.</p>
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
    const ext = data.bench?.msci_world?.extended;
    if (ext && opts.strategies.includes('world') && startIndex(data, opts.startYear) < data.points.findIndex((d) => d >= ext.to)) {
      notes.push(`MSCI World vor ${fmtDate(ext.to)}: Kurse des älteren ${ext.name} (seit ${fmtDate(ext.from)}), mit Ausschüttungen wieder angelegt. Geprüft über ${ext.months_checked} gemeinsame Monate: Korrelation ${fmtNum(ext.corr, 3)}, Abweichung ${fmtNum(ext.diff_pa * 100, 2)} % p. a.`);
    }
    const keys = opts.strategies.filter((k) => STRATEGIES[k].kind !== 'etf' || benchStart(STRATEGIES[k].bench));
    if (!keys.length) { out.innerHTML = String(note('info', 'Wähle oben mindestens eine Strategie.')); return; }
    if (opts.biasCorr && data.bias?.pa > 0) notes.push(`Mit Korrektur: Alle Aktienkurse wurden um ${fmtNum(data.bias.pa * 100, 1)} % p. a. gemindert (gemessener Überlebenden-Effekt).`);
    if (opts.endYear && opts.endYear < opts.startYear) { notes.push('Das Endjahr liegt vor dem Start – es wird bis heute gerechnet.'); opts.endYear = null; }
    const hidden = [...(await getHidden())];
    if (hidden.length) notes.push(`${hidden.length} von dir ausgeblendete Aktie(n) (gibt es bei Trade Republic nicht) werden auch rückwirkend nicht gekauft.`);
    const res = keys.map((k) => simulate(data, k, { ...opts, exclude: hidden }));
    const best = res.reduce((a, r) => (r.afterTax > (a?.afterTax ?? -Infinity) ? r : a), null);
    const k0 = startIndex(data, opts.startYear);
    const parts = [];
    for (const n of notes) parts.push(note('info', n));
    parts.push(html`<h3>Ergebnis${data.universe ? ` (${data.universe.label})` : ''}: ${opts.initial ? `${fmtEUR(opts.initial, 0)} Startkapital${opts.budget ? ' + ' : ''}` : ''}${opts.budget || !opts.initial ? `${fmtEUR(opts.budget, 0)} pro Monat${opts.budgetMonths ? ` (nur die ersten ${opts.budgetMonths} Monate)` : ''}` : ''} ab ${fmtDate(data.points[k0])}${opts.endYear ? ` bis ${fmtDate(res[0]?.end || data.points[data.points.length - 1])}` : ''}${opts.dyn ? `, +${fmtNum(opts.dyn, 1)} % pro Jahr` : ''}</h3>
      <p class="xs muted">Screening: ${FREQ_LABEL[opts.freq] || 'monatlich'}. Haltedauer: ${HOLD_LABEL[opts.hold]}. ${REST_LABEL.top}. Minimum Score: ab ${fmtNum(opts.minScore, 1)}. ${BUDGET_LABEL[opts.budgetMode]}.</p>
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
          ? html`Jeden Monat gekauft, nie etwas verkauft. Laufend gezahlt nur die Steuer auf die Vorabpauschale: ${fmtEUR(r.taxesPaid, 0)}. Nur falls du heute alles verkaufen würdest: ${fmtEUR(r.afterTax, 0)} nach Steuern, Gebühren und Spread (Gewinn ${fmtEUR(gainAfter, 0)}, ${fmtPct(r.irrAfter)} p. a.).`
          : html`Darin ${fmtEUR(r.cash, 0)} auf dem Konto${r.etfValue > 1 ? html` und ${fmtEUR(r.etfValue, 0)} im MSCI World ETF` : ''}. Bereits gezahlte Steuern ${fmtEUR(r.taxesPaid, 0)}. Falls du heute alles verkaufst: ${fmtEUR(r.afterTax, 0)} nach Steuern, Gebühren und Spread (Gewinn ${fmtEUR(gainAfter, 0)}, ${fmtPct(r.irrAfter)} p. a.).`}
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
        <p class="xs muted">Steuer = in diesem Jahr einbehaltene Abgeltungsteuer inkl. Soli (bei jedem Verkauf sofort abgezogen, Erstattungen bei Verlusten im selben Jahr verrechnet; beim ETF die Vorabpauschale). Letzte Zeile: Wert am letzten Kurstag.</p>`);
    };
    const drawMonth = () => {
      const k = Number(out.querySelector('#simmonth').value);
      const list = monthList(data, k);
      out.querySelector('#simml').innerHTML = String(html`<div class="group">${list.map((x) => html`<div class="row"><div class="grow"><div class="title">${x.rank}. ${x.name}</div>
          <div class="sub" style="white-space:normal">${x.sector || ''}${x.score != null ? html` · Momentum-Score ${fmtNum(x.score, 2)}` : ''}${x.s2rank ? html` · Stage 2: Platz ${x.s2rank}${x.s2score != null ? `, Score ${fmtNum(x.s2score, 1)}` : ''}` : ''}</div></div>
        <div class="end">${x.cand ? html`<span class="badge b-buy">Kandidat</span>` : html`<span class="badge b-hold">kein Kandidat</span>`}${x.s2top ? html` <span class="badge b-cont">S2 Top 5</span>` : ''}</div></div>`)}</div>
        <p class="xs muted">Rangfolge nach Stage-1-Momentum-Score am ${fmtDate(data.signal_dates[k])}, nur mit Kursen bis zu diesem Tag. <b>Kandidat</b> = erfüllt alle Stage-1-Regeln. <b>S2 Top 5</b> = unter den Top-10-Kandidaten die 5 mit dem höchsten Stage-2-Score (Kursteil: gleichmäßiger Anstieg, Nähe zum 52-Wochen-Hoch, Stärke gegenüber dem Markt; jeweils im Vergleich zu allen Momentum-Aktien). Gekauft wurde am ${fmtDate(data.points[k])}.</p>`);
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
          : html`<b>${fmtDate(data.points[m.k])}</b>: Konto vorher ${fmtEUR(z(m.carried), 2)}${Math.abs(m.tax) > 0.005 ? html`, Steuer ${m.tax > 0 ? '−' : '+'}${fmtEUR(Math.abs(m.tax), 2)}` : ''}, Budget +${fmtEUR(m.budget, 2)}${m.proceeds ? html`, Verkaufserlöse +${fmtEUR(m.proceeds, 2)}` : ''} → angelegt ${fmtEUR(m.invest, 2)}${m.n ? html`, je Aktie ${fmtEUR(m.each, 2)} (${m.n} auf der Liste)` : html` (keine Aktie auf der Liste)`} → Konto danach ${fmtEUR(z(m.cashAfter), 2)}.`;
        const rows = ev.map((e) => {
          if (e.type === 'Halten') {
            return html`<div class="row"><div class="grow"><div class="title">Halten: ${e.name}</div><div class="sub" style="white-space:normal">${e.why}</div></div><div class="end"><span class="badge b-stop">wartet</span></div></div>`;
          }
          if (e.type === 'Steuer') {
            return html`<div class="row"><div class="grow"><div class="title">Steuer ${e.name}</div><div class="sub" style="white-space:normal">${e.why}</div></div><div class="end"><b class="${e.amount > 0 ? 'neg' : 'pos'}">${e.amount > 0 ? `−${fmtEUR(e.amount, 2)}` : `+${fmtEUR(-e.amount, 2)}`}</b></div></div>`;
          }
          if (e.type === 'Info') {
            return html`<div class="row"><div class="grow"><div class="title">${e.name}</div><div class="sub" style="white-space:normal">${e.why}</div></div></div>`;
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
    if (t.name === 'biasCorr') o.biasCorr = !!t.checked;
    else if (t.name === 'freq') o.freq = t.value;
    else if (t.name === 'hold' || t.name === 'budgetMode') o[t.name] = t.value;
    else if (t.name === 'startYear') o.startYear = Number(t.value);
    else if (t.name === 'endYear') o.endYear = t.value ? Number(t.value) : null;
    else if (t.name === 'budgetMonths') o.budgetMonths = t.value ? Number(t.value) : null;
    else o[t.name] = num(t.value, DEFAULTS[t.name]);
    const maxFee = Math.max(0, Math.max(o.budget, (o.initial || 0) / 12) * 0.1);
    for (const f of ['feeBuy', 'feeSell', 'feeEtf']) {
      if (o[f] > Math.min(maxFee, 50)) { o[f] = DEFAULTS[f]; const inp = el.querySelector(`[name=${f}]`); if (inp) inp.value = String(o[f]).replace('.', ','); toastFee(); }
    }
    if (t.name === 'minScore' && !(o.minScore >= 0 && o.minScore <= 10)) { o.minScore = 4; t.value = '4'; }
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

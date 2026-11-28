// Simulator-Abschnitt im Backtest: Strategien wählen, Budget und Kosten einstellen, Vermögensverlauf nachvollziehen.
import { lineChart } from '../charts.js';
import { fmtDate, fmtEUR, fmtNum, fmtPct, parseDec } from '../fmt.js';
import { getHidden } from '../hidden.js';
import { FREQ_LABEL, FREQ_NAME, FREQ_STEP, freqText, monthsText, BUDGET_LABEL, DEFAULTS, HOLD_LABEL, REST_LABEL, STRATEGIES, monthList, simulate, startIndex } from '../simulator.js';
import { getSetting, setSetting } from '../store.js';
import { esc, html, note, openSheet } from '../ui.js';

const shiftOpts = (freq, shift) => html`${Array.from({ length: FREQ_STEP[freq] || 1 }, (_, i) => html`<option value="${i}" ${shift === i ? 'selected' : ''}>${monthsText(freq, i)}${i === 0 ? ' (wie bisher)' : ''}</option>`)}`;

const COLORS = { world: 'var(--s1)', sp500: 'var(--s4)', s1top5: 'var(--s2)', s1top10: 'var(--s3)', s2top5: 'var(--s5)', s1min4: 'var(--ink-2)', hold1: 'var(--teal)' };

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
  if (!(Number.isInteger(o.shift) && o.shift >= 0 && o.shift < (FREQ_STEP[o.freq] || 1))) o.shift = 0;
  if (!(Number.isInteger(o.endYear))) o.endYear = null;
  if (!(Number.isInteger(o.budgetMonths) && o.budgetMonths > 0)) o.budgetMonths = null;
  if (!(o.initial >= 0)) o.initial = 0;
  o.rest = 'top'; // feste Regel: Top 5/Top 10/Stage 2 Top 5 kaufen immer 5 bzw. 10 Aktien, unabhängig vom Momentum-Score
  o.strategies = [...new Set((o.strategies || []).map((x) => (x === 's2' ? 's2top5' : x)).filter((x) => STRATEGIES[x]))];
  if (saved && !saved.v6) { for (const x of ['s2top5', 's1min4']) if (!o.strategies.includes(x)) o.strategies.push(x); o.v6 = true; }
  if (saved && !saved.v7) { if (!o.strategies.includes('hold1')) o.strategies.push('hold1'); o.v7 = true; }
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
      <label class="field"><span>Wie oft wird gescreent und gekauft?</span><select name="freq">${Object.entries(FREQ_NAME).map(([k, v]) => html`<option value="${k}" ${o.freq === k ? 'selected' : ''}>${v[0].toUpperCase() + v.slice(1)}</option>`)}</select></label>
      <label class="field" id="shiftf" ${o.freq === 'monthly' ? 'hidden' : ''}><span>In welchen Monaten? (testet Timing-Glück)</span><select name="shift">${shiftOpts(o.freq, o.shift)}</select></label>
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
    const ext5 = data.bench?.sp500?.extended;
    if (ext5 && opts.strategies.includes('sp500') && startIndex(data, opts.startYear) < data.points.findIndex((d) => d >= ext5.to)) {
      notes.push(`S&P 500 vor ${fmtDate(ext5.to)} (Start des ETF): ${ext5.name}. Geprüft über ${ext5.months_checked} gemeinsame Monate mit dem echten ETF: Korrelation ${fmtNum(ext5.corr, 3)}, Abweichung ${fmtNum(ext5.diff_pa * 100, 2)} % p. a.`);
    }
    const keys = opts.strategies.filter((k) => STRATEGIES[k].kind !== 'etf' || benchStart(STRATEGIES[k].bench));
    if (!keys.length) { out.innerHTML = String(note('info', 'Wähle oben mindestens eine Strategie.')); return; }
    if (opts.biasCorr && data.bias?.pa > 0) notes.push(`Mit Korrektur: Alle Aktienkurse wurden um ${fmtNum(data.bias.pa * 100, 1)} % p. a. gemindert (gemessener Überlebenden-Effekt).`);
    if (opts.endYear && opts.endYear < opts.startYear) { notes.push('Das Endjahr liegt vor dem Start – es wird bis heute gerechnet.'); opts.endYear = null; }
    if (opts.strategies.includes('hold1')) {
      notes.push(`Gewinner halten: An jedem Screening-Termin (${freqText(opts.freq, opts.shift)}) fließt das ganze Geld auf dem Konto – also alle Monatsbudgets seit dem letzten Termin plus Dividenden – in die Nr. 1 der Stage-1-Liste. Verkauft wird nie (Haltedauer und Verkaufssignal gelten hier nicht), nur wenn die Kursdaten einer Aktie enden (Übernahme/Delisting).${opts.initial ? ` Startkapital wird bei dieser Strategie nicht eingesetzt, „Eingezahlt“ ist deshalb ${fmtEUR(opts.initial, 0)} kleiner.` : ''}`);
    }
    const hidden = [...(await getHidden())];
    if (hidden.length) notes.push(`${hidden.length} von dir ausgeblendete Aktie(n) (gibt es bei Trade Republic nicht) werden auch rückwirkend nicht gekauft.`);
    const res = keys.map((k) => simulate(data, k, { ...opts, exclude: hidden }));
    // „Am meisten nach Steuern“: Gewinn nach Steuern (fair, auch wenn eine Strategie ohne Startkapital rechnet)
    const best = res.reduce((a, r) => (r.afterTax - r.contrib > (a ? a.afterTax - a.contrib : -Infinity) ? r : a), null);
    const k0 = startIndex(data, opts.startYear);
    const parts = [];
    for (const n of notes) parts.push(note('info', n));
    parts.push(html`<h3>Ergebnis${data.universe ? ` (${data.universe.label})` : ''}: ${opts.initial ? `${fmtEUR(opts.initial, 0)} Startkapital${opts.budget ? ' + ' : ''}` : ''}${opts.budget || !opts.initial ? `${fmtEUR(opts.budget, 0)} pro Monat${opts.budgetMonths ? ` (nur die ersten ${opts.budgetMonths} Monate)` : ''}` : ''} ab ${fmtDate(data.points[k0])}${opts.endYear ? ` bis ${fmtDate(res[0]?.end || data.points[data.points.length - 1])}` : ''}${opts.dyn ? `, +${fmtNum(opts.dyn, 1)} % pro Jahr` : ''}</h3>
      <p class="xs muted">Screening: ${freqText(opts.freq, opts.shift)}. Haltedauer: ${HOLD_LABEL[opts.hold]}. ${REST_LABEL.top}. Minimum Score: ab ${fmtNum(opts.minScore, 1)}. ${BUDGET_LABEL[opts.budgetMode]}.</p>
      <div class="panel"><div id="simchart"></div><p class="xs muted" style="margin:6px 0 0">Depotwert in Euro vor Steuern. Graue Linie = eingezahltes Geld.</p></div>`);
    for (const r of res) {
      const isEtf = r.kind === 'etf';
      const gainNow = r.final - r.contrib;
      const gainAfter = r.afterTax - r.contrib;
      const yrs = Object.entries(r.yearly).filter(([, v]) => v.ret != null);
      parts.push(html`<div class="panel simcard" data-calc="${r.key}" role="button" tabindex="0" style="border-left:4px solid ${COLORS[r.key]};cursor:pointer">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline"><h3 style="margin:0">${r.label}</h3>${r === best && res.length > 1 ? html`<span class="badge b-buy">Am meisten nach Steuern</span>` : ''}</div>
        <div class="grid2" style="margin-top:8px">
          <div class="stat"><div class="l">Auszahlung, wenn du heute alles verkaufst</div><div class="v">${fmtEUR(r.afterTax, 0)}</div></div>
          <div class="stat"><div class="l">Selbst eingezahlt</div><div class="v">${fmtEUR(r.contrib, 0)}</div></div>
          <div class="stat"><div class="l">Gewinn nach Kosten und Steuern</div><div class="v ${gainAfter >= 0 ? 'pos' : 'neg'}">${fmtEUR(gainAfter, 0)}</div></div>
          <div class="stat"><div class="l">Deine Rendite pro Jahr, nach allem</div><div class="v">${fmtPct(r.irrAfter)}</div></div>
        </div>
        <p class="xs muted" style="margin:8px 0 0">Gewinn = Auszahlung − eingezahlt. Darin steckt alles: Kursgewinne, Dividenden und die Gewinne aus Verkäufen, die danach weiter angelegt wurden. Rendite pro Jahr = Zinssatz auf dein Geld, mit dem Zeitpunkt jeder Einzahlung (Sparkonto-Vergleich). ${isEtf
          ? html`Ohne Verkauf (nie verkauft): Depotwert ${fmtEUR(r.final, 0)}, Buchgewinn ${fmtEUR(gainNow, 0)}, ${fmtPct(r.irr)} p. a. – darin ist die Steuer auf die Vorabpauschale (${fmtEUR(r.taxesPaid, 0)}) schon bezahlt, die Steuer auf den Kursgewinn noch nicht.`
          : html`Ohne Verkauf: Depotwert ${fmtEUR(r.final, 0)} (darin ${fmtEUR(r.cash, 0)} auf dem Konto${r.etfValue > 1 ? html` und ${fmtEUR(r.etfValue, 0)} im MSCI World ETF` : ''}), Buchgewinn ${fmtEUR(gainNow, 0)}, ${fmtPct(r.irr)} p. a. Unterwegs schon gezahlte Steuern ${fmtEUR(r.taxesPaid, 0)}${r.divTotal > 1 ? ` (inkl. Steuer auf ${fmtEUR(r.divTotal, 0)} Dividenden)` : ''}.`}
          Größter Rückgang ${fmtPct(r.maxDD, 0)}. ${fmtNum(r.trades, 0)} Orders, Gebühren ${fmtEUR(r.fees, 0)}, Spread ${fmtEUR(r.spreadCost, 0)}.</p>
        ${isEtf && r.fundPa != null ? html`<p class="xs muted" style="margin:8px 0 0">Zum Vergleich: Der ETF-Kurs selbst stieg ${fmtPct(r.fundPa)} pro Jahr (${fmtDate(r.start)} bis ${fmtDate(r.end)}, vor Steuern und Kosten). Das zeigen Online-Rechner – es ist die Leistung des Fonds, nicht deine Rendite auf die Raten.</p>` : ''}
        ${yrs.length ? html`<p class="small" style="margin:8px 0 0">Wie gut lief die Strategie je Kalenderjahr (zeitgewichtet, unabhängig von deinen Einzahlungen): ${yrs.map(([y, v], j) => html`<span style="white-space:nowrap"><b class="${v.ret >= 0 ? 'pos' : 'neg'}">${y}${partYear(r, y, j, yrs.length) ? '*' : ''} ${fmtPct(v.ret)}</b></span>`).reduce((a, x, j) => (j ? html`${a}, ${x}` : x), '')}${yrs.some(([y], j) => partYear(r, y, j, yrs.length)) ? html`<span class="xs muted"> (* Teiljahr)</span>` : ''}</p>` : ''}
        <p class="small" style="margin:8px 0 0;color:var(--ice)">Antippen für die komplette Rechnung ›</p>
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
        return html`<tr><td class="sticky">${y}</td><td class="n ${v.ret == null ? '' : v.ret >= 0 ? 'pos' : 'neg'}">${v.ret == null ? '–' : fmtPct(v.ret)}</td><td class="n">${fmtEUR(cum, 0)}</td><td class="n">${fmtEUR(v.valueEnd ?? v.value, 0)}</td><td class="n">${fmtEUR(v.tax, 0)}</td><td class="n">${v.trades}</td><td class="n">${fmtEUR(v.cash, 0)}</td><td style="min-width:220px;white-space:normal" class="xs">${hold}${v.etf && STRATEGIES[r.key].kind !== 'etf' ? ' + MSCI World ETF' : ''}</td></tr>`;
      });
      out.querySelector('#simyt').innerHTML = String(html`<div class="table-wrap"><table><thead><tr><th class="sticky">Jahr</th><th class="n">Rendite im Jahr</th><th class="n">Eingezahlt</th><th class="n">Wert Jahresende</th><th class="n">Steuer</th><th class="n">Orders</th><th class="n">Konto</th><th>Bestand am Jahresende</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="xs muted">Steuer = in diesem Jahr einbehaltene Abgeltungsteuer inkl. Soli (bei jedem Verkauf sofort abgezogen, Erstattungen bei Verlusten im selben Jahr verrechnet; Dividenden im Jahr der Zahlung; beim ETF die Vorabpauschale). Letzte Zeile: Wert am letzten Kurstag. Rendite im Jahr = zeitgewichtet (wie bei Fonds üblich): nur die Wertentwicklung, Einzahlungen zählen nicht als Gewinn. Erstes und letztes Jahr sind oft Teiljahre.</p>`);
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
          : html`<b>${fmtDate(data.points[m.k])}</b>: Konto vorher ${fmtEUR(z(m.carried), 2)}${Math.abs(m.tax) > 0.005 ? html`, Steuer ${m.tax > 0 ? '−' : '+'}${fmtEUR(Math.abs(m.tax), 2)}` : ''}, Budget +${fmtEUR(m.budget, 2)}${m.proceeds ? html`, Verkaufserlöse +${fmtEUR(m.proceeds, 2)}` : ''} → ${!m.screen ? html`kein Screening-Termin (${freqText(opts.freq, opts.shift)}), Geld bleibt bis zum nächsten Termin auf dem Konto` : html`angelegt ${fmtEUR(m.invest, 2)}${!m.n ? html` (keine Aktie auf der Liste)` : m.invest > 0 ? html`, je Aktie ${fmtEUR(m.each, 2)} (${m.n} auf der Liste)` : html` (kein Geld zum Anlegen)`}`} → Konto danach ${fmtEUR(z(m.cashAfter), 2)}.`;
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
    out.querySelectorAll('[data-calc]').forEach((el) => {
      const open = () => { const r = res.find((x) => x.key === el.dataset.calc); if (r) showCalc(r, data); };
      el.onclick = open;
      el.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } };
    });
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
    else if (t.name === 'freq') {
      o.freq = t.value;
      if (o.shift >= (FREQ_STEP[o.freq] || 1)) o.shift = 0;
      const f = el.querySelector('#shiftf');
      f.hidden = o.freq === 'monthly';
      f.querySelector('select').innerHTML = String(shiftOpts(o.freq, o.shift));
    } else if (t.name === 'shift') o.shift = Number(t.value) || 0;
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


/** Erstes/letztes Jahr nur teilweise im Zeitraum? */
function partYear(r, y, j, n) {
  if (j === 0 && r.start.slice(5, 7) > '01') return true;
  if (j === n - 1 && !(r.end.slice(0, 4) > y)) return r.end.slice(5, 10) < '12-20';
  return false;
}

/** Komplette Rechnung einer Kachel: vom Depotwert über Verkaufskosten und Steuer bis zum Gewinn nach allem. */
function showCalc(r, data) {
  const c = r.endCalc;
  const e = (v) => fmtEUR(v, 2);
  const row = (l, v, cls = '', sub = '') => `<tr class="${cls}"><td style="white-space:normal">${l}${sub ? `<div class="xs muted">${sub}</div>` : ''}</td><td class="n" style="white-space:nowrap">${v}</td></tr>`;
  const tbl = (rows) => `<div class="table-wrap"><table class="calc">${rows.join('')}</table></div>`;
  const isEtf = r.kind === 'etf';
  const pct = (x) => `${fmtNum(x * 100, x * 100 % 1 ? 3 : 0)} %`;
  const parts = [];
  parts.push(`<p class="small muted">${esc(r.label)}. Zeitraum ${fmtDate(r.start)} bis ${fmtDate(r.end)} (Kurs vom ${fmtDate(r.end)}${c.year < Number(r.end.slice(0, 4)) ? ` = Stand 31.12.${c.year}` : ''}). Steuerjahr des Verkaufs: ${c.year}. Steuersatz 25 % Abgeltungsteuer + 5,5 % Soli = 26,375 %, ohne Kirchensteuer.</p>`);
  parts.push('<h3>1. Was im Depot liegt</h3>' + tbl([
    row('Konto (nicht angelegtes Geld)', e(c.cash)),
    ...(r.open.length ? [row(`Aktien (${r.open.length} Positionen)`, e(c.stockVal))] : []),
    ...(c.etfVal > 0 ? [row(isEtf ? 'ETF-Anteile' : 'MSCI World ETF', e(c.etfVal))] : []),
    row('<b>Vermögen</b> (Wert auf der Kachel)', `<b>${e(c.final)}</b>`, 'sum'),
  ]));
  parts.push('<h3>2. Kosten, wenn du alles verkaufst</h3>' + tbl([
    ...(r.open.length ? [row('Aktien: Ordergebühren + halber Spread', `− ${e(c.liqStock)}`, '', `${r.open.length} Verkäufe`)] : []),
    ...(c.etfVal > 0 ? [row('ETF: Ordergebühr + halber Spread', `− ${e(c.liqEtf)}`)] : []),
    row('<b>Verkaufserlös vor Steuer</b>', `<b>${e(c.final - c.liqStock - c.liqEtf)}</b>`, 'sum'),
  ]));
  const g = [];
  if (r.open.length || c.realizedYear || c.carry) {
    g.push(row('<b>Aktien-Topf</b> (Verluste nur mit Aktiengewinnen verrechenbar)', ''));
    if (r.open.length) {
      g.push(row('Verkaufserlös Aktien nach Kosten', e(c.stockVal - c.liqStock)));
      g.push(row('− Einstand (Kaufpreis inkl. Kaufkosten und wiederangelegter Dividenden)', `− ${e(c.stockBasis)}`));
      g.push(row('= Kursgewinn beim Schlussverkauf', e(c.stockGainNet)));
    }
    if (c.realizedYear) g.push(row(`+ in ${c.year} schon realisierte Aktiengewinne/-verluste`, e(c.realizedYear)));
    if (c.carry) g.push(row('+ Verlustvortrag aus früheren Jahren', e(c.carry)));
    g.push(row('= Aktien-Topf', e(c.potStock), 'sum', c.potStock < 0 ? 'Negativ: wird nicht mit anderen Erträgen verrechnet, sondern vorgetragen.' : ''));
  }
  if (c.etfVal > 0 || c.vpYear || c.divYear) {
    g.push(row('<b>Allgemeiner Topf</b>', ''));
    if (c.etfVal > 0) {
      g.push(row('ETF-Verkaufserlös nach Kosten', e(c.etfVal - c.liqEtf)));
      g.push(row('− Einstand ETF (alle Raten inkl. Kaufkosten)', `− ${e(c.etfBasis)}`));
      g.push(row('= Kursgewinn ETF', e(c.etfGainRaw)));
      if (c.vpTotal) g.push(row('− bereits versteuerte Vorabpauschalen', `− ${e(c.vpTotal)}`, '', 'wurden in den Vorjahren schon versteuert und mindern den Gewinn beim Verkauf'));
      g.push(row(`× ${pct(1 - c.etfExempt)} (30 % Teilfreistellung für Aktien-ETFs)`, e(c.etfGain), 'sum'));
    }
    if (c.divYear) g.push(row(`+ Dividenden ${c.year}`, e(c.divYear)));
    if (c.vpYear) g.push(row(`+ Vorabpauschale (Vorjahr, steuerpflichtig in ${c.year})`, e(c.vpYear)));
    g.push(row('= Allgemeiner Topf', e(c.general), 'sum'));
  }
  parts.push('<h3>3. Steuerpflichtiger Gewinn</h3>' + tbl(g));
  const base = Math.max(0, c.taxable - c.allowance);
  parts.push(`<h3>4. Steuer im Jahr ${c.year}</h3>` + tbl([
    row(`Steuerpflichtig gesamt${c.potStock < 0 ? ' (Aktienverlust zählt hier nicht)' : ''}`, e(c.taxable)),
    row(`− Sparer-Pauschbetrag ${c.year}`, `− ${e(Math.min(c.allowance, Math.max(0, c.taxable)))}`, '', `${fmtEUR(c.allowance, 0)} pro Jahr (ledig); hier gilt er für alles, was ${c.year} versteuert wird`),
    row('= Bemessungsgrundlage', e(base)),
    row('× 26,375 %', e(c.liabilityYear), 'sum', `= Steuer für das ganze Jahr ${c.year}`),
    ...(c.paidYear ? [row(`− in ${c.year} schon einbehalten`, `− ${e(c.paidYear)}`, '', 'bei früheren Verkäufen, Dividenden oder der Vorabpauschale in diesem Jahr')] : []),
    row(c.endTax >= 0 ? '<b>= Steuer beim Schlussverkauf</b>' : '<b>= Erstattung beim Schlussverkauf</b>', `<b>${e(Math.abs(c.endTax))}</b>`, 'sum'),
  ]));
  parts.push('<h3>5. Was am Ende bei dir ankommt</h3>' + tbl([
    row('Vermögen', e(c.final)),
    row('− Verkaufskosten', `− ${e(c.liqStock + c.liqEtf)}`),
    row(c.endTax >= 0 ? '− Steuer beim Schlussverkauf' : '+ Steuererstattung', `${c.endTax >= 0 ? '−' : '+'} ${e(Math.abs(c.endTax))}`),
    row('<b>= Auszahlung</b>', `<b>${e(c.afterTax)}</b>`, 'sum'),
    row('− selbst eingezahlt', `− ${e(c.contrib)}`),
    row('<b>= Gewinn nach allen Kosten und Steuern</b>', `<b class="${c.afterTax - c.contrib >= 0 ? 'pos' : 'neg'}">${e(c.afterTax - c.contrib)}</b>`, 'sum'),
    row('Deine Rendite pro Jahr, nach allem', fmtPct(r.irrAfter)),
  ]));
  const ys = Object.keys(r.yearly).sort();
  const paid = ys.filter((y) => Math.abs(r.yearly[y].tax) > 0.005);
  parts.push('<h3>6. Schon unterwegs gezahlte Steuern</h3>' + (paid.length
    ? tbl([...paid.map((y) => row(String(y), e(r.yearly[y].tax))), row('<b>Summe</b> (ist im Vermögen schon abgezogen)', `<b>${e(r.taxesPaid)}</b>`, 'sum')])
    : '<p class="small muted">Keine – bis zum Schlussverkauf wurde keine Steuer fällig.</p>')
    + `<p class="xs muted">${isEtf ? 'Beim ETF: Steuer auf die Vorabpauschale (Anfang des Folgejahres).' : 'Bei jedem Verkauf, auf Dividenden und auf die Vorabpauschale sofort einbehalten, Verluste im selben Jahr erstattet.'} Jede einzelne Buchung steht unten unter „Jede Order nachvollziehen“.</p>`);
  parts.push('<h3>7. Wertentwicklung je Jahr</h3>' + tbl([
    '<tr><th>Jahr</th><th class="n">Rendite</th><th class="n">Eingezahlt</th><th class="n">Wert 31.12.</th></tr>',
    ...ys.map((y) => { const v = r.yearly[y]; return `<tr><td>${y}</td><td class="n ${v.ret == null ? '' : v.ret >= 0 ? 'pos' : 'neg'}">${v.ret == null ? '–' : fmtPct(v.ret)}</td><td class="n">${fmtEUR(v.contrib, 0)}</td><td class="n">${fmtEUR(v.valueEnd ?? v.value, 0)}</td></tr>`; }),
  ]) + '<p class="xs muted">Rendite im Jahr = zeitgewichtet: nur Kursentwicklung (nach Steuern, Gebühren), Einzahlungen zählen nicht als Gewinn. So rechnen auch Fondsanbieter. „Deine Rendite pro Jahr, nach allem“ auf der Kachel ist dagegen der Zinssatz auf deine Einzahlungen über den ganzen Zeitraum, wenn du heute alles verkaufst.</p>');
  if (r.open.length) {
    parts.push('<h3>8. Offene Positionen beim Schlussverkauf</h3>' + tbl([
      '<tr><th>Aktie</th><th class="n">Einstand</th><th class="n">Wert</th><th class="n">Gewinn</th></tr>',
      ...r.open.slice().sort((a, b) => b.value - a.value).map((p) => `<tr><td style="white-space:normal">${esc(p.name)}<div class="xs muted">seit ${fmtDate(data.points[p.firstK])}</div></td><td class="n">${fmtEUR(p.basis, 0)}</td><td class="n">${fmtEUR(p.value, 0)}</td><td class="n ${p.value - p.basis >= 0 ? 'pos' : 'neg'}">${fmtEUR(p.value - p.basis, 0)}</td></tr>`),
    ]));
  }
  parts.push('<p class="xs muted">Rein rechnerisch, keine Steuerberatung. Annahmen: ledig, keine Kirchensteuer, kein anderer Kapitalertrag im selben Jahr, Pauschbetrag nicht anderweitig genutzt.</p>');
  openSheet({ title: 'So entsteht das Ergebnis', body: parts.join(''), wide: true });
}

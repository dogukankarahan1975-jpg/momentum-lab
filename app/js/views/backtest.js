import { barChart, lineChart, SERIES_COLORS } from '../charts.js';
import { loadBacktest, loadSimIndex, loadSimulatorFor } from '../data.js';
import { getSetting, setSetting } from '../store.js';
import { renderSimulator } from './simulator-view.js';
import { fmtDate, fmtEUR, fmtNum, fmtPct } from '../fmt.js';
import { html, note, raw } from '../ui.js';

const DEFAULT_SEL = ['ew_universe', 'msci_world_eur', 'app_top10', 'app_top1'];
const GROUPS = [
  ['Vergleichsmaßstäbe', (v) => v.group === 'benchmark'],
  ['Momentum-Signale (monatlich strikt umgeschichtet)', (v) => ['m12_top10', 'm612_top10', 'ra_top10'].includes(v.id)],
  ['Konzentration: 1, 5 oder 10 Aktien', (v) => ['ra_top1', 'ra_top5', 'ra_top10', 'ra_top10_score'].includes(v.id)],
  ['App-Regeln mit Puffer und Bestätigung', (v) => ['app_top10', 'app_top1'].includes(v.id)],
  ['Getestete Filter', (v) => ['app_top10_ma200', 'app_top10_regime', 'app_top10_volshock'].includes(v.id)],
  ['Sensitivität des Haltebands', (v) => ['app_top10_hold10', 'app_top10', 'app_top10_hold30'].includes(v.id)],
];

export async function render(root) {
  let bt;
  try { bt = await loadBacktest(); } catch (e) {
    root.innerHTML = String(html`<h1>Backtesting</h1>${note('info', `Noch kein Backtest verfügbar: ${e.message}`)}`);
    return;
  }
  if (!bt.available) {
    root.innerHTML = String(html`<h1>Backtesting</h1>${note('warn', `Backtest nicht verfügbar: ${bt.reason || 'unbekannt'}`)}`);
    return;
  }
  const V = new Map(bt.variants.map((v) => [v.id, v]));
  const sel = DEFAULT_SEL.filter((id) => V.has(id));
  const parts = [html`<h1>Backtesting</h1>
    <p class="lede">Was wäre aus deinem Geld geworden, wenn du die App schon früher genutzt hättest? Stell oben Budget und Regeln ein und vergleiche mit MSCI World und S&amp;P 500.</p>`];
  if (bt.demo) parts.push(html`<div class="demo-banner">DEMO-BACKTEST mit synthetischen Kursen – die Zahlen bedeuten nichts</div>`);
  parts.push(html`<h2>Simulator: Sparplan mit echten Kursen</h2><div id="sim"></div>`);
  parts.push(raw('<details class="more" id="expert" style="margin-top:18px"><summary>Expertenansicht: alle festen Backtest-Varianten mit 10.000 € Einmalanlage</summary>'));
  parts.push(note('error', html`<b>Die Ergebnisse sind wahrscheinlich zu gut.</b> ${bt.warnings[0]}`));
  parts.push(html`<details class="more"><summary>Alle Einschränkungen (${bt.warnings.length})</summary><ul class="small" style="padding-left:18px">${bt.warnings.slice(1).map((w) => html`<li style="margin-bottom:6px">${w}</li>`)}</ul></details>`);

  // Fazit (regelbasiert, vorsichtig formuliert)
  parts.push(html`<h2>Einordnung</h2><div class="panel small">${conclusions(V).map((t) => html`<p>${t}</p>`)}<p class="muted" style="margin:0">Automatisch aus den Zahlen erzeugt. Vergangene Ergebnisse sind keine Garantie, und der Survivorship Bias verzerrt alle Einzelaktien-Varianten nach oben.</p></div>`);

  // Wertentwicklung
  parts.push(html`<h2>Wertentwicklung</h2><div class="panel">
    <div class="legend" id="leg">${bt.variants.filter((v) => v.curve.length).map((v) => html`<button data-id="${v.id}" aria-pressed="${sel.includes(v.id)}"><span class="swatch" data-sw="${v.id}"></span>${short(v)}</button>`)}</div>
    <div id="eq"></div><p class="xs muted" style="margin:6px 0 0">Logarithmische Skala, Start = 100. Höchstens vier Linien gleichzeitig. Tippe auf die Legende zum Wechseln.</p></div>`);
  // Tabelle
  parts.push(html`<h2>Kennzahlen</h2><p class="xs muted">Rendite p. a. vor Steuern nach Kosten. "Nach Steuer": inklusive laufender Abgeltungsteuer und Besteuerung bei Verkauf am Ende. ETFs mit 30 % Teilfreistellung.</p>`);
  for (const [title, fn] of GROUPS) {
    const rows = bt.variants.filter(fn);
    if (!rows.length) continue;
    parts.push(html`<h3 style="margin-top:14px">${title}</h3><div class="table-wrap"><table><thead><tr>
      <th class="sticky">Variante</th><th class="n">Rendite p. a.</th><th class="n">nach Steuer</th><th class="n">Volatilität</th><th class="n">Max. Verlust</th><th class="n">Sharpe</th><th class="n">Trades</th><th class="n">Umschlag p. a.</th><th class="n">Monate besser</th><th class="n">Cash-Anteil</th><th class="n">ab</th></tr></thead><tbody>
      ${rows.map((v) => { const m = v.metrics; return html`<tr><td class="sticky">${v.name}</td><td class="n">${fmtPct(m.cagr)}</td><td class="n">${fmtPct(m.cagr_after_tax)}</td><td class="n">${fmtPct(m.volatility, 1, false)}</td>
        <td class="n">${fmtPct(m.max_drawdown)}</td><td class="n">${fmtNum(m.sharpe, 2)}</td><td class="n">${m.trades ?? '–'}</td><td class="n">${m.turnover != null ? `${fmtNum(m.turnover * 100, 0)} %` : '–'}</td>
        <td class="n">${fmtPct(m.hit_rate_months, 0, false)}</td><td class="n">${fmtPct(m.cash_share, 0, false)}</td><td class="n">${m.start ? m.start.slice(0, 4) : '–'}</td></tr>`; })}
      </tbody></table></div>`);
  }
  parts.push(html`<p class="xs muted">"Monate besser" = Anteil der Monate mit höherer Rendite als das gleichgewichtete Universum. Sharpe vereinfacht mit 0 % Zins.</p>`);
  // Letzte 10 Jahre
  parts.push(html`<h2>Nur die letzten ${bt.assumptions.recent_years} Jahre</h2><div class="table-wrap"><table><thead><tr><th class="sticky">Variante</th><th class="n">Rendite p. a.</th><th class="n">Max. Verlust</th><th class="n">Sharpe</th></tr></thead><tbody>
    ${bt.variants.filter((v) => v.metrics_recent?.cagr != null).map((v) => html`<tr><td class="sticky">${v.name}</td><td class="n">${fmtPct(v.metrics_recent.cagr)}</td><td class="n">${fmtPct(v.metrics_recent.max_drawdown)}</td><td class="n">${fmtNum(v.metrics_recent.sharpe, 2)}</td></tr>`)}
    </tbody></table></div>`);
  // Einzelvariante
  parts.push(html`<h2>Einzelne Variante</h2><label class="field"><span>Variante</span><select id="one">${bt.variants.map((v) => html`<option value="${v.id}" ${v.id === 'app_top10' ? 'selected' : ''}>${v.name}</option>`)}</select></label>
    <div class="panel"><h3>Rückgang vom Höchststand</h3><div id="dd"></div></div><div class="panel"><h3>Rendite je Kalenderjahr</h3><div id="yr"></div></div>`);
  // Sparplan
  if (bt.savings?.length) {
    parts.push(html`<h2>Sparplan-Vergleich</h2><p class="xs muted">${fmtEUR(bt.assumptions.monthly_savings, 0)} pro Monat ab ${fmtDate(bt.savings[0].start)}. Interner Zinsfuß = Rendite pro Jahr unter Berücksichtigung der Einzahlungszeitpunkte.</p>
      <div class="table-wrap"><table><thead><tr><th class="sticky">Sparplan</th><th class="n">Eingezahlt</th><th class="n">Endwert</th><th class="n">nach Steuer</th><th class="n">Zinsfuß p. a.</th><th class="n">nach Steuer</th><th class="n">Max. Verlust</th><th class="n">Trades</th></tr></thead><tbody>
      ${bt.savings.map((s) => html`<tr><td class="sticky">${s.name}</td><td class="n">${fmtEUR(s.contributions, 0)}</td><td class="n">${fmtEUR(s.final, 0)}</td><td class="n">${fmtEUR(s.final_after_tax, 0)}</td><td class="n">${fmtPct(s.irr)}</td><td class="n">${fmtPct(s.irr_after_tax)}</td><td class="n">${fmtPct(s.max_drawdown)}</td><td class="n">${s.trades}</td></tr>`)}
      </tbody></table></div><div class="panel"><div id="sp"></div></div>`);
  }
  // Kosten
  if (bt.cost_sensitivity?.length) {
    const keys = Object.keys(bt.assumptions.costs);
    parts.push(html`<h2>Einfluss der Handelskosten</h2><div class="table-wrap"><table><thead><tr><th class="sticky">Variante</th>${keys.map((k) => html`<th class="n">${bt.assumptions.costs[k].label}</th>`)}</tr></thead><tbody>
      ${bt.cost_sensitivity.map((r) => html`<tr><td class="sticky">${r.name}</td>${keys.map((k) => html`<td class="n">${fmtPct(r[k]?.cagr)}</td>`)}</tr>`)}</tbody></table></div>`);
  }
  // Marktphasen
  const per = bt.regimes?.periods || [];
  if (per.length) {
    const cols = ['ew_universe', 'msci_world_eur', 'ra_top10', 'app_top10', 'app_top1'].filter((id) => V.has(id));
    parts.push(html`<h2>Marktphasen</h2><div class="table-wrap"><table><thead><tr><th class="sticky">Phase</th>${cols.map((c) => html`<th class="n">${short(V.get(c))}</th>`)}</tr></thead><tbody>
      ${per.map((p) => html`<tr><td class="sticky">${p.name}<div class="xs muted">${fmtDate(p.start)}–${fmtDate(p.end)}</div></td>${cols.map((c) => html`<td class="n">${fmtPct(p.returns[c])}</td>`)}</tr>`)}
      </tbody></table></div>`);
    const bb = bt.regimes.bull_bear || {};
    parts.push(html`<div class="table-wrap"><table><thead><tr><th class="sticky">Ø Monatsrendite</th><th class="n">Markt im Plus (12 M)</th><th class="n">Markt im Minus</th></tr></thead><tbody>
      ${cols.filter((c) => bb[c]).map((c) => html`<tr><td class="sticky">${short(V.get(c))}</td><td class="n">${fmtPct(bb[c].bull_avg_month, 2)}</td><td class="n">${fmtPct(bb[c].bear_avg_month, 2)}</td></tr>`)}</tbody></table></div>`);
  }
  parts.push(html`<h2>Annahmen</h2><div class="panel small"><dl class="kv">
    <dt>Handelszeitpunkt</dt><dd style="white-space:normal">${bt.assumptions.execution}</dd>
    <dt>Steuer</dt><dd>${fmtPct(bt.assumptions.tax.rate, 3, false)}, Pauschbetrag ${fmtEUR(bt.assumptions.tax.allowance, 0)}</dd>
    <dt>Marktproxy für Filter</dt><dd style="white-space:normal">${bt.assumptions.market_proxy}</dd>
    <dt>MSCI-Volatilitätsschocks</dt><dd style="white-space:normal">${(bt.vol_shock_months || []).length} Monate</dd></dl></div>`);
  parts.push(raw('</details>'));
  root.innerHTML = parts.join('');
  // Aktienliste für den Backtest: damalige Indexzusammensetzung (S&P 500, DAX, Kombination, ACWI ab 2019)
  const simEl = root.querySelector('#sim');
  const idx = await loadSimIndex();
  const avail = (idx?.universes || []).filter((u) => u.available);
  const missing = (idx?.universes || []).filter((u) => !u.available);
  const choices = [...avail.map((u) => ({ key: u.key, text: `${u.label} – ab ${String(u.coverage_from).slice(5)}/${String(u.coverage_from).slice(0, 4)}` })),
    { key: 'current', text: 'MSCI ACWI – heutige Liste (verzerrt, nur zum Vergleich)' }];
  let cur = await getSetting('simUniverse', null);
  if (!choices.some((c) => c.key === cur)) cur = avail.some((u) => u.key === 'sp500') ? 'sp500' : choices[0].key;
  const pick = document.createElement('div');
  simEl.before(pick);
  pick.innerHTML = html`<div class="panel"><label class="field" style="margin:0"><span>Aktienliste für den Backtest</span>
    <select id="simuni">${choices.map((c) => html`<option value="${c.key}" ${c.key === cur ? 'selected' : ''}>${c.text}</option>`)}</select></label>
    <p class="xs muted" id="simuniinfo" style="margin:8px 0 0"></p>
    ${missing.length ? html`<p class="xs muted" style="margin:6px 0 0">Noch nicht verfügbar: ${missing.map((u) => `${u.label} (${u.reason || 'wird aufgebaut'})`).join('; ')}</p>` : ''}</div>`;
  const info = (key) => {
    const u = avail.find((x) => x.key === key);
    pick.querySelector('#simuniinfo').textContent = u
      ? `In jedem Monat nur die Aktien, die damals im Index waren (${u.source}). Ab ${String(u.coverage_from || '').split('-').reverse().join('/')}. Im Schnitt ${Math.round(((u.coverage_count_avg ?? u.coverage_avg) || 0) * 100)} % der damaligen Mitglieder mit Kursen${u.coverage_by_weight ? ` (${Math.round((u.coverage_avg || 0) * 100)} % des Indexgewichts)` : ''}.${u.tiingo ? (u.tiingo.key ? ` Kurse ehemaliger Mitglieder von Tiingo: ${u.tiingo.stored}${u.tiingo.open ? `, noch ${u.tiingo.open} offen (werden in den nächsten Läufen geladen)` : ''}.` : ' Tiingo-Schlüssel nicht hinterlegt – frühere Jahre nur mit Yahoo-Kursen.') : ''}`
      : 'Heutige ACWI-Mitglieder rückwirkend angewandt: Firmen, die damals noch nicht im Index waren, werden mitgekauft. Ergebnisse zu günstig.';
  };
  const show = async (key) => {
    info(key);
    simEl.innerHTML = String(note('info', 'Lade Backtest-Daten …'));
    let sim = null;
    try { sim = await loadSimulatorFor(key); } catch { sim = null; }
    renderSimulator(simEl, sim);
  };
  pick.querySelector('#simuni').onchange = async (e) => { await setSetting('simUniverse', e.target.value); show(e.target.value); };
  await show(cur);

  const eqEl = root.querySelector('#eq');
  const drawEq = () => {
    const chosen = sel.slice(0, 4).map((id) => V.get(id));
    root.querySelectorAll('[data-sw]').forEach((s) => {
      const k = sel.indexOf(s.dataset.sw);
      s.style.background = k >= 0 && k < 4 ? SERIES_COLORS[k] : 'var(--line)';
    });
    lineChart(eqEl, { height: 240, log: true, label: 'Wertentwicklung im Backtest', yFmt: (v) => fmtNum(v, 0), tipFmt: (v) => fmtNum(v, 0),
      series: chosen.map((v, i) => ({ name: v.name, short: short(v), points: v.curve, color: SERIES_COLORS[i] })) });
  };
  root.querySelector('#leg').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-id]');
    if (!b) return;
    const id = b.dataset.id;
    const k = sel.indexOf(id);
    if (k >= 0) sel.splice(k, 1); else { sel.push(id); if (sel.length > 4) sel.shift(); }
    root.querySelectorAll('#leg button').forEach((x) => x.setAttribute('aria-pressed', String(sel.includes(x.dataset.id))));
    drawEq();
  });
  drawEq();
  root.querySelector('#expert').addEventListener('toggle', () => { drawEq(); drawOne(); });
  const drawOne = () => {
    const v = V.get(root.querySelector('#one').value);
    lineChart(root.querySelector('#dd'), { height: 170, area: true, zero: true, endLabels: false, label: 'Rückgang vom Hoch', yFmt: (x) => `${fmtNum(x, 0)} %`, tipFmt: (x) => `${fmtNum(x, 1)} %`,
      series: [{ name: v.name, points: v.drawdown, color: '#e66767' }] });
    const ys = Object.keys(v.yearly).sort();
    barChart(root.querySelector('#yr'), { labels: ys, values: ys.map((y) => v.yearly[y]), fmt: (x) => fmtPct(x, 1) });
  };
  root.querySelector('#one').onchange = drawOne;
  drawOne();
  const spEl = root.querySelector('#sp');
  if (spEl) lineChart(spEl, { height: 220, label: 'Sparplan-Depotwert', yFmt: (v) => fmtNum(v / 1000, 0) + ' T', tipFmt: (v) => fmtEUR(v, 0),
    series: bt.savings.slice(0, 4).map((s, i) => ({ name: s.name, short: s.id === 'sp_etf' ? 'ETF' : s.id === 'sp_top1' ? 'Top 1' : 'Top 10', points: s.curve, color: SERIES_COLORS[i] })) });
}

function short(v) {
  const map = { ew_universe: 'Universum', msci_world_eur: 'MSCI World', msci_world_usd: 'World USD', msci_momentum_eur: 'World Mom.',
    msci_usa_momentum: 'USA Mom.', m12_top10: '12M T10', m612_top10: '6+12 T10', ra_top10: 'RA T10', ra_top5: 'RA T5', ra_top1: 'RA T1',
    ra_top10_score: 'RA T10 gew.', app_top10: 'App T10', app_top1: 'App T1', app_top10_ma200: '+200T', app_top10_regime: '+Markt',
    app_top10_volshock: '+Vola', app_top10_hold10: 'Band 10', app_top10_hold30: 'Band 30' };
  return map[v.id] || v.name.slice(0, 10);
}

function conclusions(V) {
  const out = [];
  const g = (id) => V.get(id)?.metrics || {};
  const strat = [...V.values()].filter((v) => v.group === 'strategy' && Number.isFinite(v.metrics.sharpe));
  if (strat.length) {
    const best = strat.reduce((a, b) => (b.metrics.sharpe > a.metrics.sharpe ? b : a));
    out.push(`Bestes Verhältnis von Rendite zu Schwankung (Sharpe) im Test: ${best.name} mit ${fmtNum(best.metrics.sharpe, 2)}, ${fmtPct(best.metrics.cagr)} p. a. und maximal ${fmtPct(best.metrics.max_drawdown)} Verlust.`);
  }
  const t1 = g('ra_top1'), t10 = g('ra_top10'), t5 = g('ra_top5');
  if (Number.isFinite(t1.cagr) && Number.isFinite(t10.cagr)) {
    out.push(`Eine Aktie gegen zehn: Top 1 erzielte ${fmtPct(t1.cagr)} p. a. bei ${fmtPct(t1.volatility, 0, false)} Volatilität und ${fmtPct(t1.max_drawdown)} maximalem Verlust. Top 10 kam auf ${fmtPct(t10.cagr)} p. a., ${fmtPct(t10.volatility, 0, false)} und ${fmtPct(t10.max_drawdown)}${Number.isFinite(t5.cagr) ? `, Top 5 auf ${fmtPct(t5.cagr)} p. a.` : ''}. ${t1.sharpe > t10.sharpe ? 'Die Konzentration war risikobereinigt besser, aber mit deutlich höherem Einzelrisiko.' : 'Die Streuung auf zehn Aktien war risikobereinigt besser.'}`);
  }
  const a10 = g('app_top10'), ma = g('app_top10_ma200'), rg = g('app_top10_regime');
  if (Number.isFinite(a10.cagr) && Number.isFinite(ma.cagr)) out.push(`200-Tage-Filter: ${ma.sharpe > a10.sharpe ? 'verbesserte' : 'verbesserte nicht'} das Rendite-Risiko-Verhältnis (Sharpe ${fmtNum(ma.sharpe, 2)} statt ${fmtNum(a10.sharpe, 2)}). Er ist deshalb ${ma.sharpe > a10.sharpe ? 'ein Kandidat für eine künftige, dokumentierte Methodik-Version' : 'nicht Teil der Regeln'}.`);
  if (Number.isFinite(rg.cagr) && Number.isFinite(a10.cagr)) out.push(`Markt-Trendfilter: maximaler Verlust ${fmtPct(rg.max_drawdown)} statt ${fmtPct(a10.max_drawdown)}, Rendite ${fmtPct(rg.cagr)} statt ${fmtPct(a10.cagr)} p. a., Cash-Anteil ${fmtPct(rg.cash_share, 0, false)}.`);
  const ew = g('ew_universe');
  if (Number.isFinite(a10.cagr) && Number.isFinite(ew.cagr)) out.push(`Gegenüber dem fairsten Maßstab, dem gleichgewichteten Universum mit derselben Verzerrung (${fmtPct(ew.cagr)} p. a.), lagen die App-Regeln mit Top 10 bei ${fmtPct(a10.cagr)} p. a. nach Kosten.`);
  return out;
}



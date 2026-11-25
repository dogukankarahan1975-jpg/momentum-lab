// Autopilot: ein fester Monatsplan (verkaufen, kaufen, auffüllen) für das eigene Depot.
import { ACTION_TEXT, STATUS_TEXT, buildPlan, monthName } from '../autopilot.js';
import { loadAutopilot, loadScreen } from '../data.js';
import { computePortfolio } from '../depot.js';
import { cls, fmtDate, fmtEUR, fmtPct, parseDec } from '../fmt.js';
import { state } from '../state.js';
import { getSetting, setSetting } from '../store.js';
import { chevron, esc, html, note } from '../ui.js';

const MARKET_SHORT = { none: 'Kein Markt-Trendfilter', soft: 'Trendfilter: im Abwärtstrend keine Neukäufe', hard: 'Trendfilter: im Abwärtstrend alles parken' };

export async function render(root) {
  let ap = null, screen = null;
  try { ap = await loadAutopilot(); } catch { ap = null; }
  try { screen = await loadScreen(); } catch { screen = null; }
  const parts = [html`<h1>Autopilot</h1>
    <p class="lede">Ein fester Plan pro Monat. Du setzt ihn einmal im Monat um und musst dazwischen nichts tun.</p>`];
  if (!ap || ap.status === 'fehler' || !ap.plan?.available) {
    parts.push(note('warn', ap?.reason || ap?.plan?.reason || 'Der Monatsplan ist noch nicht verfügbar. Er entsteht beim nächsten nächtlichen Datenlauf.'));
    root.innerHTML = parts.join('');
    return;
  }
  if (ap.demo) parts.push(html`<div class="demo-banner">DEMO-DATEN – der Plan ist nicht echt</div>`);
  const plan = ap.plan;
  const rule = plan.rule;
  const act = ACTION_TEXT[plan.action] || ACTION_TEXT.NORMAL;
  const newCash = await getSetting('apNewCash', 0);
  const pf = computePortfolio(state.positions, state.txs, screen);
  const holdings = pf.open.map((i) => ({
    symbol: i.pos.symbol, name: i.pos.name, mvEUR: i.mvEUR, posId: i.pos.id,
    sector: screen?.bySymbol?.get(i.pos.symbol)?.sector || null,
  }));
  const res = buildPlan(plan, holdings, newCash);

  // Kopf: Termin und Marktlage
  parts.push(html`<section class="panel">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
      <h3 style="margin:0">Plan für ${monthName(plan.trade_from)}</h3>
      <span class="badge ${act.cls === 'ok' ? 'b-buy' : act.cls === 'warn' ? 'b-stop' : 'b-sell'}">${act.label}</span>
    </div>
    <p class="small" style="margin:8px 0">${plan.action_text}</p>
    <p class="small" style="margin:4px 0"><span class="muted">Umsetzen:</span> ab ${fmtDate(plan.trade_from)}, am besten in der ersten Woche des Monats</p>
    <p class="small" style="margin:4px 0"><span class="muted">Nächster Plan:</span> ab ${fmtDate(plan.next_plan)}</p>
    <p class="small" style="margin:4px 0"><span class="muted">Gesamtmarkt:</span> ${plan.market.bull ? 'über' : 'unter'} der 200-Tage-Linie am ${fmtDate(plan.signal_date)}${plan.market.now ? `, heute ${plan.market.now.bull ? 'darüber' : 'darunter'} (${fmtPct(plan.market.now.dist_ma200)})` : ''}</p>
    <p class="xs muted" style="margin:4px 0 0">Grundlage sind die Schlusskurse vom ${fmtDate(plan.signal_date)}, genau wie im Backtest.</p>
  </section>`);

  // Neues Geld
  parts.push(html`<label class="field"><span>Neues Geld für diesen Monat (z. B. deine Sparrate), in €</span>
    <input id="cash" inputmode="decimal" value="${newCash ? String(newCash).replace('.', ',') : ''}" placeholder="0">
    <div class="hint">Verkaufserlöse rechnet der Autopilot automatisch dazu. Steuern und Gebühren beim Verkauf sind nicht abgezogen.</div></label>`);

  // Aufgabenliste
  const todo = [];
  if (res.sells.length) todo.push(group('1. Verkaufen', res.sells.map((r) => row(r.name, `${STATUS_TEXT[r.code] || ''}${r.pct != null ? `, Rang Top ${fmtPct(r.pct, 0, false)}` : ''}`,
    html`<span class="badge b-sell">Verkaufen</span><div class="xs muted">${fmtEUR(r.mvEUR, 0)}</div>`, `#/position/${encodeURIComponent(r.posId)}`))));
  if (res.buys.length) todo.push(group(`${res.sells.length ? '2' : '1'}. Neu kaufen`, res.buys.map((b) => row(b.name, `Platz ${b.rank} der Kaufliste${b.sector ? `, ${b.sector}` : ''}`,
    html`<span class="badge b-buy">für ${fmtEUR(b.amount, 0)}</span>`, `#/aktie/${encodeURIComponent(b.symbol)}`))));
  if (res.topups.length) todo.push(group('Aufstocken (untergewichtet)', res.topups.map((t) => row(t.name, `liegt mehr als 25 % unter dem Zielbetrag von ${fmtEUR(res.target, 0)}`,
    html`<span class="badge b-cont">+ ${fmtEUR(t.amount, 0)}</span>`, `#/position/${encodeURIComponent(t.posId)}`))));
  const checks = res.kept.filter((r) => r.todo === 'pruefen');
  if (checks.length) todo.push(group('Selbst prüfen', checks.map((r) => row(r.name, r.code === 'X' ? 'Nicht im MSCI-World-Universum: der Autopilot bewertet sie nicht.' : 'Auffällige Kursdaten, zum Beispiel Übernahme oder Datenfehler.',
    html`<span class="badge b-check">Prüfen</span>`, `#/position/${encodeURIComponent(r.posId)}`))));
  const holds = res.kept.filter((r) => r.todo === 'halten');
  if (holds.length) todo.push(group('Halten, nichts tun', holds.map((r) => row(r.name, r.code === 'W' ? 'Verkaufsbedingung einmal erfüllt. Fällt sie am nächsten Monatsende erneut an, wird verkauft.' : `im Halteband${r.pct != null ? ` (Top ${fmtPct(r.pct, 0, false)})` : ''}`,
    html`<span class="badge ${r.code === 'W' ? 'b-stop' : 'b-hold'}">${r.code === 'W' ? 'Warnung' : 'Halten'}</span>`, `#/position/${encodeURIComponent(r.posId)}`))));
  const nothing = !res.sells.length && !res.buys.length && !res.topups.length;
  parts.push(html`<h2>Was du tun musst</h2>`);
  if (!holdings.length && !res.buys.length) {
    parts.push(note('info', res.park || res.noBuys ? 'Diesen Monat keine Käufe. Lass dein Geld geparkt.' : 'Trage oben ein, wie viel Geld du anlegen willst. Dann zeigt der Autopilot, welche Aktien du mit welchem Betrag kaufst.'));
  } else if (nothing) {
    parts.push(note('info', 'Diesen Monat ist nichts zu tun. Alle Positionen bleiben, wie sie sind.'));
  }
  parts.push(todo.join(''));
  if (res.rest > 50 && !res.park) parts.push(note('info', `${fmtEUR(res.rest, 0)} bleiben übrig (keine freien Plätze und keine stark untergewichtete Position). Das Geld wartet bis zum nächsten Plan.`));
  if (res.waiting.length) parts.push(note('info', `Für ${res.waiting.length} weitere freie Plätze reicht das Geld diesen Monat nicht. Nächste Kandidaten: ${res.waiting.slice(0, 3).map((w) => w.name).join(', ')}. Sie kommen mit dem nächsten Geld dran.`));
  if (res.skipped.length) parts.push(html`<p class="xs muted">Übersprungen wegen Branchengrenze: ${res.skipped.map((s) => s.name).join(', ')}.</p>`);
  parts.push(html`<p class="xs muted">Ziel: ${res.n} Aktien zu je etwa ${fmtEUR(res.target, 0)}${res.cap ? `, höchstens ${res.cap} aus derselben Branche` : ''}. Du hältst ${res.kept.length} Aktien, ${res.freeSlots} Plätze sind frei.</p>`);

  // Regeln
  parts.push(html`<h2>Die Regeln</h2>
    <div class="panel"><p class="small" style="margin-top:0"><b>${rule.name}</b>${rule.provisional ? ' (vorläufig, bis der Backtest die Regel auswählt)' : ''}</p>
    <ol class="small" style="padding-left:20px;margin:0">
      <li>Einmal im Monat: in der ersten Woche hier reinschauen und den Plan umsetzen. Sonst nichts tun.</li>
      <li>Verkaufen, wenn eine Aktie an zwei Monatsenden hintereinander nicht mehr zu den besten 20 % gehört oder ihr 12-Monats-Momentum nicht mehr positiv ist. Sofort verkaufen, wenn sie unter den Durchschnitt fällt oder 12 Monate mehr als 10 % im Minus ist.</li>
      <li>Freie Plätze mit den Bestplatzierten der Kaufliste füllen, bis ${rule.n} Aktien im Depot sind${rule.sector_cap ? `, höchstens ${rule.sector_cap} aus einer Branche` : ''}.</li>
      <li>${MARKET_SHORT[rule.market]}${rule.market === 'none' ? '. Im Lernzeitraum brachte der Filter nicht genug.' : '.'}</li>
      <li>Neues Geld zuerst in freie Plätze, dann in deutlich untergewichtete Aktien. Gewinner werden nie verkauft, nur weil sie gestiegen sind.</li>
    </ol></div>`);

  // Backtest
  const bt = ap.backtest;
  if (bt?.available) {
    const oosC = bt.oos?.[bt.chosen];
    const oosB = bt.baseline && bt.baseline !== bt.chosen ? bt.oos?.[bt.baseline] : null;
    const w = bt.benchmarks_oos?.msci_world_eur;
    const m = bt.benchmarks_oos?.msci_momentum_eur;
    const line = (label, r, strong) => r ? html`<tr${strong ? html` style="font-weight:700"` : ''}><td class="sticky">${label}</td><td class="n ${cls(r.cagr_after_tax)}">${fmtPct(r.cagr_after_tax)}</td><td class="n">${fmtPct(r.cagr)}</td><td class="n neg">${fmtPct(r.max_drawdown, 0)}</td></tr>` : '';
    parts.push(html`<h2>Hat das früher funktioniert?</h2>
      <p class="small muted">Die Regel wurde automatisch nur mit den Jahren ${bt.insample.start?.slice(0, 4) || '2003'}–2014 aus ${bt.grid.length} Varianten gewählt. Bedingung: höchster Gewinn nach Steuern, Zwischenverlust nicht tiefer als ${fmtPct(bt.max_drawdown_limit, 0)}. Die Jahre ab 2015 hat sie dabei nie gesehen. Sie sind der ehrliche Test.</p>
      <h3>Test ab 2015 mit 10.000 € (nach Kosten)</h3>
      <div class="table-wrap"><table><thead><tr><th class="sticky"></th><th class="n">p. a. nach Steuern</th><th class="n">vor Steuern</th><th class="n">größter Verlust</th></tr></thead><tbody>
        ${line('Autopilot', oosC, true)}${line('Stage-1-Regeln ohne Extras', oosB)}${line('MSCI World ETF', w)}${line('MSCI World Momentum ETF', m)}
      </tbody></table></div>
      ${bt.savings ? html`<h3>Sparplan ${fmtEUR(bt.savings.monthly, 0)} pro Monat ab 2015</h3>
        <div class="grid2"><div class="stat"><div class="l">Autopilot, nach Steuern</div><div class="v">${fmtEUR(bt.savings.final_after_tax, 0)}</div><div class="xs muted">eingezahlt ${fmtEUR(bt.savings.contributions, 0)}, Steuern bezahlt ${fmtEUR(bt.savings.taxes_paid, 0)}</div></div>
        <div class="stat"><div class="l">MSCI World ETF, nach Steuern</div><div class="v">${bt.savings.etf ? fmtEUR(bt.savings.etf.final_after_tax, 0) : '–'}</div><div class="xs muted">eingezahlt ${bt.savings.etf ? fmtEUR(bt.savings.etf.contributions, 0) : '–'}</div></div></div>` : ''}
      ${bt.full ? html`<h3>Gesamter Zeitraum seit ${bt.full.start?.slice(0, 4)}</h3>
        <p class="small">${fmtPct(bt.full.cagr)} pro Jahr vor Steuern, ${fmtPct(bt.full.cagr_after_tax)} nach Steuern. Größter Zwischenverlust ${fmtPct(bt.full.max_drawdown, 0)} (${fmtDate(bt.full.max_dd_date)})${bt.full.worst_year ? `, schlechtestes Jahr ${bt.full.worst_year.year} mit ${fmtPct(bt.full.worst_year.return, 0)}` : ''}.</p>` : ''}
      <details class="panel"><summary class="small">Alle ${bt.grid.length} getesteten Varianten (Lernzeitraum)</summary>
        <div class="table-wrap"><table><thead><tr><th class="sticky">Variante</th><th class="n">p. a. n. St.</th><th class="n">größter Verlust</th></tr></thead><tbody>
        ${bt.grid.map((g) => html`<tr${g.chosen ? html` style="font-weight:700"` : ''}><td class="sticky">${g.chosen ? '▶ ' : ''}${g.name}</td><td class="n">${fmtPct(g.insample.cagr_after_tax)}</td><td class="n ${g.meets_limit ? '' : 'neg'}">${fmtPct(g.insample.max_drawdown, 0)}</td></tr>`)}
        </tbody></table></div></details>
      ${note('warn', bt.warnings?.[0] || 'Vergangene Ergebnisse sind keine Garantie.')}
      <p class="xs muted">${(bt.warnings || []).slice(1).map((x) => esc(x)).join(' ')}</p>`);
  } else {
    parts.push(note('info', bt?.reason || 'Der Autopilot-Backtest wird beim nächsten Monatswechsel berechnet.'));
  }
  parts.push(html`<a class="row panel" href="#/depot" style="color:inherit;margin-top:10px"><div class="grow"><div class="title">Käufe und Verkäufe im Depot erfassen</div><div class="sub">Damit der nächste Plan dein Depot kennt</div></div>${chevron}</a>
    <p class="xs muted">Keine Anlageberatung. Der Autopilot setzt feste, vorab getestete Regeln um. Ob du handelst, entscheidest du.</p>`);
  root.innerHTML = parts.join('');
  const inp = root.querySelector('#cash');
  inp.addEventListener('change', async () => {
    const v = parseDec(inp.value);
    await setSetting('apNewCash', Number.isFinite(v) && v > 0 ? v : 0);
    render(root);
  });
}

function group(title, rows) {
  return html`<div class="group-title">${title}</div><div class="group">${rows}</div>`;
}
function row(title, sub, end, href) {
  return html`<a class="row" href="${href}" style="color:inherit"><div class="grow"><div class="title">${title}</div><div class="sub" style="white-space:normal">${sub}</div></div><div class="end">${end}</div>${chevron}</a>`;
}

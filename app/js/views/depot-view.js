import { lineChart } from '../charts.js';
import { loadMonthly, loadScreen } from '../data.js';
import { computePortfolio, planOverview, reconstructHistory, INTERVALS } from '../depot.js';
import { cls, fmtDate, fmtEUR, fmtPct, fmtQty } from '../fmt.js';
import { latestScreening, state } from '../state.js';
import { db } from '../store.js';
import { badge, chevron, empty, html, note } from '../ui.js';
import { openTxForm } from './forms.js';

export async function render(root) {
  let screen = null;
  try { screen = await loadScreen(); } catch { /* ohne Kurse */ }
  const snap = await latestScreening();
  const sigBy = new Map((snap?.signals || []).map((s) => [s.positionId, s]));
  const pf = computePortfolio(state.positions, state.txs, screen);
  const t = pf.totals;
  const parts = [html`<h1>Mein Depot</h1>
    <p class="lede">Alle Daten bleiben auf diesem iPhone. Kurse kommen aus dem täglichen Datenlauf${screen ? ` (Stand ${fmtDate(screen.asof)})` : ''}.</p>
    <button class="btn primary block" id="add" style="margin-bottom:14px">+ Kauf, Verkauf oder Dividende erfassen</button>`];
  if (!state.positions.length) {
    parts.push(empty('Noch keine Positionen', 'Erfasse deinen ersten Kauf. Mehrere Kauftranchen, Sparpläne, Teilverkäufe, Dividenden und Splits werden unterstützt.'));
    root.innerHTML = parts.join('');
    root.querySelector('#add').onclick = () => openTxForm();
    return;
  }
  if (screen?.demo) parts.push(html`<div class="demo-banner">DEMO-KURSE – Werte sind nicht echt</div>`);
  if (t.missingPrices) parts.push(note('warn', `${t.missingPrices} Position(en) ohne Kurs. Ihr Wert fehlt in der Summe. Öffne die Position und trage den Kurs manuell ein.`));
  parts.push(html`<div class="grid2" style="margin-bottom:10px">
    <div class="stat"><div class="l">Marktwert</div><div class="v">${fmtEUR(t.mv, 0)}</div></div>
    <div class="stat"><div class="l">Investiert (Einstand)</div><div class="v">${fmtEUR(t.costOpen, 0)}</div></div>
    <div class="stat"><div class="l">Unrealisiert</div><div class="v ${cls(t.unreal)}">${fmtEUR(t.unreal, 0)}</div><div class="xs ${cls(t.unreal)}">${fmtPct(t.unrealPct)}</div></div>
    <div class="stat"><div class="l">Realisiert</div><div class="v ${cls(t.realized)}">${fmtEUR(t.realized, 0)}</div></div>
    <div class="stat"><div class="l">Dividenden</div><div class="v">${fmtEUR(t.dividends, 0)}</div></div>
    <div class="stat"><div class="l">Gesamtrendite</div><div class="v ${cls(t.totalReturn)}">${fmtPct(t.totalReturnPct)}</div><div class="xs muted">${fmtEUR(t.totalReturn, 0)} auf ${fmtEUR(t.bought, 0)} Käufe</div></div>
  </div>
  <h2>Entwicklung</h2><div class="panel"><div id="hist"><p class="muted small">Lädt Monatskurse …</p></div>
  <p class="xs muted" style="margin:6px 0 0">Monatsendwerte aus deinen Transaktionen und den Schlusskursen. Fehlende Kurse (z. B. bei manuellen Positionen) sind nicht enthalten.</p></div>
  <h2>Positionen</h2>
  <div class="group">${pf.open.sort((a, b) => (b.mvEUR || 0) - (a.mvEUR || 0)).map((i) => {
    const s = sigBy.get(i.pos.id);
    return html`<a class="row" href="#/position/${encodeURIComponent(i.pos.id)}">
      <div class="grow"><div class="title">${i.pos.name}</div>
        <div class="sub">${fmtQty(i.qty)} Stk., ${i.weight != null ? `${fmtPct(i.weight, 1, false)} Anteil` : 'ohne Kurs'}${i.mark?.source === 'manuell' ? ', Kurs manuell' : ''}</div>
        ${s ? html`<div style="margin-top:4px">${badge(s.signal)}${s.plan ? html` ${badge(s.plan.signal)}` : ''}</div>` : ''}</div>
      <div class="end"><div>${fmtEUR(i.mvEUR, 0)}</div><div class="xs ${cls(i.unreal)}">${fmtPct(i.unrealPct)}</div></div>${chevron}</a>`;
  })}</div>`);
  const activePlans = state.plans.filter((p) => p.active !== false);
  if (activePlans.length) {
    parts.push(html`<h2>Sparpläne</h2><div class="group">${activePlans.map((p) => {
      const pos = state.positions.find((x) => x.id === p.positionId);
      const ov = planOverview(p, state.txs.filter((x) => x.positionId === p.positionId));
      return html`<a class="row" href="#/position/${encodeURIComponent(p.positionId)}"><div class="grow"><div class="title">${pos?.name || '?'}</div>
        <div class="sub">${fmtEUR(p.amount)} ${INTERVALS[p.interval]}, nächste Ausführung ${fmtDate(ov.next)}</div></div>
        <div class="end">${ov.open ? html`<span class="badge b-stop">${ov.open} offen</span>` : html`<span class="xs muted">${ov.recorded} erfasst</span>`}</div>${chevron}</a>`;
    })}</div>`);
  }
  if (pf.closed.length) {
    parts.push(html`<details class="more"><summary>Geschlossene Positionen (${pf.closed.length})</summary><div class="group">${pf.closed.map((i) => html`<a class="row" href="#/position/${encodeURIComponent(i.pos.id)}">
      <div class="grow"><div class="title">${i.pos.name}</div><div class="sub">realisiert ${fmtEUR(i.realized)}, Dividenden ${fmtEUR(i.dividends)}</div></div>${chevron}</a>`)}</div></details>`);
  }
  root.innerHTML = parts.join('');
  root.querySelector('#add').onclick = () => openTxForm();
  // Historie
  try {
    const monthly = await loadMonthly();
    const hist = reconstructHistory(state.positions, state.txs, monthly);
    const vals = (await db.all('valuations')).sort((a, b) => a.date.localeCompare(b.date));
    const lastM = hist.length ? hist[hist.length - 1].date : '';
    const tail = vals.filter((v) => v.date > lastM);
    const val = [...hist.map((h) => [h.date, h.value]), ...tail.map((v) => [v.date, v.value])];
    const inv = [...hist.map((h) => [h.date, h.invested]), ...tail.map((v) => [v.date, v.invested])];
    if (val.length < 2) root.querySelector('#hist').innerHTML = '<p class="muted small" style="margin:0">Die Entwicklung erscheint, sobald Transaktionen aus mindestens zwei Monaten vorliegen.</p>';
    else lineChart(root.querySelector('#hist'), { height: 200, label: 'Depotentwicklung', yFmt: (v) => fmtEUR(v, 0).replace(/\s?€/, ''), tipFmt: (v) => fmtEUR(v, 0),
      series: [{ name: 'Depotwert', short: 'Wert', points: val }, { name: 'Investiert', short: 'Einstand', points: inv, color: 'var(--ink-3)', width: 1.5, dash: '4 3' }] });
  } catch (e) {
    root.querySelector('#hist').innerHTML = `<p class="muted small" style="margin:0">Monatskurse nicht verfügbar (${e.message}).</p>`;
  }
}

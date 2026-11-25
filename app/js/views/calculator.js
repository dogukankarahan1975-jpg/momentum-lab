// Kauf-Rechner: Gewinn aus Verkäufen und Aufteilung der Neukäufe (1 € je Kauf).
import { loadScreen } from '../data.js';
import { computePortfolio } from '../depot.js';
import { cls, fmtEUR, fmtNum, fmtPct, parseDec, todayISO } from '../fmt.js';
import { SELL_FEE, holdStatus, splitBuy } from '../holding.js';
import { state } from '../state.js';
import { getSetting, setSetting } from '../store.js';
import { html } from '../ui.js';

export async function render(root) {
  let screen = null;
  try { screen = await loadScreen(); } catch { /* ohne Liste */ }
  const saved = (await getSetting('calc', null)) || {};
  const v = { cost: '', credit: '', extra: '', n: 5, fee: 1, ...saved };
  const pf = computePortfolio(state.positions, state.txs, screen);
  const due = pf.open.filter((i) => holdStatus(i.pos, i, todayISO())?.state === 'verkaufen');
  const fmtIn = (x) => (x === '' || x == null ? '' : String(x).replace('.', ','));
  root.innerHTML = String(html`<h1>Kauf-Rechner</h1>
    <p class="lede">Was hast du mit den Verkäufen verdient, und mit wie viel Euro kaufst du jede neue Aktie?</p>
    <div class="panel">
      ${due.length ? html`<button class="btn block" id="pre" style="margin-bottom:10px">Fällige Verkäufe übernehmen (${due.length})</button>` : ''}
      <label class="field"><span>Damals investiert (Einstand der verkauften Aktien, €)</span><input id="cost" inputmode="decimal" value="${fmtIn(v.cost)}" placeholder="z. B. 2.500"></label>
      <label class="field"><span>Gutschrift aus den Verkäufen (€, schon nach Kosten)</span><input id="credit" inputmode="decimal" value="${fmtIn(v.credit)}" placeholder="z. B. 2.830"></label>
      <label class="field"><span>Zusätzliches Geld, z. B. Sparrate (€)</span><input id="extra" inputmode="decimal" value="${fmtIn(v.extra)}" placeholder="0"></label>
      <div class="grid2">
        <label class="field"><span>Neue Aktien</span><input id="n" inputmode="numeric" value="${v.n}"></label>
        <label class="field"><span>Gebühr je Kauf (€)</span><input id="fee" inputmode="decimal" value="${fmtIn(v.fee)}"></label>
      </div>
    </div>
    <div id="res"></div>`);
  const $ = (s) => root.querySelector(s);
  const calc = async () => {
    const cost = parseDec($('#cost').value) || 0;
    const credit = parseDec($('#credit').value) || 0;
    const extra = parseDec($('#extra').value) || 0;
    const n = Math.max(1, Math.min(20, Math.round(parseDec($('#n').value) || 5)));
    const fee = Math.max(0, parseDec($('#fee').value) || 0);
    await setSetting('calc', { cost, credit, extra, n, fee });
    const gain = credit - cost;
    const total = credit + extra;
    const sp = splitBuy(total, n, fee);
    const list = (screen?.candidates || []).slice(0, n).map((sym) => screen.bySymbol.get(sym)).filter(Boolean);
    $('#res').innerHTML = String(html`
      ${cost > 0 && credit > 0 ? html`<div class="grid2"><div class="stat"><div class="l">Gewinn aus den Verkäufen</div><div class="v ${cls(gain)}">${fmtEUR(gain, 2)}</div><div class="xs ${cls(gain)}">${fmtPct(cost > 0 ? gain / cost : null)}</div></div>
        <div class="stat"><div class="l">Rein → raus</div><div class="v" style="font-size:17px">${fmtEUR(cost, 0)} → ${fmtEUR(credit, 0)}</div></div></div>` : ''}
      <div class="panel"><h3 style="margin-top:0">So teilst du auf</h3>
        <p class="small" style="margin:0 0 8px">${fmtEUR(total, 2)} verfügbar − ${n} × ${fmtEUR(fee, 2)} Gebühr = ${fmtEUR(Math.max(0, total - sp.fees), 2)} für Aktien.</p>
        <p style="font-size:22px;font-weight:700;margin:0">je Aktie ${fmtEUR(sp.orderEach, 2)}</p>
        <p class="xs muted" style="margin:4px 0 0">Das ist das Ordervolumen ohne Gebühr. Inklusive 1 € Gebühr gehen pro Kauf ${fmtEUR(sp.each, 2)} vom Konto.</p>
        ${list.length ? html`<div class="group" style="margin-top:10px">${list.map((r, i) => html`<a class="row" href="#/aktie/${encodeURIComponent(r.symbol)}" style="color:inherit"><div class="grow"><div class="title">${i + 1}. ${r.name}</div><div class="sub">${r.symbol}</div></div><div class="end"><b>${fmtEUR(sp.orderEach, 2)}</b></div></a>`)}</div>
          <p class="xs muted">Top ${list.length} der aktuellen Screening-Liste (Stage 1).</p>` : ''}
      </div>`);
  };
  root.querySelectorAll('input').forEach((i) => i.addEventListener('input', calc));
  $('#pre')?.addEventListener('click', () => {
    const cost = due.reduce((s, i) => s + i.costOpen, 0);
    const credit = due.reduce((s, i) => s + Math.max(0, (i.mvEUR || 0) - SELL_FEE), 0);
    $('#cost').value = fmtNum(cost, 2);
    $('#credit').value = fmtNum(credit, 2);
    calc();
  });
  calc();
}

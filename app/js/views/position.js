import { loadScreen } from '../data.js';
import { computePosition, estimateSaleTax, markFor, planOverview, TX_LABEL, INTERVALS, sortTx } from '../depot.js';
import { cls, fmtDate, fmtEUR, fmtMoney, fmtNum, fmtPct, fmtPrice, fmtQty } from '../fmt.js';
import { latestScreening, reloadDepot, state, go } from '../state.js';
import { db } from '../store.js';
import { badge, confirmDialog, html, note, toast } from '../ui.js';
import { openManualPrice, openPlanForm, openPositionEdit, openTxForm } from './forms.js';

export async function render(root, id) {
  const pos = state.positions.find((p) => p.id === id);
  if (!pos) { root.innerHTML = String(note('error', 'Position nicht gefunden.')); return; }
  let screen = null;
  try { screen = await loadScreen(); } catch { /* */ }
  const txs = state.txs.filter((t) => t.positionId === id);
  const it = computePosition(pos, txs, markFor(pos, screen));
  const snap = await latestScreening();
  const sig = snap?.signals?.find((s) => s.positionId === id);
  const plans = state.plans.filter((p) => p.positionId === id);
  const row = screen?.bySymbol.get(pos.symbol);
  const tax = it.unreal > 0 ? estimateSaleTax(it.unreal, state.settings) : 0;
  const parts = [html`<p style="margin:4px 0"><a href="#/depot">‹ Depot</a></p><h1>${pos.name}</h1>
    <div class="chips" style="margin:6px 0 12px"><span class="chip">${pos.symbol}</span>${pos.isin ? html`<span class="chip">${pos.isin}</span>` : ''}${row ? html`<a class="chip" href="#/aktie/${encodeURIComponent(pos.symbol)}" style="color:var(--ice)">Analyse öffnen</a>` : ''}</div>`];
  if (it.errors.length) parts.push(note('error', html`Unstimmigkeiten: ${it.errors.join('; ')}`));
  if (sig) parts.push(html`<a class="panel" href="#/signale" style="display:block;color:inherit"><div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px">${badge(sig.signal)}${sig.plan ? badge(sig.plan.signal) : ''}</div>
    <p class="small" style="margin:0;color:var(--ink-2)">${sig.reasons?.[0] || ''}</p><p class="xs muted" style="margin:6px 0 0">Screening vom ${fmtDate(snap.createdAt.slice(0, 10))}</p></a>`);
  parts.push(html`<div class="panel"><dl class="kv">
    <dt>Stückzahl</dt><dd>${fmtQty(it.qty)}</dd>
    <dt>Ø Einstandskurs</dt><dd>${fmtEUR(it.avgCost)}</dd>
    <dt>Einstand offene Position</dt><dd>${fmtEUR(it.costOpen)}</dd>
    <dt>Aktueller Kurs</dt><dd>${it.mark ? html`${fmtPrice(it.mark.price, it.mark.currency)}<div class="xs muted">${it.mark.source === 'manuell' ? 'manuell, ' : ''}${fmtDate(it.mark.date)}${it.mark.currency !== 'EUR' ? `, ${fmtEUR(it.priceEUR)}` : ''}</div>` : 'fehlt'}</dd>
    <dt>Marktwert</dt><dd>${fmtEUR(it.mvEUR)}</dd>
    <dt>Gewinn/Verlust unrealisiert</dt><dd class="${cls(it.unreal)}">${fmtEUR(it.unreal)} (${fmtPct(it.unrealPct)})</dd>
    <dt>Realisiert (FIFO)</dt><dd class="${cls(it.realized)}">${fmtEUR(it.realized)}</dd>
    <dt>Dividenden (netto)</dt><dd>${fmtEUR(it.dividends)}</dd>
    <dt>Gesamtrendite</dt><dd class="${cls(it.totalReturn)}">${fmtEUR(it.totalReturn)} (${fmtPct(it.totalReturnPct)})</dd>
    <dt>Gebühren gesamt</dt><dd>${fmtEUR(it.fees)}</dd>
    ${it.unreal > 0 ? html`<dt>Geschätzte Steuer bei Verkauf heute</dt><dd>${fmtEUR(tax)}</dd>` : ''}
  </dl>${it.unreal > 0 ? html`<p class="xs muted" style="margin:8px 0 0">Schätzung: Abgeltungsteuer ${state.settings.churchTax ? 'inkl. Kirchensteuer' : 'plus Soli'}, verbleibender Pauschbetrag ${fmtEUR(state.settings.taxAllowanceLeft, 0)}. Verlustverrechnung mit anderen Positionen bleibt unberücksichtigt.</p>` : ''}
  ${!row ? html`<p class="small" style="margin:10px 0 0">Für dieses Symbol gibt es keine automatischen Kurse. <button class="btn small" id="mp">Kurs manuell eintragen</button></p>` : ''}</div>
  <div class="btn-row" style="margin-bottom:14px">
    <button class="btn small" data-t="BUY">+ Kauf</button><button class="btn small" data-t="SELL">Verkauf</button>
    <button class="btn small" data-t="DIV">Dividende</button><button class="btn small" data-t="SPLIT">Split</button>
  </div>`);
  // Sparplan
  parts.push(html`<h2>Sparplan</h2>`);
  if (!plans.length) parts.push(html`<div class="panel"><p class="muted small">Kein Sparplan angelegt.</p><button class="btn small" id="newplan">Sparplan anlegen</button></div>`);
  for (const p of plans) {
    const ov = planOverview(p, txs);
    parts.push(html`<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <div><b>${fmtEUR(p.amount)} ${INTERVALS[p.interval]}</b><div class="xs muted">seit ${fmtDate(p.start)}, Tag ${p.day}, ${p.active === false ? `gestoppt ${fmtDate(p.stoppedAt)}` : 'aktiv'}</div></div>
      <button class="btn small" data-plan="${p.id}">Bearbeiten</button></div>
      <dl class="kv small" style="margin-top:10px"><dt>Erfasste Ausführungen</dt><dd>${ov.recorded}</dd><dt>Investiert über Sparplan</dt><dd>${fmtEUR(ov.invested)}</dd>
      <dt>Ø Kaufkurs Sparplan</dt><dd>${fmtEUR(ov.avgPrice)}</dd><dt>Nächste Ausführung</dt><dd>${fmtDate(ov.next)}</dd></dl>
      ${ov.rows.length ? html`<details class="more" ${ov.open ? 'open' : ''}><summary>Geplante und erfasste Käufe</summary><div class="group">${ov.rows.slice(-12).reverse().map((r) => html`<div class="row">
        <div class="grow"><div class="title">${fmtDate(r.date)}</div><div class="sub">${r.status === 'erfasst' ? `erfasst: ${fmtQty(r.tx.qty)} Stk. zu ${fmtMoney(r.tx.price, r.tx.currency)}` : r.status === 'offen' ? 'noch nicht erfasst' : 'geplant'}</div></div>
        ${r.status === 'offen' ? html`<button class="btn small" data-exec="${p.id}" data-date="${r.date}" data-amt="${p.amount}">Erfassen</button>` : html`<span class="xs muted">${r.status}</span>`}</div>`)}</div></details>` : ''}</div>`);
  }
  // Transaktionen
  const list = sortTx(txs).reverse();
  parts.push(html`<h2>Transaktionen</h2>${list.length ? html`<div class="group">${list.map((t) => html`<button class="row" data-tx="${t.id}">
    <div class="grow"><div class="title">${TX_LABEL[t.type]} ${t.planId ? '(Sparplan)' : ''}</div><div class="sub">${fmtDate(t.date)}${t.note ? `, ${t.note}` : ''}</div></div>
    <div class="end small">${t.type === 'BUY' || t.type === 'SELL' ? html`<div>${fmtQty(t.qty)} × ${fmtMoney(t.price, t.currency)}</div><div class="xs muted">${t.fees ? `Gebühr ${fmtMoney(t.fees, t.currency)}` : ''}</div>` : t.type === 'DIV' ? fmtEUR(t.amount) : `${fmtNum(t.ratio, 4)} : 1`}</div></button>`)}</div>` : html`<p class="muted">Keine Transaktionen.</p>`}
  ${pos.note ? html`<h2>Notizen</h2><div class="panel"><p style="white-space:pre-wrap;margin:0">${pos.note}</p></div>` : ''}
  <div class="btn-row" style="margin:18px 0"><button class="btn" id="edit">Position bearbeiten</button>${row ? html`<button class="btn" id="mp2">Kurs manuell</button>` : ''}<button class="btn danger" id="del">Position löschen</button></div>`);
  root.innerHTML = parts.join('');
  root.querySelectorAll('[data-t]').forEach((b) => { b.onclick = () => openTxForm({ preset: { positionId: id, type: b.dataset.t } }); });
  root.querySelectorAll('[data-tx]').forEach((b) => { b.onclick = () => txMenu(txs.find((t) => t.id === b.dataset.tx)); });
  root.querySelectorAll('[data-plan]').forEach((b) => { b.onclick = () => openPlanForm(pos, plans.find((p) => p.id === b.dataset.plan)); });
  root.querySelectorAll('[data-exec]').forEach((b) => { b.onclick = () => openTxForm({ preset: { positionId: id, type: 'BUY', date: b.dataset.date, planId: b.dataset.exec, buyAmount: Number(b.dataset.amt) } }); });
  const np = root.querySelector('#newplan'); if (np) np.onclick = () => openPlanForm(pos);
  for (const sel of ['#mp', '#mp2']) { const b = root.querySelector(sel); if (b) b.onclick = () => openManualPrice(pos); }
  root.querySelector('#edit').onclick = () => openPositionEdit(pos);
  root.querySelector('#del').onclick = async () => {
    const ok = await confirmDialog({ title: 'Position löschen?', text: `${pos.name} mit ${txs.length} Transaktionen und ${plans.length} Sparplänen wird dauerhaft von diesem Gerät gelöscht. Ein vorheriges Backup kann sie wiederherstellen.`, confirm: 'Endgültig löschen', danger: true });
    if (!ok) return;
    for (const t of txs) await db.del('transactions', t.id);
    for (const p of plans) await db.del('plans', p.id);
    await db.del('positions', pos.id);
    await reloadDepot();
    toast('Position gelöscht');
    go('#/depot');
  };
}

async function txMenu(t) {
  const { openSheet } = await import('../ui.js');
  openSheet({ title: `${TX_LABEL[t.type]} vom ${fmtDate(t.date)}`, body: '<div class="btn-row"><button class="btn primary" id="e">Bearbeiten</button><button class="btn danger" id="d">Löschen</button></div>',
    onMount: (el, close) => {
      el.querySelector('#e').onclick = () => { close(); openTxForm({ tx: t }); };
      el.querySelector('#d').onclick = async () => {
        close();
        const ok = await confirmDialog({ title: 'Transaktion löschen?', text: 'Diese Transaktion wird von diesem Gerät gelöscht.', confirm: 'Löschen', danger: true });
        if (!ok) return;
        await db.del('transactions', t.id);
        await reloadDepot();
        toast('Gelöscht');
        window.dispatchEvent(new HashChangeEvent('hashchange'));
      };
    } });
}

import { freshness, loadScreen, loadStatus, cachedStatus } from '../data.js';
import { computePortfolio, estimateSaleTax } from '../depot.js';
import { fmtDate, fmtEUR, fmtPct, fmtRankPct } from '../fmt.js';
import { bestAlternative, computeSignals } from '../screening.js';
import { urgencyRank } from '../signals.js';
import { holdStatus } from '../holding.js';
import { todayISO } from '../fmt.js';
import { latestScreening, state } from '../state.js';
import { badge, empty, holdBand, html, note } from '../ui.js';

export async function render(root) {
  let screen;
  try { screen = await loadScreen(); } catch (e) {
    root.innerHTML = String(html`<h1>Signale</h1>${note('error', `Keine Daten: ${e.message}`)}`);
    return;
  }
  const status = cachedStatus() || await loadStatus().catch(() => null);
  const snap = await latestScreening();
  const fr = freshness(screen.asof);
  const pf = computePortfolio(state.positions, state.txs, screen);
  const sigs = computeSignals(screen, status, pf, state.plans, state.settings)
    .sort((a, b) => urgencyRank(a.urgency) - urgencyRank(b.urgency));
  const hold = screen.params?.hold_max_pct ?? 0.2;
  const held = new Set(pf.open.map((i) => i.pos.symbol));
  const parts = [html`<h1>Portfolio Intelligence</h1>
    <p class="lede">Ein Signal für jede gehaltene Aktie. Das Verkaufssignal der App (oben rechts) ist getrennt von deiner eigenen Haltedauer (eigener Kasten).</p>
    <p class="small muted">Datenstand ${fmtDate(screen.asof)} (${fr.label}), Methodik v${screen.methodology_version}${snap ? `, letztes gespeichertes Screening ${fmtDate(snap.createdAt.slice(0, 10))}` : ''}.</p>`];
  if (screen.demo) parts.push(html`<div class="demo-banner">DEMO-DATEN – Signale sind nur ein Funktionstest</div>`);
  if (!pf.open.length) {
    parts.push(empty('Keine Positionen im Depot', 'Erfasse deine Aktien unter Depot. Danach erscheinen hier Halte-, Kauf- und Verkaufssignale.', html`<a class="btn" href="#/depot">Zum Depot</a>`));
  }
  for (const s of sigs) {
    const it = pf.open.find((i) => i.pos.id === s.positionId);
    const row = screen.bySymbol.get(s.symbol);
    const tax = s.signal === 'VERKAUF' || s.signal === 'VERKAUF PRÜFEN' ? estimateSaleTax(it.unreal, state.settings) : null;
    parts.push(html`<section class="panel">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
        <div style="min-width:0"><h3 style="font-size:17px">${s.name}</h3><div class="xs muted">${s.symbol}${row?.rank ? `, Rang ${row.rank} (${fmtRankPct(row.pct)})` : ''}</div></div>
        <div style="text-align:right">${badge(s.signal)}<div class="xs muted" style="margin-top:4px">Dringlichkeit: ${s.urgency}</div></div>
      </div>
      ${(() => { const h = it ? holdStatus(it.pos, it, todayISO()) : null; return h ? html`<div class="note ${h.state === 'verkaufen' ? 'error' : h.state === 'warten' ? 'warn' : 'info'}" style="margin:10px 0"><div><b>Deine Haltedauer (${h.months} Monate):</b> ${h.text}</div></div>` : ''; })()}
      ${row?.Z != null ? html`<div style="margin:10px 0 4px">${holdBand(row.pct, { holdMax: hold, prevPct: row.prev_pct })}</div>` : ''}
      <h3 style="margin-top:12px">Begründung</h3>
      <ul style="margin:0 0 8px;padding-left:18px">${s.reasons.map((r) => html`<li style="margin-bottom:4px">${r}</li>`)}</ul>
      <details class="more" ${s.signal.startsWith('VERKAUF') ? 'open' : ''}><summary>Kriterien (${s.criteria.filter((c) => c.ok === true).length} von ${s.criteria.length} erfüllt)</summary>
        <ul class="crit-list">${s.criteria.map((c) => html`<li><span class="${c.ok === true ? 'ok' : c.ok === false ? (c.info ? 'na' : 'no') : 'na'}">${c.ok === true ? '✓' : c.ok === false ? '×' : '–'}</span><span>${c.label}${c.info ? html` <span class="xs muted">(Hinweis)</span>` : ''}${c.value ? html`<span class="v">${c.value}</span>` : ''}</span></li>`)}</ul>
      </details>
      <dl class="kv small" style="margin-top:8px">
        <dt>Datenstand</dt><dd>${fmtDate(row?.last_date || screen.asof)}</dd>
        <dt>Depotanteil</dt><dd>${fmtPct(it?.weight, 1, false)}</dd>
        <dt>Gewinn/Verlust</dt><dd>${fmtEUR(it?.unreal, 0)} (${fmtPct(it?.unrealPct)})</dd>
        ${tax != null ? html`<dt>Geschätzte Steuer bei Verkauf</dt><dd>${fmtEUR(tax, 0)}</dd>` : ''}
      </dl>
      <p class="small" style="margin:10px 0 0"><b>Bei der nächsten Überprüfung:</b> ${s.next}</p>
      ${s.plan ? html`<hr class="sep"><div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><h3 style="margin:0">Sparplan</h3>${badge(s.plan.signal)}</div>
        <ul style="margin:8px 0 0;padding-left:18px">${s.plan.reasons.map((r) => html`<li style="margin-bottom:4px">${r}</li>`)}</ul>
        ${s.plan.switchTo ? html`<p class="small" style="margin:8px 0 0"><a href="#/aktie/${encodeURIComponent(s.plan.switchTo.symbol)}">Wechselkandidat ansehen: ${s.plan.switchTo.name}</a></p>` : ''}` : ''}
    </section>`);
  }
  // Sparplan-Kandidaten
  const tp = screen.top_pick ? screen.bySymbol.get(screen.top_pick) : null;
  const alts = screen.candidates.filter((c) => !held.has(c)).slice(0, 5).map((c) => screen.bySymbol.get(c));
  parts.push(html`<h2>Sparplan-Kandidat für neue Raten</h2>`);
  if (!fr.ok || screen.status === 'fehler') parts.push(note('warn', 'Ohne aktuelle Daten gibt es keine Empfehlung für neue Raten.'));
  else if (tp) parts.push(html`<a class="toppick" href="#/aktie/${encodeURIComponent(tp.symbol)}" style="display:block;color:inherit"><div class="label">Top Pick</div><div class="name" style="font-size:20px">${tp.name}</div>
    <p class="small" style="margin:4px 0 0;color:var(--ink-2)">Neue Sparraten folgen dem aktuellen Ranking. Bestehende Positionen folgen den Halteregeln und werden nicht für einen Wechsel verkauft. Das spart Kosten und Steuern.</p></a>`);
  else parts.push(note('info', 'Kein Top Pick. Ohne Top Pick ist eine Verteilung auf die Top-10-Kandidaten möglich, oder die Rate wird pausiert.'));
  if (alts.length && fr.ok) {
    parts.push(html`<h3>Weitere Wechselkandidaten</h3><div class="group">${alts.map((r) => html`<a class="row" href="#/aktie/${encodeURIComponent(r.symbol)}">
      <div class="grow"><div class="title">${r.rank}. ${r.name}</div><div class="sub">${r.symbol}, 12 Monate ${fmtPct(r.m12)}</div></div>${badge(r.symbol === screen.top_pick ? 'TOP PICK' : 'KAUF-KANDIDAT')}</a>`)}</div>`);
  }
  const alt = bestAlternative(screen, held);
  void alt;
  parts.push(html`<h2>So entstehen die Signale</h2><div class="panel small">
    <p><b>VERKAUF</b> nur, wenn die Aktie an zwei Monatsenden in Folge außerhalb der besten ${Math.round(hold * 100)} % liegt oder ihr 12-Monats-Momentum nicht mehr positiv ist. Sofort, wenn sie unter den Median fällt oder das 12-Monats-Momentum unter −10 % liegt.</p>
    <p><b>VERKAUF PRÜFEN</b> erscheint beim ersten Auftreten dieser Bedingung oder bei auffälligen Daten.</p>
    <p><b>NACHKAUFEN</b> erscheint, wenn die Aktie zu den aktuellen Top 10 gehört und höchstens ${Math.round((state.settings.maxWeight || 0.2) * 100)} % des Depots ausmacht.</p>
    <p><b>SPARPLAN FORTSETZEN</b>, solange die Aktie zu den besten ${Math.round((screen.params?.savings_max_pct ?? 0.05) * 100)} % gehört. Sonst <b>SPARPLAN STOPPEN</b>: Die Position wird weiter gehalten, nur neues Geld wechselt.</p>
    <p style="margin:0" class="muted">Diese Regeln wurden vor dem Backtest festgelegt und werden nicht laufend angepasst. Momentum Lab ist keine Anlageberatung.</p></div>`);
  root.innerHTML = parts.join('');
}

import { cachedStatus, freshness, loadScreen, loadStage2, loadStatus } from '../data.js';
import { stage2Usable } from '../stage2.js';
import { computePortfolio } from '../depot.js';
import { cls, fmtDate, fmtDateTime, fmtEUR, fmtNum, fmtPct, fmtRankPct } from '../fmt.js';
import { latestScreening, state } from '../state.js';
import { getSetting } from '../store.js';
import { badge, chevron, holdBand, html, note } from '../ui.js';
import { urgencyRank } from '../signals.js';

export async function render(root) {
  const [status, snap, lastBackup, changes] = await Promise.all([
    cachedStatus() ? Promise.resolve(cachedStatus()) : loadStatus().catch(() => null),
    latestScreening(), getSetting('lastBackupAt', null), getSetting('changesSinceBackup', 0),
  ]);
  let screen = null;
  try { screen = await loadScreen(); } catch { /* Depot ohne Kurse */ }
  const pf = computePortfolio(state.positions, state.txs, screen);
  const fr = freshness(status?.asof);
  const parts = [];
  if (status?.demo) parts.push(html`<div class="demo-banner">DEMO-DATEN: Kurse und Unternehmen sind erfunden. Die App läuft noch nicht mit echten Daten.</div>`);
  parts.push(html`<h1>Übersicht</h1>
    <p class="lede">${status?.asof ? `Datenstand ${fmtDate(status.asof)}, ${fr.label}` : 'Noch keine Daten vom Datenlauf.'}</p>`);
  if (status?.overall === 'fehler') parts.push(note('error', `Der letzte Datenlauf ist fehlgeschlagen. ${status.messages?.filter((m) => m.level === 'fehler').map((m) => m.text).join(' ') || ''}`));
  else if (status && !fr.ok) parts.push(note('warn', `Die Daten sind ${fr.label}. Empfehlungen werden erst mit aktuellen Daten wieder erzeugt.`));

  // Screening
  parts.push(html`<section class="panel">
    <h3>Screening</h3>
    <p class="muted small">${snap ? `Zuletzt am ${fmtDateTime(snap.createdAt)} mit Daten vom ${fmtDate(snap.asof)}: ${snap.candidates.length} Kandidaten.` : 'Noch kein Screening durchgeführt.'}</p>
    <button class="screen-btn" id="go-screen">SCREENING STARTEN</button>
  </section>`);

  // Top Pick
  const tpSym = screen?.top_pick || snap?.top_pick;
  const tp = tpSym && screen ? screen.bySymbol.get(tpSym) : null;
  if (tp) {
    parts.push(html`<a class="toppick" href="#/aktie/${encodeURIComponent(tp.symbol)}" style="display:block;color:inherit">
      <div class="label">Top Pick</div>
      <div class="name">${tp.name}</div>
      <div class="chips" style="margin-bottom:10px"><span class="chip">${tp.symbol}</span><span class="chip">${tp.country}</span><span class="chip">${tp.sector}</span></div>
      <div class="grid2" style="margin-bottom:8px">
        <div><div class="muted xs">12 Monate (ohne letzten)</div><div class="num ${cls(tp.m12)}" style="font-weight:700">${fmtPct(tp.m12)}</div></div>
        <div><div class="muted xs">Score / Rang</div><div class="num" style="font-weight:700">${fmtNum(tp.Z, 2)} (${fmtRankPct(tp.pct)})</div></div>
      </div>
      ${holdBand(tp.pct, { holdMax: screen.params?.hold_max_pct ?? 0.2, label: false })}
    </a>`);
  } else if (screen && screen.candidates?.length === 0) {
    parts.push(note('info', 'Aktuell erfüllt keine Aktie alle Kriterien. Die App empfiehlt deshalb nichts.'));
  }

  // Stage 2 (finale Rangfolge)
  let s2 = null;
  try { s2 = await loadStage2(); } catch { s2 = null; }
  if (screen && s2 && s2.ranking?.length) {
    const use = stage2Usable(s2, screen, freshness(screen.asof));
    parts.push(html`<a class="panel" href="#/top10/final" style="display:block;color:inherit">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><h3 style="margin:0">Stage 2: Top 5 zum Kaufen</h3>${chevron}</div>
      <p class="small muted" style="margin:6px 0 8px">${use.ok ? 'Die Top-10-Kandidaten, sortiert nach der Chance, dass das Momentum weiterläuft.' : use.reason}</p>
      ${(use.ok ? s2.ranking.slice(0, 5) : []).map((r) => html`<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:6px 0;border-top:1px solid var(--line-soft)">
        <div class="small" style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.stage2?.rank ?? '–'}. ${r.name} <span class="muted">${r.stage2?.score_display != null ? fmtNum(r.stage2.score_display, 1) : ''}</span></div>
        <div></div></div>`)}
    </a>`);
  }

  // Depot
  const t = pf.totals;
  parts.push(html`<h2>Depot</h2>`);
  if (!state.positions.length) {
    parts.push(html`<div class="panel"><p class="muted">Noch keine Positionen erfasst.</p><a class="btn block" href="#/depot">Erste Position erfassen</a></div>`);
  } else {
    parts.push(html`<div class="grid2" style="margin-bottom:14px">
      <div class="stat"><div class="l">Marktwert</div><div class="v">${fmtEUR(t.mv, 0)}</div></div>
      <div class="stat"><div class="l">Unrealisiert</div><div class="v ${cls(t.unreal)}">${fmtPct(t.unrealPct)}</div><div class="xs muted">${fmtEUR(t.unreal, 0)}</div></div>
      <div class="stat"><div class="l">Gesamtrendite</div><div class="v ${cls(t.totalReturn)}">${fmtPct(t.totalReturnPct)}</div><div class="xs muted">inkl. realisiert und Dividenden</div></div>
      <div class="stat"><div class="l">Positionen</div><div class="v">${t.positions}</div><div class="xs muted">${t.missingPrices ? `${t.missingPrices} ohne Kurs` : 'alle mit Kurs'}</div></div>
    </div>`);
  }

  // Signale
  if (snap?.signals?.length) {
    const urgent = snap.signals.filter((s) => ['VERKAUF', 'VERKAUF PRÜFEN'].includes(s.signal) || s.plan?.signal === 'SPARPLAN STOPPEN')
      .sort((a, b) => urgencyRank(a.urgency) - urgencyRank(b.urgency));
    parts.push(html`<h2>Portfolio Intelligence</h2>
      <div class="group">${urgent.length ? urgent.map((s) => html`<a class="row" href="#/signale">
        <div class="grow"><div class="title">${s.name}</div><div class="sub">${s.reasons?.[0] || ''}</div></div>
        <div class="end">${badge(s.signal)}${s.plan?.signal === 'SPARPLAN STOPPEN' ? html`<div style="margin-top:4px">${badge('SPARPLAN STOPPEN')}</div>` : ''}</div></a>`)
        : html`<a class="row" href="#/signale"><div class="grow"><div class="title">Keine dringenden Signale</div><div class="sub">Stand ${fmtDate(snap.asof)}. Alle Positionen im Halteband oder ohne Handlungsbedarf.</div></div>${chevron}</a>`}
      </div>`);
  }

  // Markt
  const mk = screen?.market;
  if (mk?.proxy) {
    parts.push(html`<h2>Marktumfeld</h2><div class="panel"><dl class="kv">
      <dt>${mk.name}</dt><dd>${mk.above_ma200 ? 'über' : 'unter'} 200-Tage-Linie (${fmtPct(mk.dist_ma200)})</dd>
      <dt>Abstand zum Hoch</dt><dd>${fmtPct(mk.dd_from_high)}</dd>
      <dt>12 / 24 Monate</dt><dd>${fmtPct(mk.ret_12m)} / ${fmtPct(mk.ret_24m)}</dd>
      <dt>Aktien über 200-Tage-Linie</dt><dd>${fmtPct(mk.breadth_above_ma200, 0, false)}</dd>
      <dt>Momentum-Crash-Risiko</dt><dd>${mk.bear_state ? 'erhöht' : 'normal'}</dd>
      <dt>Volatilitätsschock (MSCI-Regel)</dt><dd>${mk.vol_shock ? 'ausgelöst' : 'nein'}</dd>
    </dl>${mk.bear_state ? html`<p class="small muted" style="margin-top:10px">Nach Phasen mit negativer 24-Monats-Rendite des Marktes kam es historisch öfter zu starken Momentum-Einbrüchen, wenn der Markt plötzlich drehte. Das ist ein Hinweis, kein Handelssignal.</p>` : ''}</div>`);
  }

  // Backup-Erinnerung
  const days = lastBackup ? (Date.now() - new Date(lastBackup)) / 86400000 : Infinity;
  if (state.positions.length && (days > (state.settings?.backupReminderDays || 14) || changes > 20)) {
    parts.push(note('warn', html`${lastBackup ? `Letztes Backup vor ${Math.floor(days)} Tagen` : 'Noch kein Backup erstellt'}${changes ? `, seitdem ${changes} Änderungen` : ''}. <a href="#/einstellungen">Jetzt sichern</a>`));
  }

  parts.push(html`<h2>Mehr</h2><div class="group">
    <a class="row" href="#/backtest"><div class="grow"><div class="title">Backtesting</div><div class="sub">Strategievarianten im historischen Test</div></div>${chevron}</a>
    <a class="row" href="#/einstellungen"><div class="grow"><div class="title">Einstellungen und Datenquellen</div><div class="sub">Datenstatus, Methodik, Backup</div></div>${chevron}</a>
  </div>
  <p class="xs muted">Momentum Lab ist ein privates Analysewerkzeug und keine Anlageberatung. Alle Signale folgen festen, dokumentierten Regeln.</p>`);
  root.innerHTML = parts.join('');
  root.querySelector('#go-screen').onclick = () => { sessionStorage.setItem('autorun', '1'); location.hash = '#/screening'; };
}

import { fundamentals, riskFlags } from '../analysis.js';
import { whySelected } from '../analysis.js';
import { freshness, loadDetail, loadScreen, loadStage2 } from '../data.js';
import { computePortfolio } from '../depot.js';
import { cls, fmtDate, fmtNum, fmtPct, fmtRankPct } from '../fmt.js';
import { computeSignals } from '../screening.js';
import { CAT_ORDER, decisionBadge, dqBadge, outBadge, profile, riskBadge, scoreScale, stage2Usable } from '../stage2.js';
import { latestScreening, state } from '../state.js';
import { getSetting, setSetting } from '../store.js';
import { badge, empty, holdBand, html, note } from '../ui.js';

export async function render(root, mode) {
  let screen;
  try { screen = await loadScreen(); } catch (e) {
    root.innerHTML = String(html`<h1>Top 10</h1>${note('error', e.message)}`);
    return;
  }
  let s2 = null;
  try { s2 = await loadStage2(); } catch { s2 = null; }
  const fr = freshness(screen.asof);
  if (mode) await setSetting('top10View', mode);
  const view = mode || (await getSetting('top10View', null)) || (s2 && s2.status !== 'fehler' ? 'final' : 'stage1');
  const parts = [html`<h1>Top 10</h1>`];
  if (screen.demo) parts.push(html`<div class="demo-banner">DEMO-DATEN – erfundene Unternehmen, keine echten Signale</div>`);
  parts.push(html`<div class="seg" role="group" aria-label="Ansicht">
    <a class="seg-link" href="#/top10/final" aria-pressed="${view === 'final'}">Finale Rangfolge</a>
    <a class="seg-link" href="#/top10/stage1" aria-pressed="${view !== 'final'}">Stage 1 (Momentum)</a></div>`);
  if (view === 'final') parts.push(...finalParts(screen, s2, fr));
  else parts.push(...(await stage1Parts(screen, s2, fr)));
  root.innerHTML = parts.join('');
}

// ---------------------------------------------------------------- Finale Rangfolge (Stage 2)
function finalParts(screen, s2, fr) {
  const parts = [];
  const use = stage2Usable(s2, screen, fr);
  if (!s2) {
    parts.push(note('info', 'Stage 2 wird beim nächsten nächtlichen Datenlauf zum ersten Mal berechnet. Bis dahin gilt die Stage-1-Liste.'));
    return parts;
  }
  for (const m of (s2.messages || []).filter((x) => x.level !== 'info')) parts.push(note(m.level === 'fehler' ? 'error' : 'warn', m.text));
  const infos = (s2.messages || []).filter((x) => x.level === 'info');
  if (infos.length) parts.push(html`<details class="more"><summary>Hinweise zur Datenbasis (${infos.length})</summary>${infos.map((m) => html`<p class="small muted">${m.text}</p>`)}</details>`);
  if (!use.ok && s2.status !== 'fehler') parts.push(note('warn', use.reason));
  if (!s2.ranking.length) {
    parts.push(empty('Keine Kandidaten für Stage 2', 'Stage 1 hat heute keine Aktie ausgewählt. Ohne Kandidaten gibt es auch keine Stage-2-Bewertung.'));
    return parts;
  }
  const m = s2.market || {};
  const elig = use.ok ? s2.eligible.length : null;
  parts.push(html`<div class="panel">
    <div class="s2-meta" style="margin-top:0">
      <div><div class="muted xs">Für einen neuen Sparplan freigegeben</div>
        <div class="s2-score">${elig ?? '–'}<span class="small muted" style="font-weight:500"> von ${s2.ranking.length} Kandidaten</span></div></div>
      <div class="xs muted" style="text-align:right">Stage 2 v${s2.stage2_version}<br>Stand ${fmtDate(s2.asof)}</div></div>
    <p class="small" style="margin:8px 0 6px;color:var(--ink-2)">Sortiert nach Stage-2-Score (0 bis 10). Er prüft, ob die Stärke aus Stage 1 durch mehrere unabhängige Faktoren gestützt wird: Persistenz, Gewinnrevisionen, relative Stärke, Trend, Qualität, Bewertung und Überhitzung.</p>
    ${use.ok && elig === 0 ? html`<p class="small" style="margin:0 0 6px">Derzeit erfüllt keine Aktie die Bedingungen für einen neuen Sparplan. Das ist ein gültiges Ergebnis.</p>` : ''}
    <p class="xs muted" style="margin:0">Vergleich MSCI World (${m.name || 'EUNL'}): 3 Monate ${fmtPct(m.ret_3m)}, 6 Monate ${fmtPct(m.ret_6m)}, 12 Monate ${fmtPct(m.ret_12m)}.</p></div>`);
  for (const r of s2.ranking) {
    const sc = r.stage2?.score_display;
    const missing = CAT_ORDER.filter((c) => r.categories?.[c] && !r.categories[c].available).map((c) => r.categories[c].short);
    parts.push(html`<a class="panel" href="#/aktie/${encodeURIComponent(r.symbol)}" style="display:block;color:inherit">
      <div class="s2-head">
        <div class="s2-rank">${r.stage2?.rank ?? '–'}</div>
        <div style="flex:1;min-width:0"><div class="title" style="font-weight:650">${r.name}</div>
          <div class="chips" style="margin:5px 0 0"><span class="chip">${r.symbol}</span><span class="chip">Stage 1: Rang ${r.stage1?.rank ?? '–'}, Score ${fmtNum(r.stage1?.score, 2)}</span>${r.stage1?.top_pick ? html`<span class="chip" style="color:var(--brass-ink)">Top Pick</span>` : ''}</div></div>
        <div>${use.ok ? decisionBadge(r.decision?.code) : badge('KEINE BEWERTUNG')}</div>
      </div>
      <div class="s2-meta"><div><div class="muted xs">Stage-2-Score</div><div class="s2-score">${sc != null ? fmtNum(sc, 1) : '–'}</div></div>${profile(r.categories)}</div>
      ${scoreScale(r.stage2?.score, { label: false })}
      <div class="chips" style="margin-top:8px">${outBadge(r.outperformance?.level)}${riskBadge(r.risk?.level)}${dqBadge(r.data_quality?.level)}</div>
      ${missing.length && sc != null ? html`<p class="xs" style="margin:8px 0 0;color:var(--warn)">Ohne ${missing.join(', ')} berechnet (fehlende Daten, Gewichte neu normiert).</p>` : ''}
      <p class="small muted" style="margin:8px 0 0">${r.texts?.vs_next || ''}</p>
    </a>`);
  }
  parts.push(html`<details class="more"><summary>Als Tabelle anzeigen</summary><div class="table-wrap"><table><thead><tr>
    <th class="n">Rang</th><th class="sticky">Aktie</th><th class="n">Stage 1</th><th class="n">Stage 2</th><th>Outperformance</th><th>Risiko</th><th>Entscheidung</th></tr></thead><tbody>
    ${s2.ranking.map((r) => html`<tr><td class="n">${r.stage2?.rank ?? '–'}</td><td class="sticky">${r.name}</td><td class="n">${r.stage1?.rank ?? '–'}</td>
      <td class="n">${r.stage2?.score_display != null ? fmtNum(r.stage2.score_display, 1) : '–'}</td><td>${r.outperformance?.level || '–'}</td>
      <td>${r.risk?.level || '–'}</td><td>${use.ok ? r.decision?.label || '–' : '–'}</td></tr>`)}
    </tbody></table></div></details>`);
  parts.push(html`<p class="xs muted">Schwellen: ab 9,0 EXCEPTIONAL, ab 8,5 STRONG BUY CANDIDATE, ab 7,5 WATCHLIST, ab 6,0 NO ENTRY, darunter REJECT. HARD RISK (Risiko CRITICAL) blockiert jede Freigabe. Die Schwellen sind Heuristiken und noch nicht durch einen Backtest belegt. Keine Anlageberatung.</p>`);
  return parts;
}

// ---------------------------------------------------------------- Stage-1-Liste (unverändert, plus Stage-2-Zeile)
async function stage1Parts(screen, s2, fr) {
  const snap = await latestScreening();
  const pf = computePortfolio(state.positions, state.txs, screen);
  const sigs = computeSignals(screen, null, pf, state.plans, state.settings);
  const heldSig = new Map(sigs.map((s) => [s.symbol, s]));
  const details = {};
  await Promise.all(screen.candidates.map(async (s) => { try { details[s] = await loadDetail(s); } catch { details[s] = null; } }));
  const use = stage2Usable(s2, screen, fr);
  const parts = [html`<p class="lede">Höchstens zehn Aktien, die alle Regeln erfüllen. Datenstand ${fmtDate(screen.asof)} (${fr.label}), Methodik v${screen.methodology_version}.${snap ? '' : ' Tipp: Starte ein Screening, damit das Ergebnis mit deinem Depot gespeichert wird.'}</p>`];
  if (!fr.ok || screen.status === 'fehler') parts.push(note('error', `Die Daten sind ${screen.status === 'fehler' ? 'fehlerhaft' : fr.label}. Diese Liste ist keine aktuelle Empfehlung.`));
  else if (screen.status === 'warnung') parts.push(note('warn', 'Der Datenlauf hat Warnungen gemeldet. Details stehen unter Einstellungen > Datenquellen.'));

  if (!screen.candidates.length) {
    parts.push(empty('Keine Aktie erfüllt alle Kriterien', 'Das ist eine bewusste Entscheidung des Systems und kein Fehler. Die Liste wird nie mit schwachen Kandidaten aufgefüllt. Häufige Ursache: Im Markt fehlt positives Momentum.'));
    return parts;
  }
  if (screen.market?.bear_state) parts.push(note('warn', 'Marktphase: Der Gesamtmarkt liegt über 24 Monate im Minus. Nach solchen Phasen kam es historisch öfter zu Momentum-Crashs, wenn der Markt plötzlich drehte (Daniel & Moskowitz 2016). Das betrifft alle Kandidaten.'));
  if (screen.market?.vol_shock) parts.push(note('warn', 'Volatilitätsschock am Gesamtmarkt: MSCI würde jetzt ad hoc nur mit 6-Monats-Momentum neu gewichten.'));
  const hold = screen.params?.hold_max_pct ?? 0.2;
  const tp = screen.top_pick ? screen.bySymbol.get(screen.top_pick) : null;
  if (tp) {
    const why = whySelected(tp, screen);
    const s2tp = s2?.bySymbol?.get(tp.symbol);
    parts.push(html`<a class="toppick" href="#/aktie/${encodeURIComponent(tp.symbol)}" style="display:block;color:inherit">
      <div class="label">Top Pick, Rang ${tp.rank}</div>
      <div class="name">${tp.name}</div>
      <div class="chips" style="margin:6px 0 12px"><span class="chip">${tp.symbol}</span><span class="chip">${tp.country}</span><span class="chip">${tp.sector}</span>${heldSig.has(tp.symbol) ? badge(heldSig.get(tp.symbol).signal) : badge('TOP PICK')}</div>
      <dl class="kv"><dt>Score</dt><dd>${fmtNum(tp.Z, 2)} (${fmtRankPct(tp.pct)})</dd>
        <dt>12 / 6 Monate (ohne letzten)</dt><dd><span class="${cls(tp.m12)}">${fmtPct(tp.m12)}</span> / <span class="${cls(tp.m6)}">${fmtPct(tp.m6)}</span></dd>
        <dt>Volatilität</dt><dd>${fmtPct(tp.vol, 0, false)} p. a.</dd>
        ${s2tp ? html`<dt>Stage 2</dt><dd>${s2tp.stage2?.score_display != null ? fmtNum(s2tp.stage2.score_display, 1) : '–'} ${use.ok ? decisionBadge(s2tp.decision?.code) : ''}</dd>` : ''}</dl>
      <div style="margin-top:12px">${holdBand(tp.pct, { holdMax: hold })}</div>
      <p class="small" style="margin:12px 0 0;color:var(--ink-2)">${why[0]} Zusätzlich erfüllt: beide Teilscores mindestens 1, Volatilität nicht im obersten Zehntel, Kurs gegengeprüft.</p>
    </a>`);
  } else {
    parts.push(note('info', 'Kein Top Pick: Keiner der Kandidaten erfüllt zusätzlich alle Robustheitsregeln (beide Teilscores ≥ 1, Volatilität nicht extrem, Kurs gegengeprüft). Die Kandidaten unten bleiben gültig.'));
  }
  parts.push(html`<h2>Kandidaten</h2>`);
  for (const sym of screen.candidates) {
    const r = screen.bySymbol.get(sym);
    const d = details[sym];
    const fm = fundamentals(d);
    const flags = riskFlags(r, d, screen, { isCandidate: true, market: false });
    const serious = flags.filter((f) => f.level !== 'info');
    const held = heldSig.get(sym);
    const sig = held ? held.signal : sym === screen.top_pick ? 'TOP PICK' : 'KAUF-KANDIDAT';
    const isNew = screen.prev_candidates && !screen.prev_candidates.includes(sym);
    const e2 = s2?.bySymbol?.get(sym);
    parts.push(html`<a class="panel" href="#/aktie/${encodeURIComponent(sym)}" style="display:block;color:inherit">
      <div style="display:flex;gap:10px;align-items:flex-start">
        <div style="font-family:var(--display);font-size:22px;font-weight:750;min-width:28px;color:${sym === screen.top_pick ? 'var(--brass)' : 'var(--ink-2)'}">${r.rank}</div>
        <div style="flex:1;min-width:0">
          <div class="title" style="font-weight:650">${r.name}</div>
          <div class="chips" style="margin:5px 0 8px"><span class="chip">${sym}</span><span class="chip">${r.country}</span><span class="chip">${r.sector}</span>${isNew ? html`<span class="chip" style="color:var(--ice)">neu</span>` : ''}</div>
        </div>
        <div>${badge(sig)}</div>
      </div>
      <dl class="kv small">
        <dt>Momentum-Score</dt><dd>${fmtNum(r.Z, 2)} (${fmtRankPct(r.pct)})</dd>
        <dt>Performance 6 / 12 Monate</dt><dd><span class="${cls(r.ret_6m)}">${fmtPct(r.ret_6m)}</span> / <span class="${cls(r.ret_12m)}">${fmtPct(r.ret_12m)}</span></dd>
        <dt>Risiko (Volatilität)</dt><dd>${fmtPct(r.vol, 0, false)} p. a.</dd>
        <dt>Trend</dt><dd>${r.above_ma200 === true ? 'über 200-Tage-Linie' : r.above_ma200 === false ? 'unter 200-Tage-Linie' : 'n. v.'}</dd>
        <dt>Datenqualität</dt><dd>${r.verified === true ? 'gegengeprüft' : r.verified === false ? 'Abweichung!' : 'geprüft, ohne Zweitquelle'}</dd>
        <dt>Bewertung (KGV)</dt><dd>${fm && Number.isFinite(fm.metrics.pe) ? fmtNum(fm.metrics.pe, 1) : 'n. v.'}</dd>
        ${e2 ? html`<dt>Stage 2</dt><dd>Rang ${e2.stage2?.rank ?? '–'}, Score ${e2.stage2?.score_display != null ? fmtNum(e2.stage2.score_display, 1) : '–'}</dd>` : ''}
      </dl>
      ${e2 && use.ok ? html`<div class="chips" style="margin-top:8px">${decisionBadge(e2.decision?.code)}${riskBadge(e2.risk?.level)}</div>` : ''}
      <p class="small" style="margin:10px 0 4px;color:var(--ink-2)">Warum ausgewählt: ${r.rank <= 3 ? 'Spitzenreiter' : 'Unter den Besten'} beim risikoadjustierten Momentum, 12-Monats-Momentum ${fmtPct(r.m12)}, alle Qualitätsregeln erfüllt.</p>
      <p class="small" style="margin:0;color:${serious.length ? 'var(--serious)' : 'var(--ink-3)'}">${serious.length ? `Risiken: ${serious.map((f) => f.text).slice(0, 2).join(' ')}` : 'Keine besonderen Risikohinweise.'}</p>
      <p class="xs muted" style="margin:6px 0 0">Screening-Datum ${fmtDate(screen.asof)}</p>
    </a>`);
  }
  parts.push(html`<p class="xs muted">Die Halteregeln für gekaufte Aktien sind lockerer als die Aufnahmeregeln. Eine Aktie, die aus den Top 10 fällt, wird nicht automatisch verkauft (siehe Signale).</p>`);
  return parts;
}

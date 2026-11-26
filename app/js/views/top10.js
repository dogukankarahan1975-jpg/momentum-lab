import { fundamentals, riskFlags } from '../analysis.js';
import { whySelected } from '../analysis.js';
import { freshness, loadDetail, loadScreen, loadStage2 } from '../data.js';
import { computePortfolio } from '../depot.js';
import { cls, fmtDate, fmtNum, fmtPct, fmtRankPct } from '../fmt.js';
import { computeSignals } from '../screening.js';
import { buyBadge, stage2Usable } from '../stage2.js';
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
    <a class="seg-link" href="#/top10/final" aria-pressed="${view === 'final'}">Stage 2 Rangfolge</a>
    <a class="seg-link" href="#/top10/stage1" aria-pressed="${view !== 'final'}">Stage 1 (Momentum)</a></div>`);
  if (view === 'final') parts.push(...finalParts(screen, s2, fr));
  else parts.push(...(await stage1Parts(screen, s2, fr)));
  root.innerHTML = parts.join('');
}

// ---------------------------------------------------------------- Stage 2: Fortsetzungs-Rangfolge
function finalParts(screen, s2, fr) {
  const parts = [];
  const use = stage2Usable(s2, screen, fr);
  if (!use.ok) parts.push(note(s2?.status === 'fehler' ? 'error' : 'info', use.reason));
  if (!s2 || !s2.schema || s2.schema < 2) return parts;
  for (const m of (s2.messages || [])) parts.push(html`<p class="xs muted">${m.text}</p>`);
  if (!s2.ranking.length) {
    parts.push(empty('Keine Kandidaten für Stage 2', 'Stage 1 hat heute keine Aktie ausgewählt.'));
    return parts;
  }
  parts.push(html`<div class="panel"><h3 style="margin-top:0">So liest du diese Liste</h3>
    <p class="small" style="margin:0">Das sind dieselben Top-10-Kandidaten wie in Stage 1, neu sortiert nach der Frage: <b>Bei welchen läuft das Momentum am ehesten weiter?</b> Gezählt werden gleichmäßiger Anstieg, Nähe zum 52-Wochen-Hoch, Stärke gegenüber dem Gesamtmarkt und – wenn vorhanden – steigende Gewinnschätzungen und Gewinnüberraschungen. Die <b>ersten 5</b> sind die Kaufkandidaten.</p></div>`);
  parts.push(html`<div class="group">${s2.ranking.map((r) => html`<a class="row" href="#/aktie/${encodeURIComponent(r.symbol)}" style="color:inherit">
      <div style="font-size:22px;font-weight:700;width:30px;text-align:center">${r.stage2?.rank ?? '–'}</div>
      <div class="grow"><div class="title">${r.name}</div><div class="sub">Stage 2 Score ${r.stage2?.score_display != null ? fmtNum(r.stage2.score_display, 1) : '–'}${r.stage2?.price_only ? ' (nur Kursteil)' : ''} · Stage 1: Platz ${r.stage1?.rank ?? '–'}, Score ${fmtNum(r.stage1?.score, 2)}</div>
        ${r.flags?.length ? html`<div class="xs" style="color:var(--brass-ink);white-space:normal">${r.flags[0]}</div>` : ''}</div>
      <div class="end">${use.ok ? buyBadge(r) : ''}</div></a>`)}</div>
    <p class="xs muted">Score 0–10: Durchschnitt der Signale im Vergleich zu allen ${s2.method?.peers ?? ''} Momentum-Aktien (10 = überall vorne). Kursteil und Gewinnteil zählen je zur Hälfte. Keine Anlageberatung.</p>`);
  return parts;
}

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
        ${s2tp && use.ok ? html`<dt>Stage 2</dt><dd>Platz ${s2tp.stage2?.rank ?? '–'}, Score ${s2tp.stage2?.score_display != null ? fmtNum(s2tp.stage2.score_display, 1) : '–'}</dd>` : ''}</dl>
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
        ${e2 && use.ok ? html`<dt>Stage 2</dt><dd>Platz ${e2.stage2?.rank ?? '–'}, Score ${e2.stage2?.score_display != null ? fmtNum(e2.stage2.score_display, 1) : '–'}</dd>` : ''}
      </dl>
      ${e2 && use.ok ? html`<div class="chips" style="margin-top:8px">${buyBadge(e2)}</div>` : ''}
      <p class="small" style="margin:10px 0 4px;color:var(--ink-2)">Warum ausgewählt: ${r.rank <= 3 ? 'Spitzenreiter' : 'Unter den Besten'} beim risikoadjustierten Momentum, 12-Monats-Momentum ${fmtPct(r.m12)}, alle Qualitätsregeln erfüllt.</p>
      <p class="small" style="margin:0;color:${serious.length ? 'var(--serious)' : 'var(--ink-3)'}">${serious.length ? `Risiken: ${serious.map((f) => f.text).slice(0, 2).join(' ')}` : 'Keine besonderen Risikohinweise.'}</p>
      <p class="xs muted" style="margin:6px 0 0">Screening-Datum ${fmtDate(screen.asof)}</p>
    </a>`);
  }
  parts.push(html`<p class="xs muted">Die Halteregeln für gekaufte Aktien sind lockerer als die Aufnahmeregeln. Eine Aktie, die aus den Top 10 fällt, wird nicht automatisch verkauft (siehe Signale).</p>`);
  return parts;
}

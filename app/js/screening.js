// Ablauf "SCREENING STARTEN": Stage 1 (11 Schritte), Stage 2 (8 Schritte), Depot (3 Schritte).
// Abbruch bei fehlenden/alten Daten. Stage 2 wird im nächtlichen Datenlauf berechnet; hier wird sie geprüft und gezeigt.
import { freshness, getUniverse, loadDetail, loadScreen, loadStage2, loadStatus, reasonText, rowWithSource } from './data.js';
import { computePortfolio } from './depot.js';
import { fmtDate, fmtDateTime, fmtPct, uid } from './fmt.js';
import { evaluateHolding } from './signals.js';
import { stage2Usable } from './stage2.js';
import { db } from './store.js';
import { isDataProblem, riskFlags } from './analysis.js';

export const STEP_GROUPS = { s1: 'Stage 1 – Momentum-Screening', s2: 'Stage 2 – Fortsetzungs-Rangfolge', depot: 'Depot und Speichern' };
export const STEP_DEFS = [
  ['data', 's1', 'Aktuellen Datenstand abrufen'], ['universe', 's1', 'Aktienuniversum laden'],
  ['scan', 's1', 'Alle Aktien untersuchen'], ['errors', 's1', 'Fehlerhafte Daten erkennen'],
  ['exclude', 's1', 'Ungeeignete Aktien ausschließen'], ['scores', 's1', 'Momentum-Scores berechnen'],
  ['risk', 's1', 'Fundamentale und Risiko-Prüfungen'], ['news', 's1', 'Unternehmensnachrichten berücksichtigen'],
  ['rank', 's1', 'Aktien ranken'], ['select', 's1', 'Maximal 10 Kandidaten auswählen'], ['top', 's1', 'Top-Kandidaten bestimmen'],
  ['s2handover', 's2', 'Top-10-Kandidaten an Stage 2 übergeben'], ['s2data', 's2', 'Analystendaten prüfen (Gewinnteil)'],
  ['s2factors', 's2', 'Fortsetzungs-Signale gegen alle Momentum-Aktien vergleichen'], ['s2rank', 's2', 'Rangfolge erstellen, Top 5 bestimmen'],
  ['depot', 'depot', 'Depotpositionen einbeziehen'], ['signals', 'depot', 'Empfehlungen für das Depot erzeugen'],
  ['save', 'depot', 'Screening mit Datum speichern'],
];
export const STEPS = STEP_DEFS.map(([, , label]) => label);
const I = Object.fromEntries(STEP_DEFS.map(([id], i) => [id, i]));
const count = (arr, fn) => arr.reduce((m, x) => { const k = fn(x) ?? '–'; m[k] = (m[k] || 0) + 1; return m; }, {});

export function bestAlternative(screen, heldSymbols) {
  const cand = [screen.top_pick, ...screen.candidates].filter(Boolean).find((s) => !heldSymbols.has(s));
  if (!cand) return null;
  const r = screen.bySymbol.get(cand);
  return { symbol: cand, name: r?.name || cand };
}

export function computeSignals(screen, status, pf, plans, settings) {
  const fr = freshness(screen.asof);
  const held = new Set(pf.open.map((i) => i.pos.symbol));
  const alt = bestAlternative(screen, held);
  const planBy = {};
  for (const p of plans) if (p.active !== false) planBy[p.positionId] = p;
  return pf.open.map((it) => {
    // Bewertung immer in der Liste, in der die Aktie steht (Rang im S&P 500 bzw. im ACWI)
    const { row, screen: src } = rowWithSource(screen, it.pos.symbol);
    const own = src === screen;
    const ev = evaluateHolding({
      row, fresh: own ? fr : freshness(src.asof),
      globalStatus: src.status === 'fehler' || (own && status?.overall === 'fehler') ? 'fehler' : src.status,
      inCandidates: src.candidates.includes(it.pos.symbol), topPick: src.top_pick, weight: it.weight,
      maxWeight: settings.maxWeight, plan: planBy[it.pos.id] || null, bestAlternative: own ? alt : bestAlternative(src, held),
      params: src.params, reasonLabel: (c) => reasonText(c, src),
    });
    return { positionId: it.pos.id, symbol: it.pos.symbol, name: it.pos.name, ...ev,
      unreal: it.unreal, mvEUR: it.mvEUR, weight: it.weight, asof: src.asof,
      uniKey: own ? screen.uniKey : src.uniKey };
  });
}

export async function runScreening({ positions, txs, plans, settings, onStep }) {
  const steps = STEP_DEFS.map(([id, group, label]) => ({ id, group, label, state: 'wait', detail: '' }));
  let cur = 0;
  const emit = () => onStep?.(steps.map((s) => ({ ...s })));
  const set = (i, state, detail = '') => { cur = i; steps[i] = { ...steps[i], state, detail }; emit(); };
  const stop = (i, detail) => { set(i, 'err', detail); for (let k = i + 1; k < steps.length; k++) steps[k].state = 'skip'; emit(); };
  try {
    set(I.data, 'run');
    const [status, screen] = await Promise.all([loadStatus(true).catch(() => null), loadScreen(true)]);
    const fr = freshness(screen.asof);
    const runStatus = status?.overall || screen.status;
    if (screen.status === 'fehler' || runStatus === 'fehler') {
      const m = (status?.messages || []).filter((x) => x.level === 'fehler').map((x) => x.text).join(' ');
      stop(I.data, `Der letzte Datenlauf meldet einen Fehler. ${m || ''} Es gibt keine Empfehlungen.`);
      return { error: 'Datenlauf fehlerhaft', steps };
    }
    if (fr.abort) {
      stop(I.data, `Der Datenstand (${fmtDate(screen.asof)}) ist ${fr.label}. Das Screening wurde abgebrochen, damit keine veralteten Empfehlungen entstehen.`);
      return { error: 'Daten zu alt', steps };
    }
    set(I.data, fr.level === 'aktuell' ? 'ok' : 'warn', `Schlusskurse vom ${fmtDate(screen.asof)} (${fr.label}), berechnet vom nächtlichen Datenlauf am ${fmtDateTime(screen.generated_at)}. Die App lädt dieses fertige Ergebnis; neue Kurse kommen werktags nach US-Börsenschluss (fertig gegen 23:45 Uhr deutscher Zeit).${screen.demo ? ' DEMO-DATEN' : ''}`);

    const u = screen.universe;
    set(I.universe, u.source?.startsWith('iShares') || screen.demo ? 'ok' : 'warn',
      `${u.size} Aktien, Quelle: ${u.source}${u.as_of ? ` (Stand ${u.as_of})` : ''}${u.emerging ? `, davon ${u.emerging} aus Schwellenländern` : ''}${u.tradable?.checked ? `. Nur in Deutschland handelbare Aktien (${u.tradable.removed} ohne Frankfurt-Notierung und ${u.tradable.removed_cn_a} China-A-Aktien ausgeschlossen)` : u.tradable?.note ? `. ${u.tradable.note}` : ''}${u.watchlist?.length ? `, dazu ${u.watchlist.length} aus der Beobachtungsliste` : ''}`);

    const analyzed = screen.rows.filter((r) => Number.isFinite(r.last_close)).length;
    set(I.scan, analyzed / Math.max(u.size, 1) > 0.8 ? 'ok' : 'warn', `${analyzed} Aktien mit Kursdaten untersucht, ${u.size - u.priced} ohne Kursdaten`);

    const probs = screen.rows.filter((r) => r.in_universe && isDataProblem(r));
    const byCode = {};
    for (const r of probs) for (const c of r.reasons) byCode[c] = (byCode[c] || 0) + 1;
    const top = Object.entries(byCode).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([c, n]) => `${reasonText(c, screen)}: ${n}`).join(', ');
    set(I.errors, probs.length > 0.1 * u.size ? 'warn' : 'ok', probs.length ? `${probs.length} Aktien mit Datenproblemen erkannt (${top})` : 'Keine Datenprobleme erkannt');

    const excl = screen.rows.filter((r) => r.in_universe && !r.eligible).length;
    set(I.exclude, 'ok', `${excl} Aktien ausgeschlossen, ${u.eligible} zulässig. Die Gründe stehen in der Liste unten.`);

    const ranked = screen.rows.filter((r) => Number.isInteger(r.rank)).length;
    if (!ranked) { stop(I.scores, 'Keine gültigen Scores in den Daten.'); return { error: 'Keine Scores', steps }; }
    set(I.scores, 'ok', `${ranked} risikoadjustierte Momentum-Scores (Methodik v${screen.methodology_version})`);

    set(I.risk, 'run');
    const details = {};
    await Promise.all(screen.candidates.map(async (s) => {
      try { details[s] = await loadDetail(s); } catch { details[s] = null; }
    }));
    let flagCount = 0;
    const flags = {};
    for (const s of screen.candidates) {
      flags[s] = riskFlags(screen.bySymbol.get(s), details[s], screen, { isCandidate: true, market: false });
      flagCount += flags[s].filter((x) => x.level !== 'info').length;
    }
    const missingFund = screen.candidates.filter((s) => !details[s]?.fund).length;
    set(I.risk, missingFund ? 'warn' : 'ok', `${flagCount} Risikohinweise bei den Kandidaten${missingFund ? `. Für ${missingFund} fehlen Fundamentaldaten` : ''}`);

    const newsN = screen.candidates.reduce((n, s) => n + (details[s]?.news?.length || 0) + (details[s]?.fund?.sec_filings?.filings?.length || 0), 0);
    set(I.news, newsN || screen.demo ? 'ok' : 'warn', newsN ? `${newsN} Meldungen geladen. Sie werden angezeigt, fließen aber nicht in den Score ein.` : 'Keine Meldungen verfügbar');

    set(I.rank, 'ok', 'Rangfolge nach risikoadjustiertem 6- und 12-Monats-Momentum');
    set(I.select, screen.candidates.length ? 'ok' : 'warn', screen.candidates.length
      ? `${screen.candidates.length} Kandidaten erfüllen alle Kriterien`
      : 'Keine Aktie erfüllt derzeit alle Kriterien. Die App empfiehlt deshalb nichts.');
    const tp = screen.top_pick ? screen.bySymbol.get(screen.top_pick) : null;
    set(I.top, tp ? 'ok' : 'warn', tp ? `Top Pick: ${tp.name} (${tp.symbol})` : 'Kein Top Pick. Kein Kandidat erfüllt alle zusätzlichen Robustheitsregeln.');

    // ---------------- Stage 2
    set(I.s2handover, 'run');
    let s2 = null;
    try { s2 = await loadStage2(true); } catch { s2 = null; }
    const use = stage2Usable(s2, screen, fr);
    const S2_IDS = ['s2data', 's2factors', 's2rank'];
    if (!use.ok || !s2.ranking.length) {
      set(I.s2handover, 'warn', !s2 ? 'Stage 2 wird beim nächsten nächtlichen Datenlauf zum ersten Mal berechnet.'
        : !s2.ranking?.length && s2.status !== 'fehler' ? 'Keine Stage-1-Kandidaten, deshalb keine Stage-2-Rangfolge.' : use.reason);
      for (const id of S2_IDS) steps[I[id]].state = 'skip';
      emit();
    } else {
      const R = s2.ranking;
      set(I.s2handover, 'ok', `${R.length} Kandidaten aus Stage 1 übergeben, Datenstand ${fmtDate(s2.asof)} (Stage 2 v${s2.stage2_version}).`);
      const po = R.filter((r) => r.stage2?.price_only).length;
      set(I.s2data, po ? 'warn' : 'ok', po ? `${R.length - po} mit aktuellen Analystendaten, ${po} nur mit Kursteil. Quelle: Yahoo Finance (inoffiziell).` : 'Alle Kandidaten mit aktuellen Analystendaten. Quelle: Yahoo Finance (inoffiziell).');
      set(I.s2factors, 'ok', `Gleichmäßiger Anstieg, Nähe zum 52-Wochen-Hoch, Stärke ggü. dem Markt, Gewinnschätzungen und Gewinnüberraschungen, verglichen mit ${s2.method?.peers ?? '–'} Momentum-Aktien.`);
      set(I.s2rank, 'ok', `Top 5: ${R.filter((r) => r.buy).map((r) => r.name).join(', ')}`);
    }

    // ---------------- Depot
    const pf = computePortfolio(positions, txs, screen);
    const matched = pf.open.filter((i) => rowWithSource(screen, i.pos.symbol).row?.last_close != null).length;
    const fromOther = pf.open.filter((i) => !screen.bySymbol.get(i.pos.symbol) && screen.other?.bySymbol?.get(i.pos.symbol)).length;
    set(I.depot, pf.open.length === 0 ? 'ok' : matched === pf.open.length ? 'ok' : 'warn',
      pf.open.length ? `${pf.open.length} Positionen, ${matched} davon mit aktuellen Daten${fromOther ? ` (${fromOther} aus dem anderen Screening bewertet)` : ''}` : 'Noch keine Depotpositionen erfasst');

    const signals = computeSignals(screen, status, pf, plans, settings);
    const cnt = {};
    for (const s of signals) { cnt[s.signal] = (cnt[s.signal] || 0) + 1; if (s.plan) cnt[s.plan.signal] = (cnt[s.plan.signal] || 0) + 1; }
    set(I.signals, 'ok', signals.length ? Object.entries(cnt).map(([k, v]) => `${v}× ${k}`).join(', ') : 'Keine Positionen zu bewerten');

    const snapshot = {
      id: uid(), createdAt: new Date().toISOString(), asof: screen.asof, generated_at: screen.generated_at, uniKey: getUniverse(),
      methodology_version: screen.methodology_version, params_hash: screen.params_hash, pipeline_version: screen.pipeline_version,
      status: screen.status, freshness: fr, demo: !!screen.demo, top_pick: screen.top_pick,
      candidates: screen.candidates.map((s) => {
        const r = screen.bySymbol.get(s);
        return { symbol: s, name: r.name, rank: r.rank, Z: r.Z, pct: r.pct, m6: r.m6, m12: r.m12, vol: r.vol, sector: r.sector,
          country: r.country, flags: (flags[s] || []).map((x) => x.text) };
      }),
      stage2: s2 && use.ok ? {
        asof: s2.asof, version: s2.stage2_version, usable: use.ok, top5: s2.buy || [],
        ranking: s2.ranking.map((r) => ({ symbol: r.symbol, name: r.name, rank: r.stage2?.rank, score: r.stage2?.score_display, buy: !!r.buy })),
      } : null,
      signals: signals.map((s) => ({ positionId: s.positionId, symbol: s.symbol, name: s.name, signal: s.signal, urgency: s.urgency,
        reasons: s.reasons, next: s.next, plan: s.plan ? { signal: s.plan.signal, reasons: s.plan.reasons, switchTo: s.plan.switchTo } : null })),
      market: screen.market, universe: screen.universe,
      steps: steps.map((s) => ({ label: s.label, group: s.group, state: s.state, detail: s.detail })),
      depot: { value: pf.totals.mv, invested: pf.totals.costOpen, positions: pf.open.length },
    };
    const save = { label: STEPS[I.save], group: 'depot', state: 'ok', detail: `Gespeichert am ${fmtDateTime(snapshot.createdAt)} mit Methodik v${snapshot.methodology_version}${snapshot.stage2 ? ` und Stage 2 v${snapshot.stage2.version}` : ''}` };
    snapshot.steps[I.save] = save;
    await db.put('screenings', snapshot);
    if (pf.totals.mv > 0 && screen.asof) await db.put('valuations', { date: screen.asof, value: pf.totals.mv, invested: pf.totals.costOpen });
    set(I.save, 'ok', save.detail);
    return { snapshot, steps, screen, status, signals, pf, details, flags, stage2: s2, stage2Use: use };
  } catch (e) {
    stop(cur, e?.message || String(e));
    return { error: e?.message || String(e), steps };
  }
}

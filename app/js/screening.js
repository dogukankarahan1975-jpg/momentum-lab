// Ablauf "SCREENING STARTEN": 14 nachvollziehbare Schritte, Abbruch bei fehlenden/alten Daten.
import { freshness, loadDetail, loadScreen, loadStatus, reasonText } from './data.js';
import { computePortfolio } from './depot.js';
import { fmtDate, fmtDateTime, uid } from './fmt.js';
import { evaluateHolding } from './signals.js';
import { db } from './store.js';
import { isDataProblem, riskFlags } from './analysis.js';

export const STEPS = [
  'Aktuellen Datenstand abrufen', 'Aktienuniversum laden', 'Alle Aktien untersuchen', 'Fehlerhafte Daten erkennen',
  'Ungeeignete Aktien ausschließen', 'Momentum-Scores berechnen', 'Fundamentale und Risiko-Prüfungen',
  'Unternehmensnachrichten berücksichtigen', 'Aktien ranken', 'Maximal 10 Kandidaten auswählen',
  'Top-Kandidaten bestimmen', 'Depotpositionen einbeziehen', 'Empfehlungen für das Depot erzeugen',
  'Screening mit Datum speichern',
];

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
    const row = screen.bySymbol.get(it.pos.symbol) || null;
    const ev = evaluateHolding({
      row, fresh: fr, globalStatus: screen.status === 'fehler' || status?.overall === 'fehler' ? 'fehler' : screen.status,
      inCandidates: screen.candidates.includes(it.pos.symbol), topPick: screen.top_pick, weight: it.weight,
      maxWeight: settings.maxWeight, plan: planBy[it.pos.id] || null, bestAlternative: alt, params: screen.params,
      reasonLabel: (c) => reasonText(c, screen),
    });
    return { positionId: it.pos.id, symbol: it.pos.symbol, name: it.pos.name, ...ev,
      unreal: it.unreal, mvEUR: it.mvEUR, weight: it.weight, asof: screen.asof };
  });
}

export async function runScreening({ positions, txs, plans, settings, onStep }) {
  const steps = STEPS.map((label) => ({ label, state: 'wait', detail: '' }));
  let cur = 0;
  const set = (i, state, detail = '') => { cur = i; steps[i] = { ...steps[i], state, detail }; onStep?.(steps.map((s) => ({ ...s }))); };
  const stop = (i, detail) => { set(i, 'err', detail); for (let k = i + 1; k < steps.length; k++) steps[k].state = 'skip'; onStep?.(steps.map((s) => ({ ...s }))); };
  try {
    set(0, 'run');
    const [status, screen] = await Promise.all([loadStatus(true).catch(() => null), loadScreen(true)]);
    const fr = freshness(screen.asof);
    const runStatus = status?.overall || screen.status;
    if (screen.status === 'fehler' || runStatus === 'fehler') {
      const m = (status?.messages || []).filter((x) => x.level === 'fehler').map((x) => x.text).join(' ');
      stop(0, `Der letzte Datenlauf meldet einen Fehler. ${m || ''} Es gibt keine Empfehlungen.`);
      return { error: 'Datenlauf fehlerhaft', steps };
    }
    if (fr.abort) {
      stop(0, `Der Datenstand (${fmtDate(screen.asof)}) ist ${fr.label}. Das Screening wurde abgebrochen, damit keine veralteten Empfehlungen entstehen.`);
      return { error: 'Daten zu alt', steps };
    }
    set(0, fr.level === 'aktuell' ? 'ok' : 'warn', `Datenstand ${fmtDate(screen.asof)} (${fr.label}), berechnet am ${fmtDateTime(screen.generated_at)}${screen.demo ? '. DEMO-DATEN' : ''}`);

    const u = screen.universe;
    set(1, u.source?.startsWith('iShares') || screen.demo ? 'ok' : 'warn',
      `${u.size} Aktien, Quelle: ${u.source}${u.as_of ? ` (Stand ${u.as_of})` : ''}${u.watchlist?.length ? `, dazu ${u.watchlist.length} aus der Beobachtungsliste` : ''}`);

    const analyzed = screen.rows.filter((r) => Number.isFinite(r.last_close)).length;
    set(2, analyzed / Math.max(u.size, 1) > 0.8 ? 'ok' : 'warn', `${analyzed} Aktien mit Kursdaten untersucht, ${u.size - u.priced} ohne Kursdaten`);

    const probs = screen.rows.filter((r) => r.in_universe && isDataProblem(r));
    const byCode = {};
    for (const r of probs) for (const c of r.reasons) byCode[c] = (byCode[c] || 0) + 1;
    const top = Object.entries(byCode).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([c, n]) => `${reasonText(c, screen)}: ${n}`).join(', ');
    set(3, probs.length > 0.1 * u.size ? 'warn' : 'ok', probs.length ? `${probs.length} Aktien mit Datenproblemen erkannt (${top})` : 'Keine Datenprobleme erkannt');

    const excl = screen.rows.filter((r) => r.in_universe && !r.eligible).length;
    set(4, 'ok', `${excl} Aktien ausgeschlossen, ${u.eligible} zulässig. Die Gründe stehen in der Liste unten.`);

    const ranked = screen.rows.filter((r) => Number.isInteger(r.rank)).length;
    if (!ranked) { stop(5, 'Keine gültigen Scores in den Daten.'); return { error: 'Keine Scores', steps }; }
    set(5, 'ok', `${ranked} risikoadjustierte Momentum-Scores (Methodik v${screen.methodology_version})`);

    set(6, 'run');
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
    set(6, missingFund ? 'warn' : 'ok', `${flagCount} Risikohinweise bei den Kandidaten${missingFund ? `. Für ${missingFund} fehlen Fundamentaldaten` : ''}`);

    const newsN = screen.candidates.reduce((n, s) => n + (details[s]?.news?.length || 0) + (details[s]?.fund?.sec_filings?.filings?.length || 0), 0);
    set(7, newsN || screen.demo ? 'ok' : 'warn', newsN ? `${newsN} Meldungen geladen. Sie werden angezeigt, fließen aber nicht in den Score ein.` : 'Keine Meldungen verfügbar');

    set(8, 'ok', 'Rangfolge nach risikoadjustiertem 6- und 12-Monats-Momentum');
    set(9, screen.candidates.length ? 'ok' : 'warn', screen.candidates.length
      ? `${screen.candidates.length} Kandidaten erfüllen alle Kriterien`
      : 'Keine Aktie erfüllt derzeit alle Kriterien. Die App empfiehlt deshalb nichts.');
    const tp = screen.top_pick ? screen.bySymbol.get(screen.top_pick) : null;
    set(10, tp ? 'ok' : 'warn', tp ? `Top Pick: ${tp.name} (${tp.symbol})` : 'Kein Top Pick. Kein Kandidat erfüllt alle zusätzlichen Robustheitsregeln.');

    const pf = computePortfolio(positions, txs, screen);
    const matched = pf.open.filter((i) => screen.bySymbol.get(i.pos.symbol)?.last_close != null).length;
    set(11, pf.open.length === 0 ? 'ok' : matched === pf.open.length ? 'ok' : 'warn',
      pf.open.length ? `${pf.open.length} Positionen, ${matched} davon mit aktuellen Daten` : 'Noch keine Depotpositionen erfasst');

    const signals = computeSignals(screen, status, pf, plans, settings);
    const cnt = {};
    for (const s of signals) { cnt[s.signal] = (cnt[s.signal] || 0) + 1; if (s.plan) cnt[s.plan.signal] = (cnt[s.plan.signal] || 0) + 1; }
    set(12, 'ok', signals.length ? Object.entries(cnt).map(([k, v]) => `${v}× ${k}`).join(', ') : 'Keine Positionen zu bewerten');

    const snapshot = {
      id: uid(), createdAt: new Date().toISOString(), asof: screen.asof, generated_at: screen.generated_at,
      methodology_version: screen.methodology_version, params_hash: screen.params_hash, pipeline_version: screen.pipeline_version,
      status: screen.status, freshness: fr, demo: !!screen.demo, top_pick: screen.top_pick,
      candidates: screen.candidates.map((s) => {
        const r = screen.bySymbol.get(s);
        return { symbol: s, name: r.name, rank: r.rank, Z: r.Z, pct: r.pct, m6: r.m6, m12: r.m12, vol: r.vol, sector: r.sector,
          country: r.country, flags: (flags[s] || []).map((x) => x.text) };
      }),
      signals: signals.map((s) => ({ positionId: s.positionId, symbol: s.symbol, name: s.name, signal: s.signal, urgency: s.urgency,
        reasons: s.reasons, next: s.next, plan: s.plan ? { signal: s.plan.signal, reasons: s.plan.reasons, switchTo: s.plan.switchTo } : null })),
      market: screen.market, universe: screen.universe, steps: steps.map((s) => ({ label: s.label, state: s.state, detail: s.detail })),
      depot: { value: pf.totals.mv, invested: pf.totals.costOpen, positions: pf.open.length },
    };
    snapshot.steps[13] = { label: STEPS[13], state: 'ok', detail: `Gespeichert am ${fmtDateTime(snapshot.createdAt)} mit Methodik v${snapshot.methodology_version}` };
    await db.put('screenings', snapshot);
    if (pf.totals.mv > 0 && screen.asof) await db.put('valuations', { date: screen.asof, value: pf.totals.mv, invested: pf.totals.costOpen });
    set(13, 'ok', snapshot.steps[13].detail);
    return { snapshot, steps, screen, status, signals, pf, details, flags };
  } catch (e) {
    stop(cur, e?.message || String(e));
    return { error: e?.message || String(e), steps };
  }
}

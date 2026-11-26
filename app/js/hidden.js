// „Gibt es bei Trade Republic nicht“: vom Nutzer ausgeblendete Aktien (nur lokal gespeichert).
import { getSetting, setSetting } from './store.js';

const KEY = 'hiddenTR';

export async function getHidden() {
  try { return new Set(await getSetting(KEY, [])); } catch { return new Set(); }
}
export async function setHidden(symbol, hide) {
  const s = await getHidden();
  if (hide) s.add(symbol); else s.delete(symbol);
  await setSetting(KEY, [...s].sort());
  return s;
}

/** Entfernt ausgeblendete Aktien aus den Stage-1-Kandidaten und lässt die nächsten nach derselben Regel nachrücken. */
export function applyHiddenScreen(screen, hidden) {
  const orig = screen.candidatesOrig || screen.candidates;
  const tpOrig = 'topPickOrig' in screen ? screen.topPickOrig : screen.top_pick;
  const out = { ...screen, candidatesOrig: orig, topPickOrig: tpOrig, hiddenSyms: [...hidden].filter((s) => screen.bySymbol.has(s)) };
  if (!hidden.size || !orig.some((s) => hidden.has(s))) return { ...out, candidates: orig, top_pick: tpOrig, topPickHidden: false, refilled: [] };
  const p = screen.params || {};
  const keep = orig.filter((s) => !hidden.has(s));
  const ok = (r) => r.eligible && r.Z != null && r.rank != null && r.pct != null && r.pct <= (p.candidate_max_pct ?? 0.1)
    && (!p.require_positive_m6 || r.m6 > 0) && (!p.require_positive_m12 || r.m12 > 0);
  const extra = screen.rows.filter((r) => ok(r) && !hidden.has(r.symbol) && !keep.includes(r.symbol))
    .sort((a, b) => a.rank - b.rank).slice(0, Math.max(0, orig.length - keep.length)).map((r) => r.symbol);
  const cands = [...keep, ...extra].sort((a, b) => screen.bySymbol.get(a).rank - screen.bySymbol.get(b).rank);
  const tpHidden = !!tpOrig && hidden.has(tpOrig);
  return { ...out, candidates: cands, top_pick: tpHidden ? null : tpOrig, topPickHidden: tpHidden, refilled: extra };
}

/** Stage 2: ausgeblendete Aktien entfernen, Plätze neu zählen, Top 5 = die ersten 5 der übrigen. */
export function applyHiddenStage2(s2, hidden) {
  if (!s2 || !s2.ranking || !hidden.size) return s2;
  const ranking = s2.ranking.filter((r) => !hidden.has(r.symbol)).map((r, i) => ({
    ...r, buy: r.stage2?.score != null && i < (s2.top_n || 5), stage2: { ...r.stage2, rank: i + 1, rank_orig: r.stage2?.rank },
  }));
  return { ...s2, ranking, buy: ranking.filter((r) => r.buy).map((r) => r.symbol), bySymbol: new Map(ranking.map((r) => [r.symbol, r])) };
}

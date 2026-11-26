// Stage 2 v2 auf der Aktienseite: warum dieser Platz in der Fortsetzungs-Rangfolge?
import { fmtNum } from '../fmt.js';
import { PART_LABEL, buyBadge, fmtSignal, pctBar } from '../stage2.js';
import { html, note } from '../ui.js';

export function stage2DetailHTML(e, s2, use) {
  const st = e.stage2 || {};
  const sigs = e.signals || [];
  const meth = new Map((s2.method?.signals || []).map((x) => [x.key, x]));
  const row = (sg) => {
    const m = meth.get(sg.key) || {};
    return html`<div class="cat-row" style="display:block;padding:8px 0;border-top:1px solid var(--line-soft)">
      <div style="display:flex;justify-content:space-between;gap:8px"><span class="small"><b>${sg.label}</b></span><span class="small">${sg.pct == null ? 'keine Daten' : `besser als ${Math.round(sg.pct * 100)} %`}</span></div>
      ${pctBar(sg.pct)}
      <div class="xs muted" style="margin-top:4px">Wert ${fmtSignal(sg.key, sg.value)}. ${m.why || ''} <i>${m.study || ''}</i></div></div>`;
  };
  return html`<h2>Stage 2 – Fortsetzungs-Rangfolge</h2>
    ${use.ok ? '' : note('warn', use.reason)}
    <div class="panel">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><div><div class="xs muted">Platz unter den Top-10-Kandidaten</div><div class="s2-score">${st.rank ?? '–'}<span class="small muted"> von ${s2.ranking.length}</span></div></div>
        <div style="text-align:right">${buyBadge(e)}<div class="xs muted" style="margin-top:4px">Score ${st.score_display != null ? fmtNum(st.score_display, 1) : '–'} von 10</div></div></div>
      <p class="small" style="margin:10px 0 0">Stage 1 sagt, wie stark die Aktie gestiegen ist. Stage 2 prüft, wie wahrscheinlich es weitergeht: Jedes Signal wird mit allen ${s2.method?.peers ?? ''} Momentum-Aktien verglichen. ${st.price_only ? 'Für diese Aktie fehlen aktuelle Analystendaten, ihr Score beruht nur auf dem Kursteil.' : `Kursteil ${fmtNum((st.kurs ?? 0) * 10, 1)}, Gewinnteil ${fmtNum((st.gewinn ?? 0) * 10, 1)} (je zur Hälfte).`}</p>
    </div>
    ${['kurs', 'gewinn'].map((part) => html`<h3>${PART_LABEL[part]}</h3><div class="panel">${sigs.filter((x) => x.part === part).map(row)}</div>`)}
    ${e.flags?.length ? html`<h3>Hinweise</h3><ul class="small">${e.flags.map((f) => html`<li>${f}</li>`)}</ul>` : ''}
    <p class="xs muted">Stage 2 schließt keine Aktie aus und ist keine Anlageberatung. Ob die Rangfolge die Rendite verbessert, zeigt der Simulator (Kursteil, „Stage 2 Top 5“) und ab jetzt das Live-Protokoll.</p>`;
}

export function stage2CompactHTML() { return ''; }

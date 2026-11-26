// Stage 2 v2 – Fortsetzungs-Rangfolge: Hilfsfunktionen für die Anzeige.
import { fmtNum, fmtPct } from './fmt.js';
import { html } from './ui.js';

export const PART_LABEL = { kurs: 'Kursteil', gewinn: 'Gewinnteil' };

export function stage2Usable(s2, screen, fr) {
  if (!s2) return { ok: false, reason: 'Stage 2 wird beim nächsten Datenlauf zum ersten Mal berechnet.' };
  if (s2.status === 'fehler') return { ok: false, reason: s2.messages?.[0]?.text || 'Stage 2 konnte nicht berechnet werden.' };
  if (!s2.schema || s2.schema < 2) return { ok: false, reason: 'Stage 2 wird gerade auf die neue Fortsetzungs-Rangfolge umgestellt. Die neuen Daten kommen mit dem nächsten Datenlauf.' };
  if (screen && s2.asof !== screen.asof) return { ok: false, reason: `Stage 2 hat einen anderen Datenstand (${s2.asof}) als Stage 1 (${screen.asof}).` };
  if (fr && !fr.ok) return { ok: false, reason: `Die Daten sind ${fr.label}. Die Rangfolge ist nicht aktuell.` };
  return { ok: true, reason: '' };
}

export function buyBadge(r) {
  return r?.buy ? html`<span class="badge b-buy">Top 5 – kaufen</span>` : html`<span class="badge b-hold">Platz 6–10</span>`;
}

/** Balken 0–100 % für ein Perzentil. */
export function pctBar(p) {
  const w = p == null ? 0 : Math.max(2, Math.round(p * 100));
  return html`<div class="bar10" title="${p == null ? 'keine Daten' : `besser als ${Math.round(p * 100)} %`}"><span style="width:${w}%"></span></div>`;
}

export function fmtSignal(key, v) {
  if (v == null) return '–';
  if (key === 'prox_52w') return fmtPct(v - 1, 1);
  if (key === 'breadth30') return fmtPct(v, 0);
  if (key === 'rev90' || key === 'surprise4') return fmtPct(v, 1);
  return fmtNum(v, 2);
}

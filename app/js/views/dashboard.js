import { cachedStatus, freshness, getUniverse, loadStatus, UNIVERSE_LABEL } from '../data.js';
import { fmtDate, fmtDateTime } from '../fmt.js';
import { latestScreening, state } from '../state.js';
import { getSetting } from '../store.js';
import { chevron, html, note, universeSwitch } from '../ui.js';
import { wireUniverse } from '../main.js';

export async function render(root) {
  const [status, snap, lastBackup, changes] = await Promise.all([
    cachedStatus() ? Promise.resolve(cachedStatus()) : loadStatus().catch(() => null),
    latestScreening(), getSetting('lastBackupAt', null), getSetting('changesSinceBackup', 0),
  ]);
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
    ${universeSwitch(getUniverse())}
    <p class="muted small">${snap ? `Zuletzt am ${fmtDateTime(snap.createdAt)}${snap.uniKey ? ` (${UNIVERSE_LABEL[snap.uniKey]})` : ''} mit Daten vom ${fmtDate(snap.asof)}: ${snap.candidates.length} Kandidaten.` : 'Noch kein Screening durchgeführt.'}</p>
    <button class="screen-btn" id="go-screen">SCREENING STARTEN</button>
  </section>`);

  // Backup-Erinnerung
  const days = lastBackup ? (Date.now() - new Date(lastBackup)) / 86400000 : Infinity;
  if (state.positions.length && (days > (state.settings?.backupReminderDays || 14) || changes > 20)) {
    parts.push(note('warn', html`${lastBackup ? `Letztes Backup vor ${Math.floor(days)} Tagen` : 'Noch kein Backup erstellt'}${changes ? `, seitdem ${changes} Änderungen` : ''}. <a href="#/einstellungen">Jetzt sichern</a>`));
  }

  parts.push(html`<div class="group">
    <a class="row" href="#/backtest"><div class="grow"><div class="title">Backtest</div><div class="sub">Simulator: Strategien mit echten Kursen vergleichen</div></div>${chevron}</a>
  </div>
  <p class="xs muted">Momentum Lab ist ein privates Analysewerkzeug und keine Anlageberatung. Alle Signale folgen festen, dokumentierten Regeln.</p>`);
  root.innerHTML = parts.join('');
  wireUniverse(root);
  root.querySelector('#go-screen').onclick = () => { sessionStorage.setItem('autorun', '1'); location.hash = '#/screening'; };
}

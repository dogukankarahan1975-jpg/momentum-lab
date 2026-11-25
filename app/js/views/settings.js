import { clearMemo, freshness, getJSON, loadMethodology, loadStatus } from '../data.js';
import { fmtDate, fmtDateTime, fmtNum, fmtPct, parseDec, todayISO } from '../fmt.js';
import { refreshHeader } from '../main.js';
import { reloadDepot, reloadSettings, state } from '../state.js';
import { exportBackup, getSetting, importBackup, markBackupDone, requestPersist, setSetting, storageInfo, validateBackup, wipeAll } from '../store.js';
import { confirmDialog, html, note, openSheet, srcTag, toast } from '../ui.js';

const PARAM_LABELS = [
  ['m6_months', 'Momentum kurz (Monate, ohne letzten)', (v) => `${v}`],
  ['m12_months', 'Momentum lang (Monate, ohne letzten)', (v) => `${v}`],
  ['skip_months', 'Ausgeschlossener jüngster Zeitraum', (v) => `${v} Monat`],
  ['vol_weeks', 'Volatilität: Wochenrenditen', (v) => `${v} Wochen`],
  ['weight_m6', 'Gewicht 6 Monate', (v) => fmtPct(v, 0, false)],
  ['weight_m12', 'Gewicht 12 Monate', (v) => fmtPct(v, 0, false)],
  ['winsor_sigma', 'Robuste Standardisierung', (v) => `±${v} σ`],
  ['min_history_years', 'Mindesthistorie', (v) => `${v} Jahre`],
  ['stale_days', 'Kurs höchstens so alt', (v) => `${v} Tage`],
  ['min_liquidity_eur', 'Mindestumsatz pro Tag (Median)', (v) => `${fmtNum(v / 1e6, 0)} Mio. €`],
  ['min_price_eur', 'Mindestkurs', (v) => `${v} €`],
  ['crosscheck_tolerance', 'Toleranz Gegenprüfung', (v) => fmtPct(v, 0, false)],
  ['top_n', 'Maximale Kandidaten', (v) => `${v}`],
  ['candidate_max_pct', 'Kandidat muss im besten', (v) => `${fmtPct(v, 0, false)} liegen`],
  ['toppick_min_z6', 'Top Pick: Mindest-Teilscore', (v) => `${v}`],
  ['toppick_max_vol_pct', 'Top Pick: Volatilität höchstens', (v) => `${fmtPct(v, 0, false)}-Perzentil`],
  ['hold_max_pct', 'Halteband', (v) => `beste ${fmtPct(v, 0, false)}`],
  ['sell_immediate_pct', 'Sofortverkauf unterhalb', (v) => `${fmtPct(v, 0, false)} (Median)`],
  ['confirm_months', 'Bestätigung Verkauf', (v) => `${v} Monatsenden`],
  ['savings_max_pct', 'Sparplan fortsetzen bis', (v) => `beste ${fmtPct(v, 0, false)}`],
  ['trend_ma_days', 'Trendlinie (nur Hinweis)', (v) => `${v} Tage`],
];

function repoUrl() {
  const h = location.hostname;
  if (!h.endsWith('github.io')) return null;
  const user = h.split('.')[0];
  const repo = location.pathname.split('/').filter(Boolean)[0];
  return repo ? `https://github.com/${user}/${repo}` : null;
}

export async function render(root) {
  const [status, meth, info, lastBackup, changes] = await Promise.all([
    loadStatus(true).catch((e) => ({ error: e.message })), loadMethodology().catch(() => null), storageInfo(),
    getSetting('lastBackupAt', null), getSetting('changesSinceBackup', 0),
  ]);
  const s = state.settings;
  const repo = repoUrl();
  const build = document.querySelector('meta[name="ml-build"]')?.content || 'lokal';
  const fr = freshness(status?.asof);
  const parts = [html`<h1>Einstellungen und Datenquellen</h1>`];

  // Datenstatus
  parts.push(html`<h2>Datenstatus</h2>`);
  if (status?.error) parts.push(note('error', status.error));
  else {
    const lvl = status.overall === 'fehler' ? 'error' : status.overall === 'warnung' || !fr.ok ? 'warn' : 'ok';
    parts.push(note(lvl, html`<b>${status.overall === 'ok' ? 'Datenlauf in Ordnung' : status.overall === 'warnung' ? 'Datenlauf mit Warnungen' : 'Datenlauf fehlgeschlagen'}</b>. Datenstand ${fmtDate(status.asof)} (${fr.label}), berechnet ${fmtDateTime(status.generated_at)}, Laufzeit ${fmtNum(status.runtime_s / 60, 1)} Min.`));
    for (const m of status.messages || []) parts.push(note(m.level === 'fehler' ? 'error' : m.level === 'warnung' ? 'warn' : 'info', m.text));
    const cov = status.coverage || {};
    parts.push(html`<div class="panel"><dl class="kv">
      <dt>Aktien im Universum</dt><dd>${cov.universe ?? '–'}</dd><dt>Mit Kursdaten</dt><dd>${cov.priced ?? '–'}</dd>
      <dt>Davon aktuell</dt><dd>${cov.fresh ?? '–'}</dd><dt>Zulässig</dt><dd>${cov.eligible ?? '–'}</dd>
      <dt>Gegengeprüft (iShares)</dt><dd>${cov.crosschecked ?? '–'}, Abweichungen ${cov.crosscheck_deviations ?? '–'}</dd>
      <dt>Methodik / Pipeline</dt><dd>v${status.methodology_version} / v${status.pipeline_version}</dd></dl></div>`);
    parts.push(html`<h3>Datenquellen</h3><div class="group">${Object.entries(status.sources || {}).map(([k, v]) => html`<div class="row">
      <div class="grow"><div class="title" style="white-space:normal">${v.name} ${srcTag(v.type || 'database')}</div>
      <div class="sub" style="white-space:normal">${sourceDetail(k, v)}</div></div>
      <span class="badge ${v.ok ? 'b-buy' : 'b-sell'}">${v.ok ? 'ok' : 'Problem'}</span></div>`)}</div>
      <p class="xs muted">Kurse: Yahoo Finance (inoffiziell, frei, keine Garantie). Wechselkurse: Europäische Zentralbank (offiziell). Universum und Gegenprüfung: iShares-Bestandsliste. US-Fundamentaldaten: SEC EDGAR (offiziell). Nachrichten: Google News RSS (Sekundärquelle).</p>`);
  }

  // Methodik
  parts.push(html`<h2>Methodik</h2>`);
  if (meth) {
    parts.push(html`<div class="panel"><p class="small">Version <b>${meth.version}</b> (Parameter-Prüfsumme ${meth.params_hash}). Orientiert an der MSCI-Momentum-Methodik mit dokumentierten Abweichungen. Jede Änderung erhöht die Version, frühere Screenings bleiben mit ihrer Version gespeichert.</p>
      <dl class="kv small">${PARAM_LABELS.filter(([k]) => k in meth.params).map(([k, l, f]) => html`<dt>${l}</dt><dd>${f(meth.params[k])}</dd>`)}</dl>
      ${repo ? html`<p class="small" style="margin:10px 0 0"><a href="${repo}/blob/main/docs/METHODIK.md" target="_blank" rel="noopener">Ausführliche Methodik mit Quellen</a></p>` : ''}</div>`);
  } else parts.push(note('info', 'Methodik-Datei noch nicht verfügbar.'));
  if (meth?.stage2) {
    const m2 = meth.stage2;
    const w = m2.params?.weights || {};
    parts.push(html`<div class="panel"><p class="small">Stage 2 (Fortsetzungsanalyse) Version <b>${m2.version}</b> (Prüfsumme ${m2.params_hash}). Jede Kennzahl wird als Perzentil gegen eine feste Vergleichsgruppe gemessen: alle zulässigen MSCI-World-Aktien, der eigene Sektor (Fundamentaldaten und Bewertung) oder die Momentum-Gruppe (Überhitzung). Fehlende Werte werden nie geschätzt.</p>
      <dl class="kv small">${Object.entries(m2.categories || {}).map(([k, c]) => html`<dt>${k} ${c.name}</dt><dd>${fmtPct(w[k], 0, false)}</dd>`)}
      <dt>Score nur ab verfügbarem Gewicht</dt><dd>${fmtPct(m2.params?.min_weight_available, 0, false)}</dd>
      <dt>Schwellen EXCEPTIONAL / STRONG BUY / WATCHLIST / NO ENTRY</dt><dd>${(m2.params?.thresholds || []).slice(0, 4).map((t) => fmtNum(t[0], 1)).join(' / ')}</dd>
      <dt>Kennzahlen höchstens</dt><dd>${m2.params?.fund_max_age_days} Tage alt</dd>
      <dt>Vergleichsgruppe nötig</dt><dd>${fmtPct(m2.params?.ref_min_coverage, 0, false)} Abdeckung</dd></dl>
      <p class="xs muted" style="margin:10px 0 0">Gewichte und Schwellen sind deine Vorgabe und noch heuristisch. Gültig sind nur vorab festgelegte, versionierte Regeln.${repo ? html` <a href="${repo}/blob/main/docs/METHODIK.md#stage-2" target="_blank" rel="noopener">Stage 2 in der Methodik</a>` : ''}</p></div>`);
  }
  parts.push(html`<div class="group"><button class="row" id="archive"><div class="grow"><div class="title">Offizielle Monats-Screenings</div><div class="sub">Archiv des Datenlaufs (je Monatsende)</div></div></button></div>`);

  // Depot-Einstellungen
  parts.push(html`<h2>Depot-Einstellungen</h2><div class="panel">
    <label class="field"><span>Maximaler Depotanteil für "Nachkaufen" (%)</span><input id="mw" inputmode="decimal" value="${fmtNum(s.maxWeight * 100, 0)}"></label>
    <label class="field"><span>Verbleibender Sparerpauschbetrag (€, für Steuerschätzungen)</span><input id="ta" inputmode="decimal" value="${fmtNum(s.taxAllowanceLeft, 0)}"></label>
    <label class="toggle"><span>Kirchensteuer berücksichtigen</span><input id="ct" type="checkbox" ${s.churchTax ? 'checked' : ''}></label>
    <label class="field"><span>Backup-Erinnerung nach (Tagen)</span><input id="br" inputmode="numeric" value="${s.backupReminderDays}"></label>
    <button class="btn" id="save-s">Einstellungen speichern</button></div>`);

  // Backup
  parts.push(html`<h2>Backup und Wiederherstellung</h2><div class="panel">
    <p class="small">Deine Depotdaten liegen nur auf diesem iPhone. Sichere sie regelmäßig als Datei, am besten in iCloud Drive über "In Dateien sichern". Mit der Datei kannst du alles auf jedem Gerät wiederherstellen.</p>
    <dl class="kv small"><dt>Letztes Backup</dt><dd>${lastBackup ? fmtDateTime(lastBackup) : 'noch nie'}</dd><dt>Änderungen seitdem</dt><dd>${changes}</dd></dl>
    <div class="btn-row" style="margin-top:12px"><button class="btn primary" id="exp">Backup exportieren</button><button class="btn" id="imp">Backup importieren</button></div>
    <input id="file" type="file" accept=".json,application/json" hidden></div>`);

  // Speicher
  parts.push(html`<h2>Speicher</h2><div class="panel small"><dl class="kv">
    <dt>Als Home-Bildschirm-App geöffnet</dt><dd>${info.standalone ? 'ja' : 'nein'}</dd>
    <dt>Dauerhafter Speicher</dt><dd>${info.persisted === true ? 'ja' : info.persisted === false ? 'nein' : 'unbekannt'}</dd>
    <dt>Belegt</dt><dd>${info.usage != null ? `${fmtNum(info.usage / 1e6, 1)} MB` : '–'}</dd></dl>
    ${!info.standalone ? html`<p style="margin-top:10px">${note('warn', 'Bitte die App über "Teilen → Zum Home-Bildschirm" installieren und nur über das Symbol öffnen. Safari kann Daten von Websites nach 7 Tagen ohne Nutzung löschen. Für Home-Bildschirm-Apps gilt diese Regel nicht. Safari und die installierte App haben getrennte Speicher.')}</p>` : ''}
    <button class="btn small" id="persist">Dauerhaften Speicher anfordern</button></div>`);

  // App
  parts.push(html`<h2>App</h2><div class="group">
    <button class="row" id="reload"><div class="grow"><div class="title">Daten neu laden</div><div class="sub">Holt den neuesten Stand vom Datenlauf</div></div></button>
    <button class="row" id="upd"><div class="grow"><div class="title">Nach App-Update suchen</div><div class="sub">Version ${build}</div></div></button>
    ${repo ? html`<a class="row" href="${repo}" target="_blank" rel="noopener"><div class="grow"><div class="title">Projekt auf GitHub</div><div class="sub">Code, Datenlauf (Actions) und Dokumentation</div></div></a>` : ''}
  </div>
  <h2>Alle lokalen Daten löschen</h2><div class="panel small"><p>Löscht Positionen, Transaktionen, Sparpläne und gespeicherte Screenings von diesem Gerät. Erstelle vorher ein Backup.</p><button class="btn danger" id="wipe">Alles löschen</button></div>`);
  root.innerHTML = parts.join('');

  const $ = (q) => root.querySelector(q);
  $('#save-s').onclick = async () => {
    const mw = parseDec($('#mw').value) / 100, ta = parseDec($('#ta').value), br = Math.round(parseDec($('#br').value));
    if (!(mw > 0 && mw <= 1) || !(ta >= 0) || !(br >= 1)) { toast('Bitte gültige Werte eingeben'); return; }
    await setSetting('maxWeight', mw); await setSetting('taxAllowanceLeft', ta); await setSetting('churchTax', $('#ct').checked); await setSetting('backupReminderDays', br);
    await reloadSettings(); toast('Gespeichert');
  };
  $('#exp').onclick = async () => {
    try {
      const obj = await exportBackup();
      const name = `momentum-lab-backup-${todayISO()}.json`;
      const blob = new Blob([JSON.stringify(obj, null, 1)], { type: 'application/json' });
      const file = new File([blob], name, { type: 'application/json' });
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], title: 'Momentum Lab Backup' });
      } else {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
      }
      await markBackupDone();
      toast('Backup erstellt');
      setTimeout(() => window.dispatchEvent(new HashChangeEvent('hashchange')), 600);
    } catch (e) {
      if (e?.name !== 'AbortError') toast(`Backup fehlgeschlagen: ${e.message}`);
    }
  };
  $('#imp').onclick = () => $('#file').click();
  $('#file').onchange = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    let obj;
    try { obj = JSON.parse(await f.text()); } catch { toast('Die Datei ist kein gültiges Backup (kein JSON).'); return; }
    const v = validateBackup(obj);
    openSheet({ title: 'Backup importieren', body: String(html`
      ${v.ok ? note('ok', `Gültiges Backup vom ${fmtDateTime(v.exported_at)}`) : note('error', v.errors.join(' '))}
      <dl class="kv small"><dt>Positionen</dt><dd>${v.counts?.positions ?? 0}</dd><dt>Transaktionen</dt><dd>${v.counts?.transactions ?? 0}</dd>
      <dt>Sparpläne</dt><dd>${v.counts?.plans ?? 0}</dd><dt>Screenings</dt><dd>${v.counts?.screenings ?? 0}</dd></dl>
      ${v.ok ? html`<p class="small" style="margin-top:12px"><b>Ersetzen</b> löscht die aktuellen Daten auf diesem Gerät und übernimmt das Backup. <b>Zusammenführen</b> ergänzt und überschreibt nur Einträge mit gleicher ID.</p>
      <div class="btn-row"><button class="btn primary" id="rep">Ersetzen</button><button class="btn" id="mrg">Zusammenführen</button></div>` : ''}`),
    onMount: (el, close) => {
      const run = async (mode) => {
        const ok = await confirmDialog({ title: mode === 'replace' ? 'Daten ersetzen?' : 'Daten zusammenführen?',
          text: mode === 'replace' ? 'Alle aktuellen Depotdaten auf diesem Gerät werden durch das Backup ersetzt.' : 'Das Backup wird mit den vorhandenen Daten zusammengeführt.', confirm: 'Importieren', danger: mode === 'replace' });
        if (!ok) return;
        try { await importBackup(obj, mode); await reloadDepot(); await reloadSettings(); close(); toast('Backup importiert'); window.dispatchEvent(new HashChangeEvent('hashchange')); }
        catch (err) { toast(`Import fehlgeschlagen: ${err.message}`); }
      };
      el.querySelector('#rep')?.addEventListener('click', () => run('replace'));
      el.querySelector('#mrg')?.addEventListener('click', () => run('merge'));
    } });
  };
  $('#persist').onclick = async () => { const ok = await requestPersist(); toast(ok ? 'Dauerhafter Speicher aktiv' : 'Das System hat die Anfrage abgelehnt. Bitte die App vom Home-Bildschirm öffnen.'); };
  $('#reload').onclick = async () => { clearMemo(); await refreshHeader(); toast('Daten neu geladen'); window.dispatchEvent(new HashChangeEvent('hashchange')); };
  $('#upd').onclick = async () => {
    const reg = await navigator.serviceWorker?.getRegistration?.();
    if (!reg) { toast('Kein Update-Dienst aktiv'); return; }
    await reg.update(); toast(reg.installing || reg.waiting ? 'Update gefunden' : 'App ist aktuell');
  };
  $('#wipe').onclick = async () => {
    const ok = await confirmDialog({ title: 'Alle lokalen Daten löschen?', text: 'Dieser Schritt kann nicht rückgängig gemacht werden, außer mit einem Backup.', confirm: 'Endgültig löschen', danger: true, requireText: 'LÖSCHEN' });
    if (!ok) return;
    await wipeAll(); await reloadDepot(); await reloadSettings(); toast('Alle lokalen Daten gelöscht');
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  };
  $('#archive').onclick = async () => {
    let idx;
    try { idx = await getJSON('archive/index.json'); } catch { toast('Noch kein Archiv vorhanden. Es entsteht ab dem ersten Monatswechsel.'); return; }
    const months = [...(idx.months || [])].reverse();
    openSheet({ title: 'Monats-Screenings', body: months.length ? `<div class="group">${months.map((m) => `<button class="row" data-m="${m}"><div class="grow"><div class="title">${m}</div></div></button>`).join('')}</div><div id="arch"></div>` : '<p class="muted">Noch keine Einträge.</p>',
      onMount: (el) => {
        el.querySelectorAll('[data-m]').forEach((b) => { b.onclick = async () => {
          const a = await getJSON(`archive/${b.dataset.m}.json`);
          el.querySelector('#arch').innerHTML = String(html`<h3 style="margin-top:14px">Stichtag ${fmtDate(a.asof)}, Methodik v${a.methodology_version}</h3>
            <p class="small">Kandidaten: ${(a.candidates || []).join(', ') || 'keine'}</p>`);
        }; });
      } });
  };
}

function sourceDetail(key, v) {
  const parts = [];
  if (v.stats) parts.push(`${v.stats.ok} ok, ${v.stats.failed} ohne Daten, ${v.stats.cached_only || 0} nur aus Cache${v.stats.blocked ? ', Sperre erkannt' : ''}`);
  if (v.as_of) parts.push(`Stand ${v.as_of}`);
  if (v.size) parts.push(`${v.size} Aktien`);
  if (v.last_date) parts.push(`letzter Kurs ${fmtDate(v.last_date)}${v.from_cache ? ' (Cache)' : ''}`);
  if (v.checked != null) parts.push(`${v.checked} geprüft, ${v.deviations} Abweichungen`);
  if (v.detail) parts.push(v.detail);
  if (v.error) parts.push(v.error);
  return parts.join(', ') || (v.ok ? 'in Ordnung' : 'nicht verfügbar');
}

import { fundamentals, riskFlags, whyBetter, whySelected } from '../analysis.js';
import { lineChart } from '../charts.js';
import { freshness, loadDetail, loadScreen, loadStage2, reasonText, refreshHidden } from '../data.js';
import { getHidden, setHidden } from '../hidden.js';
import { stage2Usable } from '../stage2.js';
import { stage2DetailHTML } from './stage2-detail.js';
import { cls, fmtCompact, fmtDate, fmtEUR, fmtMoney, fmtNum, fmtPct, fmtPrice, fmtRankPct } from '../fmt.js';
import { state } from '../state.js';
import { badge, holdBand, html, note, raw, safeUrl, srcTag } from '../ui.js';
import { openTxForm } from './forms.js';

export async function render(root, symbol) {
  const screen = await loadScreen();
  const r = screen.bySymbol.get(symbol);
  if (!r) { root.innerHTML = String(note('error', `Keine Daten zu ${symbol}.`)); return; }
  let d = null;
  if (r.has_detail) { try { d = await loadDetail(symbol); } catch { d = null; } }
  const isCand = screen.candidates.includes(symbol);
  const hold = screen.params?.hold_max_pct ?? 0.2;
  const held = state.positions.find((p) => p.symbol === symbol);
  const fm = fundamentals(d);
  const flags = r.Z != null ? riskFlags(r, d, screen, { isCandidate: isCand }) : [];
  const yahooUrl = `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}`;
  const parts = [];
  const isHidden = (await getHidden()).has(symbol);
  if (screen.demo) parts.push(html`<div class="demo-banner">DEMO-DATEN – erfundenes Unternehmen</div>`);
  parts.push(html`<p style="margin:4px 0"><a href="#/top10">‹ Top 10</a></p>
    <h1>${r.name}</h1>
    <div class="chips" style="margin:6px 0 12px"><span class="chip">${symbol}</span><span class="chip">${r.country}</span><span class="chip">${r.sector}</span>${r.isin ? html`<span class="chip">${r.isin}</span>` : ''}
      ${symbol === screen.top_pick ? badge('TOP PICK') : isCand ? badge('KAUF-KANDIDAT') : ''}${held ? html`<span class="chip" style="color:var(--ice)">im Depot</span>` : ''}</div>`);
  if (isHidden) parts.push(note('warn', html`<b>Ausgeblendet:</b> Du hast markiert, dass es diese Aktie bei Trade Republic nicht gibt. Sie erscheint nicht in Top 10, Stage 2 und im Simulator.`));
  if (r.Z != null) {
    parts.push(html`<div class="panel"><div style="display:flex;justify-content:space-between;align-items:baseline">
      <div><div class="muted xs">Rang</div><div style="font-family:var(--display);font-size:24px;font-weight:750">${r.rank ? `${r.rank}.` : '–'} <span class="small muted" style="font-weight:500">${fmtRankPct(r.pct)}</span></div></div>
      <div style="text-align:right"><div class="muted xs">Momentum-Score</div><div style="font-family:var(--display);font-size:24px;font-weight:750">${fmtNum(r.Z, 2)}</div></div></div>
      <div style="margin-top:10px">${holdBand(r.pct, { holdMax: hold, prevPct: r.prev_pct })}</div>
      ${r.prev_pct != null ? html`<p class="xs muted" style="margin:6px 0 0">Kreis = Position am letzten Monatsende (${fmtDate(screen.prev_month_end)})</p>` : ''}</div>`);
  }
  // Stage 2 (Fortsetzungsanalyse): volle Analyse für Kandidaten, Kurzfassung für alle anderen mit Score
  let s2 = null;
  try { s2 = await loadStage2(); } catch { s2 = null; }
  const e2 = s2?.bySymbol?.get(symbol);
  if (e2 && s2.schema >= 2) parts.push(stage2DetailHTML(e2, s2, stage2Usable(s2, screen, freshness(screen.asof))));
  // Kurs
  parts.push(html`<h2>Kursentwicklung</h2><div class="panel"><div id="pchart"></div>
    <p class="xs muted" style="margin:6px 0 0">Dividenden- und splitbereinigt, Landeswährung (${r.currency}). Gestrichelt: 200-Tage-Linie. Quelle: Yahoo Finance ${srcTag('database')}</p></div>`);
  parts.push(html`<h2>Momentum und Risiko</h2><div class="panel"><dl class="kv">
    <dt>Letzter Kurs (${fmtDate(r.last_date)})</dt><dd>${fmtPrice(r.last_close, r.currency)}${r.currency !== 'EUR' ? html`<div class="xs muted">${fmtEUR(r.last_close_eur)}</div>` : ''}</dd>
    <dt>6 Monate ohne letzten Monat</dt><dd class="${cls(r.m6)}">${fmtPct(r.m6)}</dd>
    <dt>12 Monate ohne letzten Monat</dt><dd class="${cls(r.m12)}">${fmtPct(r.m12)}</dd>
    <dt>Teilscores 6 / 12 Monate</dt><dd>${fmtNum(r.z6, 2)} / ${fmtNum(r.z12, 2)}</dd>
    <dt>Performance 1 / 3 / 12 Monate</dt><dd>${fmtPct(r.ret_1m)} / ${fmtPct(r.ret_3m)} / ${fmtPct(r.ret_12m)}</dd>
    <dt>Seit Jahresbeginn</dt><dd class="${cls(r.ret_ytd)}">${fmtPct(r.ret_ytd)}</dd>
    <dt>Volatilität (3 J., wöchentlich)</dt><dd>${fmtPct(r.vol, 1, false)}</dd>
    <dt>Abstand 52-Wochen-Hoch</dt><dd>${fmtPct(r.dd_52w)}</dd>
    <dt>Max. Rückgang 12 Monate</dt><dd>${fmtPct(r.maxdd_1y)}</dd>
    <dt>200-Tage-Linie</dt><dd>${r.above_ma200 == null ? 'n. v.' : `${r.above_ma200 ? 'darüber' : 'darunter'} (${fmtPct(r.dist_ma200)})`}</dd>
    <dt>Liquidität (Median-Tagesumsatz)</dt><dd>${fmtCompact(r.liq_eur)} €</dd>
    <dt>Kurshistorie</dt><dd>${fmtNum(r.history_years, 1)} Jahre</dd>
    <dt>Gegenprüfung (iShares)</dt><dd>${r.verified === true ? `ok (${fmtPct(r.crosscheck_dev, 2)})` : r.verified === false ? `Abweichung ${fmtPct(r.crosscheck_dev, 1)}` : 'nicht verfügbar'}</dd>
  </dl></div>`);
  // Begründung
  if (isCand) {
    parts.push(html`<h2>Warum ausgewählt?</h2><div class="panel"><ul style="margin:0;padding-left:18px">${whySelected(r, screen).map((t) => html`<li style="margin-bottom:6px">${t}</li>`)}</ul></div>
      <h2>Warum besser als andere Kandidaten?</h2><div class="panel"><ul style="margin:0;padding-left:18px">${whyBetter(r, screen).map((t) => html`<li style="margin-bottom:6px">${t}</li>`)}</ul></div>`);
  } else {
    const why = [];
    if (!r.eligible) why.push(`Ausgeschlossen: ${(r.reasons || []).map((c) => reasonText(c, screen)).join(', ') || 'unbekannt'}.`);
    else {
      if (r.pct > (screen.params?.candidate_max_pct ?? 0.1)) why.push(`Rang ${r.rank} (${fmtRankPct(r.pct)}) liegt außerhalb des besten Zehntels.`);
      if (!(r.m6 > 0)) why.push('6-Monats-Momentum nicht positiv.');
      if (!(r.m12 > 0)) why.push('12-Monats-Momentum nicht positiv.');
      if (!why.length) why.push('Andere Aktien haben einen höheren Score. Es werden höchstens zehn ausgewählt.');
    }
    parts.push(html`<h2>Warum nicht in den Top 10?</h2><div class="panel"><ul style="margin:0;padding-left:18px">${why.map((t) => html`<li>${t}</li>`)}</ul></div>`);
  }
  parts.push(html`<h2>Risiken</h2><div class="panel">${flags.length ? html`<ul style="margin:0;padding-left:18px">${flags.map((f) => html`<li style="margin-bottom:6px;color:${f.level === 'hoch' ? 'var(--critical)' : f.level === 'mittel' ? 'var(--serious)' : 'var(--ink-2)'}">${f.text}</li>`)}</ul>` : html`<p class="muted" style="margin:0">Keine regelbasierten Risikohinweise.</p>`}
    <p class="xs muted" style="margin:10px 0 0">Risikohinweise ergänzen das Momentum-Screening. Sie verändern den Score nicht.</p></div>`);
  // Fundamentaldaten
  parts.push(html`<h2>Geschäftsmodell und Fundamentaldaten</h2>`);
  if (!d) parts.push(note('info', 'Für diese Aktie lädt der Datenlauf keine Detaildaten. Detaildaten gibt es für Kandidaten, die besten 50, frühere Kandidaten und die Beobachtungsliste.'));
  else if (!fm) parts.push(note('info', 'Keine Fundamentaldaten verfügbar.'));
  else {
    const m = fm.metrics;
    const tag = srcTag(fm.source === 'official' ? 'official' : fm.source === 'demo' ? 'demo' : 'database',
      fm.source === 'official' ? 'SEC-Bericht' : fm.source === 'demo' ? 'DEMO' : 'Yahoo');
    const u = fm.unit && fm.unit !== 'DEMO' ? fm.unit : '';
    parts.push(html`<div class="panel">
      ${fm.summary ? html`<p class="small">${fm.summary.length > 700 ? `${fm.summary.slice(0, 700)} …` : fm.summary} ${srcTag('database', 'Yahoo')}</p>` : ''}
      ${fm.sic ? html`<p class="small muted">Branche laut SEC: ${fm.sic} ${srcTag('official')}</p>` : ''}
      <dl class="kv small">
        <dt>Geschäftsjahr</dt><dd>${m.fiscal_year || 'letzte 12 Monate'} ${tag}</dd>
        <dt>Umsatz</dt><dd>${fmtCompact(m.revenue)} ${u}</dd>
        <dt>Umsatzwachstum</dt><dd class="${cls(m.revenue_growth)}">${fmtPct(m.revenue_growth)}</dd>
        ${m.revenue_cagr_3y != null ? html`<dt>Umsatzwachstum p. a. (3 J.)</dt><dd>${fmtPct(m.revenue_cagr_3y)}</dd>` : ''}
        <dt>Gewinn je Aktie (verwässert)</dt><dd>${fmtNum(m.eps_diluted, 2)}${m.eps_growth != null ? html` <span class="${cls(m.eps_growth)}">(${fmtPct(m.eps_growth)})</span>` : ''}</dd>
        <dt>Nettomarge</dt><dd>${fmtPct(m.net_margin, 1, false)}</dd>
        <dt>Operative Marge</dt><dd>${fmtPct(m.op_margin, 1, false)}</dd>
        ${m.gross_margin != null ? html`<dt>Bruttomarge</dt><dd>${fmtPct(m.gross_margin, 1, false)}</dd>` : ''}
        <dt>Free Cashflow</dt><dd>${fmtCompact(m.fcf)} ${u}${m.fcf_margin != null ? html` <span class="muted">(${fmtPct(m.fcf_margin, 1, false)})</span>` : ''}</dd>
        <dt>Eigenkapitalrendite</dt><dd>${fmtPct(m.roe, 1, false)}</dd>
        <dt>Verschuldung (Schulden/Eigenkapital)</dt><dd>${fmtNum(m.debt_to_equity, 2)}</dd>
        ${m.dilution != null ? html`<dt>Veränderung Aktienanzahl</dt><dd>${fmtPct(m.dilution)}</dd>` : ''}
        <dt>KGV</dt><dd>${fmtNum(m.pe, 1)}${fm.source === 'official' ? html` ${srcTag('calc')}` : ''}</dd>
        ${m.last_quarter ? html`<dt>Quartal ${m.last_quarter}: Umsatz ggü. Vorjahr</dt><dd class="${cls(m.q_revenue_growth)}">${fmtPct(m.q_revenue_growth)}</dd>` : ''}
        ${m.q_eps_growth != null ? html`<dt>Quartal: Gewinn je Aktie ggü. Vorjahr</dt><dd class="${cls(m.q_eps_growth)}">${fmtPct(m.q_eps_growth)}</dd>` : ''}
      </dl>
      ${fm.yahoo?.forwardEps ? html`<p class="small" style="margin-top:10px">Analystenschätzung Gewinn je Aktie (nächstes Jahr): ${fmtNum(fm.yahoo.forwardEps, 2)} ${srcTag('secondary', 'Schätzung')}</p>` : ''}
      ${fm.earningsDate ? html`<p class="small">Nächste Quartalszahlen: ${fmtDate(fm.earningsDate)} ${srcTag('database', 'Yahoo')}</p>` : ''}
      <p class="xs muted" style="margin:8px 0 0">Unternehmensprognosen (Guidance) gibt es nicht kostenlos in strukturierter Form. Sie stehen in den Quartalsberichten auf der Investor-Relations-Seite.${fm.yahoo?.website ? html` <a href="${safeUrl(fm.yahoo.website)}" target="_blank" rel="noopener">Website des Unternehmens</a>` : ''}</p>
    </div>`);
  }
  // Meldungen
  const filings = d?.fund?.sec_filings?.filings || [];
  const news = d?.news || [];
  if (filings.length || news.length) {
    parts.push(html`<h2>Unternehmensmeldungen</h2><div class="group">
      ${filings.slice(0, 6).map((f) => html`<a class="row" href="${safeUrl(f.url)}" target="_blank" rel="noopener"><div class="grow"><div class="title">${f.form}: ${f.title}</div><div class="sub">${fmtDate(f.date)}, SEC EDGAR ${srcTag('official', 'Pflichtmitteilung')}</div></div></a>`)}
      ${news.slice(0, 8).map((n) => html`<a class="row" href="${safeUrl(n.url)}" target="_blank" rel="noopener"><div class="grow"><div class="title" style="white-space:normal">${n.title}</div><div class="sub">${fmtDate(n.date)}, ${n.source} ${srcTag('secondary', 'Presse')}</div></div></a>`)}
    </div><p class="xs muted">Schlagzeilen werden angezeigt, aber nicht automatisch bewertet. Für eine verlässliche Auswertung gibt es keine wissenschaftlich belastbare, kostenlose Methode.</p>`);
  }
  const links = [[yahooUrl, 'Kursseite bei Yahoo Finance', 'database']];
  if (fm?.edgar) links.push([fm.edgar, 'Alle SEC-Berichte (EDGAR)', 'official']);
  links.push([`https://news.google.com/search?q=${encodeURIComponent(r.name)}`, 'Nachrichtensuche', 'secondary']);
  parts.push(html`<h2>Quellen</h2><div class="group">${links.map(([u, l, t]) => html`<a class="row" href="${safeUrl(u)}" target="_blank" rel="noopener"><div class="grow">${l} ${srcTag(t)}</div></a>`)}</div>`);
  parts.push(html`<div class="btn-row" style="margin:16px 0"><button class="btn primary" id="add">${held ? 'Transaktion erfassen' : 'Zum Depot hinzufügen'}</button>${held ? html`<a class="btn" href="#/position/${encodeURIComponent(held.id)}">Position öffnen</a>` : ''}</div>
    <div class="btn-row" style="margin:0 0 10px"><button class="btn" id="copyId">${/^[A-Z]{2}[A-Z0-9]{9}[0-9]$/.test(r.isin || '') ? `ISIN kopieren (${r.isin})` : 'Namen kopieren (ISIN nicht verfügbar)'}</button></div>
    <div class="btn-row" style="margin:0 0 16px"><button class="btn" id="hideTR">${isHidden ? 'Wieder einblenden' : 'Gibt es bei Trade Republic nicht'}</button></div>
    <p class="xs muted" style="margin-top:-8px">Die App nimmt nur Aktien auf, die an der Börse Frankfurt handelbar sind. Das passt gut, aber nicht zu 100 % zum Angebot von Trade Republic. Findest du eine Aktie dort nicht, blende sie hier aus: Der nächste Kandidat rückt nach. Wird nur auf deinem iPhone gespeichert.</p>`);
  root.innerHTML = parts.join('');
  const pts = d?.series || [];
  if (pts.length > 2) {
    lineChart(root.querySelector('#pchart'), {
      height: 210, xIsYear: false, label: `Kursverlauf ${r.name}`,
      yFmt: (v) => fmtNum(v, v >= 100 ? 0 : 2), tipFmt: (v) => fmtMoney(v, r.currency),
      series: [{ name: 'Kurs', short: 'Kurs', points: pts, color: 'var(--s1)' },
        ...(d.ma200_series?.length ? [{ name: '200-Tage-Linie', short: '200 T', points: d.ma200_series, color: 'var(--ink-3)', width: 1.5, dash: '4 3' }] : [])],
    });
  } else {
    root.querySelector('#pchart').innerHTML = '<p class="muted small" style="margin:0">Kein Kursverlauf in den Detaildaten. Detaildaten gibt es nur für Kandidaten, die besten 50, frühere Kandidaten und die Beobachtungsliste.</p>';
  }
  root.querySelector('#copyId').onclick = async (ev) => {
    const val = /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/.test(r.isin || '') ? r.isin : r.name;
    let ok = false;
    try { await navigator.clipboard.writeText(val); ok = true; } catch {
      const ta = document.createElement('textarea'); ta.value = val; document.body.appendChild(ta); ta.select();
      try { ok = document.execCommand('copy'); } catch { ok = false; }
      ta.remove();
    }
    ev.target.textContent = ok ? `Kopiert: ${val}` : `Kopieren nicht möglich: ${val}`;
  };
  root.querySelector('#hideTR').onclick = async () => {
    await setHidden(symbol, !isHidden);
    await refreshHidden();
    await render(root, symbol);
  };
  root.querySelector('#add').onclick = () => openTxForm({ preset: held ? { positionId: held.id } : { symbol, name: r.name, currency: r.currency, isin: r.isin, exchange: r.exchange } });
  void raw;
}

// Stage-2-Detailansicht auf der Aktienseite: Entscheidung, Kategorien, aufklappbare Fachabschnitte, Begründungen.
import { cls, fmtCompact, fmtDate, fmtNum, fmtPct, fmtSigned, ok } from '../fmt.js';
import { CAT_ORDER, bar10, decisionBadge, dqBadge, fmtMetric, outBadge, profile, riskBadge, scoreScale } from '../stage2.js';
import { chevron, html, note, srcTag } from '../ui.js';

const kv = (rows) => html`<dl class="kv small">${rows.filter(Boolean).map(([k, v, c]) => html`<dt>${k}</dt><dd class="${c || ''}">${v}</dd>`)}</dl>`;
const box = (title, body, open = false) => html`<details class="box" ${open ? 'open' : ''}><summary>${title}${chevron}</summary><div class="inner">${body}</div></details>`;
const pct = (x, d = 1) => fmtPct(x, d);
const RULE_NA = { fin: 'gilt nur für Banken und Versicherer', nonfin: 'nicht sinnvoll für Banken und Versicherer' };

function metricItem(m) {
  let refLine;
  if (!m.applicable) refLine = html`<span class="ref na">Nicht anwendbar (${RULE_NA[m.rule] || 'Branche'}), zählt weder positiv noch negativ.</span>`;
  else if (!m.active) refLine = html`<span class="ref na">Derzeit ohne ausreichende Vergleichsbasis, für alle Aktien ausgesetzt.</span>`;
  else if (m.missing) refLine = html`<span class="ref miss">Fehlt. Wird nicht geschätzt, sondern ausgelassen (senkt die Datenqualität).</span>`;
  else refLine = html`<span class="ref">Teilscore ${fmtNum(m.score, 1)} von 10 · ${m.dir < 0 ? 'niedriger ist besser · ' : ''}Vergleich: ${m.ref_label}</span>`;
  return html`<li><span>${m.label}</span><span class="v">${m.applicable ? fmtMetric(m.value, m.fmt) : '–'}</span>${refLine}</li>`;
}

export function categoriesHTML(e, weights) {
  return html`<div class="panel"><h3>Sechs Kategorien</h3><p class="xs muted" style="margin:0 0 4px">Antippen zeigt die Kennzahlen. Jede Kennzahl ist ein Perzentil gegenüber ihrer Vergleichsgruppe (0 = schwächster, 10 = stärkster Wert).</p>
    ${CAT_ORDER.map((c) => {
      const cat = e.categories?.[c];
      if (!cat) return '';
      return html`<details class="cat"><summary class="cat-row"><span class="cat-name">${c} ${cat.name}<span class="w">${fmtNum((weights?.[c] ?? cat.weight) * 100, 0)} %</span></span>
        <span class="num" style="font-weight:700">${cat.available ? fmtNum(cat.score, 1) : 'fehlt'}</span>${bar10(cat.available ? cat.score : null)}</summary>
        ${cat.available ? '' : html`<p class="xs" style="color:var(--warn);margin:0 0 6px">Nicht berechenbar: nur ${cat.n_available} von ${cat.n_applicable} Kennzahlen verfügbar (Mindestanforderung nicht erfüllt).</p>`}
        <ul class="metric-list">${cat.metrics.map(metricItem)}</ul></details>`;
    })}</div>`;
}

export function stage2DetailHTML(e, s2, use) {
  const parts = [html`<h2>Stage 2 – Fortsetzungsanalyse</h2>`];
  const d = e.decision || {};
  const sc = e.stage2?.score_display;
  const missing = CAT_ORDER.filter((c) => e.categories?.[c] && !e.categories[c].available).map((c) => e.categories[c].name);
  if (!use.ok) parts.push(note('warn', use.reason));
  parts.push(html`<div class="panel">
    <div class="s2-meta" style="margin-top:0">
      <div><div class="muted xs">Stage-2-Score${e.stage2?.rank ? `, Rang ${e.stage2.rank} von ${s2.ranking.length}` : ''}</div>
        <div class="s2-score">${sc != null ? fmtNum(sc, 1) : '–'}<span class="small muted" style="font-weight:500"> von 10</span></div></div>
      ${profile(e.categories)}</div>
    ${scoreScale(e.stage2?.score)}
    <div style="margin:12px 0 6px">${use.ok ? decisionBadge(d.code) : html`<span class="badge b-none">KEINE AKTUELLE ENTSCHEIDUNG</span>`}</div>
    <p class="small" style="margin:0 0 6px">${use.ok ? d.text : 'Die Entscheidung wird erst mit aktuellen Daten angezeigt.'}</p>
    ${use.ok && d.reasons?.length ? html`<ul class="text-list small muted">${d.reasons.map((t) => html`<li>${t}</li>`)}</ul>` : ''}
    <div class="chips" style="margin-top:8px">${outBadge(e.outperformance?.level, true)}${riskBadge(e.risk?.level)}${dqBadge(e.data_quality?.level)}</div>
    ${missing.length && sc != null ? html`<p class="xs" style="margin:8px 0 0;color:var(--warn)">Score ohne ${missing.join(', ')} berechnet: Die übrigen Kategorien wurden neu gewichtet (${fmtPct(e.stage2.weight_available, 0, false)} des Gesamtgewichts). Fehlende Werte werden nie geschätzt.</p>` : ''}
    <p class="xs muted" style="margin:8px 0 0">Outperformance-Potential und Entscheidung sind regelbasierte Research-Einschätzungen, keine Wahrscheinlichkeiten. Die Schwellen sind heuristisch und noch nicht validiert.</p>
  </div>`);
  parts.push(categoriesHTML(e, s2.weights));

  // MOMENTUM
  const mo = e.momentum || {};
  parts.push(box('Momentum', html`${kv([
    ['Performance 3 / 6 / 12 Monate', html`${pct(mo.ret_3m)} / ${pct(mo.ret_6m)} / ${pct(mo.ret_12m)}`],
    ['12–1 Monate (ohne letzten Monat)', pct(mo.m12_1), cls(mo.m12_1)],
    ['6–1 / 3–1 / 12–2 Monate', html`${pct(mo.m6_1)} / ${pct(mo.m3_1)} / ${pct(mo.m12_2)}`],
    ['Relative Stärke ggü. MSCI World 3 M', pct(mo.rs_world_3m), cls(mo.rs_world_3m)],
    ['Relative Stärke ggü. MSCI World 6 M', pct(mo.rs_world_6m), cls(mo.rs_world_6m)],
    ['Relative Stärke ggü. MSCI World 12 M', pct(mo.rs_world_12m), cls(mo.rs_world_12m)],
    ['Relative Stärke zum Sektor (6–1 M)', pct(mo.rs_sector), cls(mo.rs_sector)],
    [`Relative Stärke zum Heimatmarkt (${e.home_group || '–'})`, pct(mo.rs_home), cls(mo.rs_home)],
    ['Marktbereinigtes Momentum', fmtNum(mo.resid_mom, 2)],
    ['Monate besser als MSCI World', ok(mo.beat_n) ? `${mo.beat_n} von 12` : '–'],
    ['Beta zum MSCI World (36 M)', fmtNum(mo.beta_36m, 2)],
    ['Anteil positiver Monate (12–1)', fmtPct(mo.pos_months, 0, false)],
  ])}<p class="xs muted" style="margin:8px 0 0">Relative Stärke in Euro gegenüber ${s2.market?.name || 'dem MSCI-World-ETF'}. Sektor- und Heimatmarkt-Vergleich: gleichgewichteter Durchschnitt der zulässigen Aktien derselben Gruppe. ${srcTag('calc')}</p>`, true));

  // EARNINGS
  const ea = e.earnings || {};
  const hist = ea.surprise_hist || [];
  parts.push(box('Gewinne und Analystenrevisionen', html`${kv([
    ['Umsatzwachstum (Quartal ggü. Vorjahr)', pct(ea.rev_growth), cls(ea.rev_growth)],
    ['Gewinnwachstum je Aktie (Quartal ggü. Vorjahr)', pct(ea.eps_growth), cls(ea.eps_growth)],
    ['Gewinnüberraschung letztes Quartal', pct(ea.surprise_last), cls(ea.surprise_last)],
    ['Gewinnüberraschung Ø 4 Quartale', pct(ea.surprise4), cls(ea.surprise4)],
    ['Revisionsbreite 30 Tage', ok(ea.breadth30) ? fmtSigned(ea.breadth30, 2) : '–', cls(ea.breadth30)],
    ['Erhöhungen / Senkungen (30 Tage, lfd. Jahr)', ok(ea.analysts_0y) ? `${ea.up30 ?? 0} / ${ea.down30 ?? 0} bei ${ea.analysts_0y} Analysten` : '–'],
    [`EPS-Schätzung lfd. Geschäftsjahr${ea.eps_period_end ? ` (bis ${fmtDate(ea.eps_period_end)})` : ''}`, ok(ea.eps_now_0y) ? fmtNum(ea.eps_now_0y, 2) : '–'],
    ['… vor 30 / 60 / 90 Tagen', html`${fmtNum(ea.eps_30d_0y, 2)} / ${fmtNum(ea.eps_60d_0y, 2)} / ${fmtNum(ea.eps_90d_0y, 2)}`],
    ['Schätzungsänderung 30 / 90 Tage (Ø lfd. + nächstes Jahr)', html`${pct(ea.rev30)} / ${pct(ea.rev90)}`],
    ['Erwartetes Gewinnwachstum nächstes Jahr', pct(ea.exp_growth)],
    ['Veränderung operative Marge (Geschäftsjahr)', ok(ea.margin_change) ? `${fmtSigned(ea.margin_change * 100, 1)} Pp.` : '–'],
    ['Umsatzschätzung ggü. vor ca. 90 Tagen', ok(ea.rev_est90) ? pct(ea.rev_est90) : 'noch keine eigene Historie'],
    ['Unternehmensprognose (Guidance)', 'nicht verfügbar'],
    ['Nächste Quartalszahlen', ea.next_earnings ? fmtDate(ea.next_earnings) : '–'],
  ])}
  ${hist.length ? html`<p class="xs muted" style="margin:10px 0 4px">Letzte Quartale: Ist / Erwartung (Überraschung)</p><ul class="text-list xs">${hist.map((h) => html`<li>${fmtDate(h.quarter)}: ${fmtNum(h.eps_actual, 2)} / ${fmtNum(h.eps_est, 2)} (${pct(h.surprise)})</li>`)}</ul>` : ''}
  <p class="xs muted" style="margin:8px 0 0">Analystenschätzungen ${srcTag('secondary', 'Schätzung')} und Quartalszahlen über Yahoo Finance ${srcTag('database', 'Yahoo')}. Guidance gibt es nicht kostenlos in strukturierter Form; sie steht in den Quartalsberichten des Unternehmens.</p>`));

  // TREND
  const tr = e.trend || {};
  const cur = e.currency || '';
  parts.push(box('Trend', kv([
    ['Trendstatus', tr.status || '–'],
    ['50-Tage-Linie', ok(tr.ma50) ? html`${fmtNum(tr.ma50, 2)} ${cur} (Kurs ${pct(tr.dist_ma50)})` : '–'],
    ['200-Tage-Linie', ok(tr.ma200) ? html`${fmtNum(tr.ma200, 2)} ${cur} (Kurs ${pct(tr.dist_ma200)})` : '–'],
    ['Steigung 50 / 200 Tage (über 20 Tage)', html`${pct(tr.slope_ma50, 2)} / ${pct(tr.slope_ma200, 2)}`],
    ['Abstand zum 52-Wochen-Hoch', ok(tr.prox_52w) ? html`${pct(tr.prox_52w - 1)}${ok(tr.days_since_high) ? ` (Hoch vor ${tr.days_since_high} Tagen)` : ''}` : '–'],
    ['RSI (14 Tage)', fmtNum(tr.rsi14, 0)],
    ['Volatilität 3 Monate', fmtPct(tr.vol63, 0, false)],
    ['Maximaler Rückgang 12 Monate', pct(tr.mdd_12m)],
    ['Trendstabilität (R², 6 Monate)', fmtNum(tr.r2_6m, 2)],
    ['Monate mit höherem Hoch und Tief', fmtPct(tr.hh_hl, 0, false)],
    ['Abstand 50 / 200 Tage in Standardabweichungen', html`${fmtNum(tr.ext50, 1)} / ${fmtNum(tr.ext200, 1)}`],
    ['Beschleunigung letztes Quartal (Standardabw.)', fmtSigned(tr.z_acc, 1)],
  ])));

  // FUNDAMENTALS
  const fu = e.fundamentals || {};
  const fc = fu.currency || '';
  parts.push(box('Fundamentaldaten', html`${kv([
    ['Free Cashflow (12 M)', ok(fu.fcf) ? html`${fmtCompact(fu.fcf)} ${fc}` : '–'],
    ['Free-Cashflow-Marge', fmtPct(fu.fcf_margin, 1, false)],
    ['Operative Marge / Nettomarge', html`${fmtPct(fu.op_margin, 1, false)} / ${fmtPct(fu.profit_margin, 1, false)}`],
    ['Eigenkapitalrendite (ROE)', fmtPct(fu.roe, 1, false)],
    ['Gesamtkapitalrendite (ROA)', fmtPct(fu.roa, 1, false)],
    ['Kapitalrendite ROIC (EBIT / investiertes Kapital)', fmtPct(fu.roic_pre, 1, false)],
    ['Verschuldung (Schulden / Eigenkapital)', ok(fu.de) ? `${fmtNum(fu.de, 2)}×` : '–'],
    ['Zinsdeckung (EBIT / Zinsaufwand)', ok(fu.interest_cov) ? `${fmtNum(fu.interest_cov, 1)}×` : '–'],
    ['Veränderung der Aktienanzahl (1 Jahr)', pct(fu.dilution)],
    ['Qualitäts-Score (Kategorie E)', e.categories?.E?.available ? `${fmtNum(e.categories.E.score, 1)} von 10` : 'nicht berechenbar'],
    ['Letztes Geschäftsjahr', fu.fy_end ? fmtDate(fu.fy_end) : '–'],
  ])}<p class="xs muted" style="margin:8px 0 0">Kennzahlen über Yahoo Finance ${srcTag('database', 'Yahoo')}, Branchenvergleich innerhalb des GICS-Sektors. Wettbewerbsposition und Geschäftsmodell lassen sich nicht objektiv automatisch bewerten; dafür stehen unten die Quellen.</p>`));

  // VALUATION & RISK
  const va = e.valuation || {};
  const rk = e.risk || { flags: [] };
  const flagHTML = (list) => html`<ul class="flag-list">${list.map((f) => html`<li class="f-${String(f.group).split(' ')[0].toLowerCase()}">${f.text}<span class="g">${f.group}${f.counts === false ? ', nur Hinweis' : ''}</span></li>`)}</ul>`;
  const tech = rk.flags.filter((f) => String(f.group).startsWith('technisch'));
  const other = rk.flags.filter((f) => !String(f.group).startsWith('technisch'));
  parts.push(box('Bewertung und Risiko', html`${kv([
    ['KGV (12 M) / Forward-KGV', html`${fmtNum(va.pe_ttm, 1)} / ${fmtNum(va.pe_fwd, 1)}`],
    ['EV / EBITDA', fmtNum(va.ev_ebitda, 1)],
    ['KUV / KBV', html`${fmtNum(va.ps, 1)} / ${fmtNum(va.pb, 1)}`],
    ['PEG (Forward-KGV / erwartetes Wachstum)', fmtNum(va.peg, 2)],
    ['Forward-Bewertung im Sektor', ok(va.pe_fwd_pct_sector) ? `${fmtNum((1 - va.pe_fwd_pct_sector) * 100, 0)} % der Sektor-Aktien sind günstiger` : '–'],
    ['Risiko-Stufe', html`${riskBadge(rk.level)} <span class="xs muted">${rk.why || ''}</span>`],
  ])}
  <h3 style="margin-top:12px">Überhitzungswarnungen</h3>${tech.length ? flagHTML(tech) : html`<p class="small muted">Keine.</p>`}
  <h3>Weitere Risikoflags</h3>${other.length ? flagHTML(other) : html`<p class="small muted">Keine.</p>`}
  <p class="xs muted" style="margin:8px 0 0">Eine Aktie nahe ihrem Hoch ist nicht automatisch überbewertet. Überhitzung wird nur im Vergleich zu anderen Momentum-Aktien gemessen. CRITICAL (sinkende Gewinnerwartungen plus technische oder Bewertungsrisiken) blockiert jede Sparplanfreigabe.</p>`));

  // FINAL DECISION
  const t = e.texts || {};
  const pil = e.outperformance?.pillars || [];
  parts.push(html`<div class="panel"><h3>Warum ausgewählt</h3><ul class="text-list small">${(t.why_selected || []).map((x) => html`<li>${x}</li>`)}</ul>
    <h3 style="margin-top:12px">Größte Risiken</h3><ul class="text-list small">${(t.risks || []).map((x) => html`<li>${x}</li>`)}</ul>
    <h3 style="margin-top:12px">Warum sie den MSCI World übertreffen könnte</h3>
    <ul class="crit-list">${pil.map((p) => html`<li><span class="${p.ok === true ? 'ok' : p.ok === false ? 'no' : 'na'}">${p.ok === true ? '✓' : p.ok === false ? '✗' : '–'}</span><div>${p.label}<span class="v">${p.text}</span></div></li>`)}</ul>
    <p class="xs muted" style="margin:6px 0 0">${e.outperformance?.label || ''}: ${e.outperformance?.positives ?? 0} von ${e.outperformance?.evaluable ?? 0} prüfbaren Säulen erfüllt.</p>
    <h3 style="margin-top:12px">Was die These widerlegen würde</h3><ul class="text-list small">${(t.falsification || []).map((x) => html`<li>${x}</li>`)}</ul>
    ${t.vs_next ? html`<p class="small muted" style="margin:10px 0 0">Rangfolge: ${t.vs_next}</p>` : ''}</div>`);

  // Datenqualität und Quellen
  const dq = e.data_quality || {};
  const src = s2.sources || {};
  parts.push(box(html`Datenqualität und Quellen ${dqBadge(dq.level)}`, html`${kv([
    ['Status', dq.label || '–'],
    ['Verfügbare Kennzahlen (gewichtet)', fmtPct(dq.coverage, 0, false)],
    ['Kennzahlen Stand', dq.fund_asof ? `${fmtDate(dq.fund_asof)}${ok(dq.fund_age_days) ? ` (vor ${dq.fund_age_days} Tagen geladen)` : ''}` : 'keine'],
    ['Jahreswerte Stand', dq.ts_asof ? fmtDate(dq.ts_asof) : 'keine'],
    ['Kurs gegengeprüft (iShares)', dq.verified === true ? 'ja' : dq.verified === false ? 'nein' : 'nicht möglich'],
  ])}
  ${dq.missing?.length ? html`<p class="small" style="margin:10px 0 4px">Fehlende Kennzahlen:</p><ul class="text-list xs">${dq.missing.map((x) => html`<li>${x}</li>`)}</ul>` : ''}
  ${dq.notes?.length ? html`<ul class="text-list xs muted" style="margin-top:8px">${dq.notes.map((x) => html`<li>${x}</li>`)}</ul>` : ''}
  <p class="small" style="margin:10px 0 4px">Quellen</p>
  <ul class="text-list xs">${Object.values(src).map((v) => html`<li>${v.name} ${srcTag(v.type)}${v.asof ? `, Stand ${fmtDate(v.asof)}` : ''}</li>`)}</ul>`));
  return parts.join('');
}

export function stage2CompactHTML(c, s2) {
  const cats = Object.fromEntries(CAT_ORDER.map((k) => [k, { score: c[k], available: ok(c[k]) }]));
  return String(html`<h2>Stage 2 (Kurzfassung)</h2><div class="panel">
    <div class="s2-meta" style="margin-top:0"><div><div class="muted xs">Stage-2-Score</div><div class="s2-score">${ok(c.score) ? fmtNum(c.score, 1) : '–'}</div></div>${profile(cats)}</div>
    ${scoreScale(c.score, { label: false })}
    <div class="chips" style="margin-top:8px">${riskBadge(c.risk)}${dqBadge(c.dq)}</div>
    <dl class="kv small" style="margin-top:10px">${CAT_ORDER.map((k) => html`<dt>${k} ${s2.categories?.[k]?.name || ''}</dt><dd>${ok(c[k]) ? fmtNum(c[k], 1) : 'fehlt'}</dd>`)}</dl>
    <p class="xs muted" style="margin:10px 0 0">Die vollständige Analyse mit Sparplan-Entscheidung gibt es nur für die Stage-1-Kandidaten. Diese Aktie ist derzeit keiner.</p></div>`);
}

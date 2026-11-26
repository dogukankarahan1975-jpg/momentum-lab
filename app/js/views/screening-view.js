import { loadScreen, reasonText } from '../data.js';
import { fmtDate, fmtDateTime, fmtNum, fmtPct, fmtRankPct } from '../fmt.js';
import { runScreening, STEP_DEFS, STEP_GROUPS } from '../screening.js';
import { screenings, state } from '../state.js';
import { badge, chevron, empty, esc, html, note, openSheet } from '../ui.js';
import { refreshHeader } from '../main.js';

const ICON = { ok: '✓', warn: '!', err: '×', run: '…', wait: '', skip: '–' };
const ICLS = { ok: 'ok', warn: 'warn', err: 'err', run: 'run', wait: '', skip: '' };

function stepsHTML(steps) {
  let prev = null;
  return html`<ol class="steps">${steps.map((s) => {
    const head = s.group && s.group !== prev ? html`<li class="grp" aria-hidden="true">${STEP_GROUPS[s.group] || ''}</li>` : '';
    prev = s.group || prev;
    return html`${head}<li>
    <span class="step-ic ${ICLS[s.state] || ''}">${s.state === 'run' ? html`<span class="spinner" style="width:12px;height:12px"></span>` : ICON[s.state] ?? ''}</span>
    <div><div class="t">${s.label}</div>${s.detail ? html`<div class="d">${s.detail}</div>` : ''}</div></li>`;
  })}</ol>`;
}

export async function render(root) {
  const history = await screenings();
  const last = history[0] || null;
  const showLast = last?.steps?.length === STEP_DEFS.length;
  root.innerHTML = String(html`<h1>Screening</h1>
    <p class="lede">Lädt den neuesten geprüften Datenstand, prüft ihn auf Aktualität und Fehler, wendet die Momentum-Regeln an (Stage 1), zeigt die Fortsetzungsanalyse der Kandidaten (Stage 2) und bewertet dein Depot. Ergebnisse werden mit Datum und Methodik-Version gespeichert.</p>
    <button class="screen-btn" id="run">SCREENING STARTEN</button>
    <div id="result" style="margin-top:14px"></div>
    <section class="panel" id="steps-panel"><h3>Ablauf</h3><div id="steps">${stepsHTML(showLast ? last.steps : STEP_DEFS.map(([, group, label]) => ({ label, group, state: 'wait' })))}</div>
      ${showLast ? html`<p class="xs muted" style="margin-top:8px">Angezeigt: letztes Screening vom ${fmtDateTime(last.createdAt)}</p>` : ''}</section>
    <h2>Universum und Ausschlüsse</h2>
    <div id="universe"><p class="muted small">Wird nach dem Laden der Daten angezeigt.</p></div>
    <h2>Frühere Screenings</h2>
    <div id="history"></div>`);
  const btn = root.querySelector('#run');
  const resEl = root.querySelector('#result');
  const stepsEl = root.querySelector('#steps');
  renderHistory(root.querySelector('#history'), history);
  const doRun = async () => {
    btn.disabled = true;
    btn.textContent = 'SCREENING LÄUFT …';
    resEl.innerHTML = '';
    const res = await runScreening({ positions: state.positions, txs: state.txs, plans: state.plans, settings: state.settings,
      onStep: (steps) => { stepsEl.innerHTML = String(stepsHTML(steps)); } });
    btn.disabled = false;
    btn.textContent = 'SCREENING STARTEN';
    refreshHeader();
    if (res.error) {
      resEl.innerHTML = String(note('error', `Screening abgebrochen: ${res.error}. Es wurden keine Empfehlungen erzeugt.`));
      return;
    }
    const s = res.snapshot;
    const warn = res.steps.filter((x) => x.state === 'warn').length;
    resEl.innerHTML = String(html`${s.demo ? html`<div class="demo-banner">DEMO-DATEN – keine echten Signale</div>` : ''}
      ${note(warn ? 'warn' : 'ok', html`<b>${s.candidates.length ? `${s.candidates.length} Kandidaten gefunden` : 'Keine Kandidaten'}</b>${s.top_pick ? `, Top Pick ${res.screen.bySymbol.get(s.top_pick)?.name}` : ', kein Top Pick'}. ${s.stage2?.usable ? `Stage 2 Top 5: ${(s.stage2.ranking || []).filter((x) => x.buy).map((x) => x.name).join(', ')}. ` : ''}Datenstand ${fmtDate(s.asof)}${warn ? `. ${warn} Hinweise im Ablauf` : ''}.`)}
      <div class="btn-row"><a class="btn primary" href="#/top10/final">Stage 2: Top 5</a><a class="btn" href="#/top10/stage1">Top 10 (Stage 1)</a><a class="btn" href="#/signale">Depot-Signale</a></div>`);
    renderUniverse(root.querySelector('#universe'), res.screen);
    renderHistory(root.querySelector('#history'), await screenings());
  };
  btn.onclick = doRun;
  if (sessionStorage.getItem('autorun') === '1') { sessionStorage.removeItem('autorun'); doRun(); return; }
  try { renderUniverse(root.querySelector('#universe'), await loadScreen()); } catch (e) {
    root.querySelector('#universe').innerHTML = String(note('warn', e.message));
  }
}

const FILTERS = [['all', 'Alle'], ['elig', 'Zulässig'], ['excl', 'Ausgeschlossen'], ['data', 'Datenprobleme']];
function renderUniverse(el, screen) {
  let filter = 'all', q = '', limit = 60;
  const DATA = new Set(['no_data', 'stale', 'gaps', 'jump', 'adj_ratio', 'crosscheck', 'currency']);
  const ex = screen.universe.excluded_by_reason || {};
  const draw = () => {
    const term = q.trim().toLowerCase();
    let rows = screen.rows.filter((r) => {
      if (filter === 'elig' && !r.eligible) return false;
      if (filter === 'excl' && r.eligible) return false;
      if (filter === 'data' && !(r.reasons || []).some((c) => DATA.has(c))) return false;
      if (term && !(`${r.name} ${r.symbol} ${r.isin || ''}`.toLowerCase().includes(term))) return false;
      return true;
    });
    rows.sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9) || String(a.name).localeCompare(String(b.name)));
    const shown = rows.slice(0, limit);
    el.querySelector('#ulist').innerHTML = String(html`${shown.map((r) => html`<a class="row" href="#/aktie/${encodeURIComponent(r.symbol)}">
      <div class="grow"><div class="title">${r.rank ? `${r.rank}. ` : ''}${r.name}</div>
      <div class="sub">${r.symbol}, ${r.country}${r.eligible ? '' : ` – ${(r.reasons || []).map((c) => reasonText(c, screen)).join(', ')}`}</div></div>
      <div class="end small">${r.rank ? html`<div>${fmtNum(r.Z, 2)}</div><div class="muted xs">${fmtRankPct(r.pct)}</div>` : html`<span class="muted xs">ohne Rang</span>`}</div></a>`)}
      ${rows.length > limit ? html`<button class="row" id="more"><div class="grow muted">Weitere ${rows.length - limit} anzeigen</div></button>` : ''}
      ${rows.length === 0 ? html`<div class="row"><span class="muted">Keine Treffer.</span></div>` : ''}`);
    el.querySelector('#ucount').textContent = `${rows.length} Aktien`;
    const more = el.querySelector('#more');
    if (more) more.onclick = () => { limit += 200; draw(); };
  };
  el.innerHTML = String(html`<div class="panel"><dl class="kv">
      <dt>Quelle</dt><dd>${screen.universe.source}</dd>
      <dt>Stand der Liste</dt><dd>${screen.universe.as_of || '–'}</dd>
      <dt>Aktien im Universum</dt><dd>${screen.universe.size}</dd>
      <dt>Mit Kursdaten</dt><dd>${screen.universe.priced}</dd>
      <dt>Zulässig nach allen Regeln</dt><dd>${screen.universe.eligible}</dd>
    </dl>
    ${Object.keys(ex).length ? html`<details class="more"><summary>Ausschlussgründe anzeigen</summary><dl class="kv">${Object.entries(ex).sort((a, b) => b[1] - a[1]).map(([c, n]) => html`<dt>${reasonText(c, screen)}</dt><dd>${n}</dd>`)}</dl></details>` : ''}
    <p class="xs muted" style="margin-top:8px">Survivorship Bias: Die Liste enthält die heutigen Indexmitglieder. Ab jetzt archiviert der Datenlauf die Liste monatlich, damit spätere Auswertungen auch ausgeschiedene Aktien kennen.</p></div>
    <label class="field"><span>Suche (Name, Ticker, ISIN)</span><input id="uq" type="search" placeholder="z. B. SAP oder US0378331005" autocomplete="off"></label>
    <div class="seg" role="group" aria-label="Filter">${FILTERS.map(([k, l]) => html`<button data-f="${k}" aria-pressed="${k === filter}">${l}</button>`)}</div>
    <p class="xs muted" id="ucount"></p><div class="group" id="ulist"></div>`);
  el.querySelector('#uq').oninput = (e) => { q = e.target.value; limit = 60; draw(); };
  el.querySelectorAll('[data-f]').forEach((b) => { b.onclick = () => { filter = b.dataset.f; limit = 60; el.querySelectorAll('[data-f]').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); draw(); }; });
  draw();
}

function renderHistory(el, list) {
  if (!list.length) { el.innerHTML = String(empty('Noch keine Screenings', 'Jedes Screening wird hier mit Datum, Datenstand und Methodik-Version gespeichert.')); return; }
  el.innerHTML = String(html`<div class="group">${list.slice(0, 30).map((s) => html`<button class="row" data-id="${s.id}">
    <div class="grow"><div class="title">${fmtDateTime(s.createdAt)}</div><div class="sub">Daten ${fmtDate(s.asof)}, Methodik v${s.methodology_version}, ${s.candidates.length} Kandidaten${s.demo ? ', DEMO' : ''}</div></div>${chevron}</button>`)}</div>`);
  el.querySelectorAll('[data-id]').forEach((b) => { b.onclick = () => showSnapshot(list.find((x) => x.id === b.dataset.id)); });
}

function showSnapshot(s) {
  openSheet({ title: `Screening vom ${fmtDate(s.createdAt.slice(0, 10))}`, body: String(html`
    <dl class="kv"><dt>Datenstand</dt><dd>${fmtDate(s.asof)}</dd><dt>Berechnet</dt><dd>${fmtDateTime(s.generated_at)}</dd>
    <dt>Methodik</dt><dd>v${s.methodology_version} (${s.params_hash})</dd><dt>Datenstatus</dt><dd>${s.status}</dd></dl>
    <h3 style="margin-top:14px">Kandidaten</h3>
    ${s.candidates.length ? html`<div class="group">${s.candidates.map((c, i) => html`<div class="row"><div class="grow"><div class="title">${i + 1}. ${c.name}${c.symbol === s.top_pick ? ' (Top Pick)' : ''}</div><div class="sub">${c.symbol}, Score ${fmtNum(c.Z, 2)}, 12 M ${fmtPct(c.m12)}</div></div></div>`)}</div>` : html`<p class="muted">Keine Kandidaten.</p>`}
    <h3>Depot-Signale</h3>
    ${s.signals.length ? html`<div class="group">${s.signals.map((x) => html`<div class="row"><div class="grow"><div class="title">${x.name}</div><div class="sub">${x.reasons?.[0] || ''}</div></div><div class="end">${badge(x.signal)}${x.plan ? html`<div style="margin-top:4px">${badge(x.plan.signal)}</div>` : ''}</div></div>`)}</div>` : html`<p class="muted">Keine Positionen.</p>`}
    ${s.stage2 ? html`<h3>Stage 2</h3><div class="group">${s.stage2.ranking.map((x) => html`<div class="row"><div class="grow"><div class="title">${x.rank ?? '–'}. ${x.name}</div><div class="sub">Score ${x.score ?? '–'}</div></div><div class="end small">${x.buy ? 'Top 5' : ''}</div></div>`)}</div>` : ''}
    <h3>Ablauf</h3>${stepsHTML(s.steps || [])}`) });
  void esc;
}

// Einstieg: Router, Service Worker, Kopfzeile mit Datenstand.
import { freshness, loadStatus } from './data.js';
import { fmtDate } from './fmt.js';
import { openDB, requestPersist, getSetting, setSetting } from './store.js';
import { state, reloadDepot, reloadSettings } from './state.js';
import { esc, note, toast } from './ui.js';

const ROUTES = [
  [/^#?\/?$/, 'dashboard', 'dashboard'],
  [/^#\/screening$/, 'screening', 'screening'],
  [/^#\/top10$/, 'top10', 'top10'],
  [/^#\/top10\/(final|stage1)$/, 'top10', 'top10'],
  [/^#\/aktie\/(.+)$/, 'stock', 'top10'],
  [/^#\/depot$/, 'depot', 'depot'],
  [/^#\/position\/(.+)$/, 'position', 'depot'],
  [/^#\/signale$/, 'signals', 'signals'],
  [/^#\/backtest$/, 'backtest', 'dashboard'],
  [/^#\/rechner$/, 'calculator', 'depot'],
  [/^#\/einstellungen$/, 'settings', 'dashboard'],
];
const VIEWS = {
  dashboard: () => import('./views/dashboard.js'),
  screening: () => import('./views/screening-view.js'),
  top10: () => import('./views/top10.js'),
  stock: () => import('./views/stock.js'),
  depot: () => import('./views/depot-view.js'),
  position: () => import('./views/position.js'),
  signals: () => import('./views/signals-view.js'),
  backtest: () => import('./views/backtest.js'),
  calculator: () => import('./views/calculator.js'),
  settings: () => import('./views/settings.js'),
};

const main = document.getElementById('view');
let renderSeq = 0;

async function render() {
  const seq = ++renderSeq;
  const hash = location.hash || '#/';
  let match = null;
  for (const [re, view, tab] of ROUTES) {
    const m = hash.match(re);
    if (m) { match = { view, tab, params: m.slice(1).map(decodeURIComponent) }; break; }
  }
  if (!match) match = { view: 'dashboard', tab: 'dashboard', params: [] };
  document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-current', t.dataset.tab === match.tab ? 'page' : 'false'));
  main.innerHTML = '<p class="muted" style="padding:24px 0"><span class="spinner"></span> Lädt …</p>';
  try {
    const mod = await VIEWS[match.view]();
    if (seq !== renderSeq) return;
    main.innerHTML = '';
    await mod.render(main, ...match.params);
    if (seq === renderSeq) window.scrollTo(0, 0);
  } catch (e) {
    console.error(e);
    if (seq !== renderSeq) return;
    main.innerHTML = String(note('error', `Diese Ansicht konnte nicht geladen werden: ${e?.message || e}`));
  }
}

export async function refreshHeader() {
  const pill = document.getElementById('data-pill');
  try {
    const st = await loadStatus(true);
    const fr = freshness(st.asof);
    const bad = st.overall === 'fehler' || fr.abort;
    const warn = st.overall === 'warnung' || !fr.ok;
    const color = bad ? 'var(--critical)' : warn ? 'var(--warn)' : 'var(--good)';
    pill.innerHTML = `<span class="dot" style="background:${color}"></span>${st.demo ? 'DEMO ' : ''}${st.asof ? esc(fmtDate(st.asof).slice(0, 6)) : 'keine Daten'}`;
    pill.setAttribute('aria-label', `Datenstand ${fmtDate(st.asof)}, ${bad ? 'Fehler' : warn ? 'Warnung' : 'aktuell'}`);
  } catch {
    pill.innerHTML = '<span class="dot" style="background:var(--ink-3)"></span>offline';
  }
}

function setupSW() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('sw.js').then((reg) => {
    reg.addEventListener('updatefound', () => {
      const nw = reg.installing;
      nw?.addEventListener('statechange', () => {
        if (nw.state === 'installed' && navigator.serviceWorker.controller) {
          const bar = document.getElementById('update-bar');
          bar.hidden = false;
          bar.onclick = () => { nw.postMessage('skipWaiting'); };
        }
      });
    });
  }).catch(() => { /* lokal ohne HTTPS ok */ });
  let reloaded = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => { if (!reloaded) { reloaded = true; location.reload(); } });
}

async function boot() {
  try {
    await openDB();
  } catch (e) {
    main.innerHTML = String(note('error', `Lokaler Speicher nicht verfügbar (${e.message}). Bitte Safari verwenden und den privaten Modus ausschalten.`));
    return;
  }
  await reloadSettings();
  await reloadDepot();
  state.booted = true;
  window.addEventListener('hashchange', render);
  render();
  refreshHeader();
  setupSW();
  const standalone = window.matchMedia?.('(display-mode: standalone)').matches || navigator.standalone === true;
  if (standalone && !(await getSetting('persistAsked', false))) {
    const ok = await requestPersist();
    await setSetting('persistAsked', true);
    if (ok) toast('Speicher als dauerhaft markiert');
  }
}
boot();

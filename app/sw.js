// Service Worker: App-Dateien offline verfügbar, Daten immer zuerst aus dem Netz.
// Build-Kennung und Dateiliste werden beim Veröffentlichen eingesetzt (tools/build_site.py).
const BUILD = '__BUILD__';
const SHELL_CACHE = `ml-shell-${BUILD}`;
const DATA_CACHE = 'ml-data';
const FILES = __FILES__;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(FILES)).catch(() => undefined));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k.startsWith('ml-shell-') && k !== SHELL_CACHE).map((k) => caches.delete(k)),
  )).then(() => self.clients.claim()));
});
self.addEventListener('message', (e) => { if (e.data === 'skipWaiting') self.skipWaiting(); });

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes('/data/')) {
    const key = url.origin + url.pathname;
    e.respondWith(fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(DATA_CACHE).then((c) => c.put(key, copy)); }
      return res;
    }).catch(() => caches.open(DATA_CACHE).then((c) => c.match(key)).then((r) => r || Response.error())));
    return;
  }
  e.respondWith(caches.open(SHELL_CACHE).then((c) => c.match(req, { ignoreSearch: true }).then((hit) => hit || fetch(req).then((res) => {
    if (res.ok && url.pathname.match(/\.(js|css|html|png|webmanifest)$|\/$/)) c.put(req, res.clone());
    return res;
  }))));
});

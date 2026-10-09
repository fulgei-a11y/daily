/* Service worker della Rassegna ER.
   - Pagina, archivio ed edizioni: prima la rete (sempre l'ultima versione), la copia salvata solo senza connessione.
   - Icone e caratteri: dalla copia salvata (cambiano di rado).
   - Audio MP3: sempre dalla rete (file grandi, letti a pezzi dal lettore). */
const VERSION = 'rassegna-v1';
const CORE = ['./', 'index.html', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/favicon-64.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.pathname.endsWith('.mp3') || req.headers.has('range')) return;

  const isFont = /fonts\.(googleapis|gstatic)\.com$/.test(url.hostname);
  const sameOrigin = url.origin === self.location.origin;
  if (!sameOrigin && !isFont) return;

  if (isFont || url.pathname.includes('/icons/')) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      if (res.ok || res.type === 'opaque') { const copy = res.clone(); caches.open(VERSION).then(c => c.put(req, copy)); }
      return res;
    })));
    return;
  }

  // la pagina chiede i file con ?v=orario per evitare la cache del browser: li salviamo senza
  const key = new Request(url.origin + url.pathname);
  e.respondWith(fetch(req).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(VERSION).then(c => c.put(key, copy)); }
    return res;
  }).catch(() => caches.match(key).then(hit => hit ||
    (req.mode === 'navigate' ? caches.match('./') : Response.error()))));
});

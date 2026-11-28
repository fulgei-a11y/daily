/* Service worker di Daily.
   - Pagina, archivio ed edizioni: prima la rete (sempre l'ultima versione), la copia salvata solo senza connessione.
   - Icone e caratteri (serviti dal sito, niente richieste ad altri): dalla copia salvata.
   - File grandi (gli audio): sempre dalla rete, non si salvano. */
const VERSION = 'cache-v7';
const CORE = ['./', 'index.html', 'app.bin', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/favicon-64.png', 'fonts/fonts.css'];
const BIG = 1500000;

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

  if (url.origin !== self.location.origin) return;

  if (url.pathname.includes('/icons/') || url.pathname.includes('/fonts/')) {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(VERSION).then(c => c.put(req, copy)); }
      return res;
    })));
    return;
  }

  // la pagina chiede i file con ?v=orario per evitare la cache del browser: li salviamo senza
  const key = new Request(url.origin + url.pathname);
  e.respondWith(fetch(req).then(res => {
    const size = +(res.headers.get('content-length') || 0);
    if (res.ok && size < BIG) { const copy = res.clone(); caches.open(VERSION).then(c => c.put(key, copy)); }
    return res;
  }).catch(() => caches.match(key).then(hit => hit ||
    (req.mode === 'navigate' ? caches.match('./') : Response.error()))));
});

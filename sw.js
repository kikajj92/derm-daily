/* derm-daily service worker: app shell offline, photos cached forever, new exams fetched fresh */
const V = 'dd-v1';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icons/icon-192.png', './data/salt.json'];
self.addEventListener('install', e => { e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const req = e.request; const u = new URL(req.url);
  if (req.method !== 'GET' || u.origin !== location.origin) return;
  const fresh = req.mode === 'navigate' || /\/(index\.html|index\.json)$/.test(u.pathname) || u.pathname.endsWith('/') || /\/data\/exams\//.test(u.pathname);
  if (fresh) {
    e.respondWith(fetch(req).then(r => { if (r.ok) { const c = r.clone(); caches.open(V).then(x => x.put(req, c)); } return r; }).catch(() => caches.match(req, { ignoreSearch: true }).then(r => r || caches.match('./index.html'))));
  } else {
    e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(r => { if (r.ok) { const c = r.clone(); caches.open(V).then(x => x.put(req, c)); } return r; })));
  }
});

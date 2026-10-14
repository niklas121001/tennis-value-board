// Service Worker: macht das Board als App installierbar. Immer zuerst das Netz (frische Quoten),
// nur ohne Verbindung die zuletzt geladene Fassung aus dem Zwischenspeicher.
const CACHE = "tvb-v1";
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then(res => {
    if (res.ok) { const kopie = res.clone(); caches.open(CACHE).then(c => c.put(req, kopie)); }
    return res;
  }).catch(() => caches.match(req, {ignoreSearch: true})));
});

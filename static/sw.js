// Keeps the app shell available when the network drops. Game data (/api/) is never cached.
const CACHE = "hd-shell-v3";
const SHELL = ["/", "/static/fonts/inter-400.woff", "/static/fonts/inter-500.woff", "/static/fonts/inter-600.woff",
  "/static/fonts/inter-700.woff", "/static/fonts/bricolage-700.woff", "/static/icons/icon-192.png", "/static/brawl.js"];
self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
});
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
  e.respondWith(fetch(e.request).then(r => {   // network first, so updates always win
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request).then(r => r || caches.match("/"))));
});

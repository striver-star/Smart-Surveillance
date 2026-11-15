/* Wall service worker: keeps the wall page and its scripts on the wall PC, so a reload or a restart of
   the wall PC during a server outage still opens the wall (with its last layout, kept by wall.js).
   Network first, so changes on the server are picked up as soon as it answers; the API and the video
   streams are never cached. */
"use strict";
const CACHE = "hss-wall-v1";
const SHELL = ["/wall/", "/wall/wall.js", "/player.js"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function shellKey(url) {
  if (url.pathname === "/player.js" || url.pathname === "/wall/wall.js") return url.pathname;
  if (url.pathname.startsWith("/wall/") && !/\.\w+$/.test(url.pathname)) return "/wall/";   // the page, with any ?s=&k=
  if (url.pathname === "/wall/index.html") return "/wall/";
  return null;
}

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  const key = shellKey(url);
  if (!key) return;                                   // API, streams and everything else: straight to the network
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), 6000);
      const r = await fetch(e.request, { signal: ctl.signal, cache: "no-store" });
      clearTimeout(t);
      if (r.ok) { cache.put(key, r.clone()); return r; }
      const hit = await cache.match(key);              // 502 from the proxy while the server restarts
      return hit || r;
    } catch (_) {
      const hit = await cache.match(key);
      if (hit) return hit;
      throw _;
    }
  })());
});

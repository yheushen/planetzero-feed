// Planet Zero's service worker (session 7e, part 114). It keeps Earth's picture of the day on the device until the next day's, so a
// second visit draws the globe at once. It answers nothing else: every other request goes to the network as before, and the feed's
// numbers keep their own rules (never an old value shown as new). The page puts the picture in the same store itself (DAY_CACHE in
// web/src/earth/base.ts), since on a first visit this worker starts only after the picture was asked for.
const CACHE = 'pz-day-picture-v1'
const PICTURE = /\/earth\/real\/(\d{4}-\d\d-\d\d)-\d+\.(webp|jpg)$/

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return
  const m = PICTURE.exec(new URL(e.request.url).pathname)
  if (!m) return
  e.respondWith(
    (async () => {
      const cache = await caches.open(CACHE)
      const hit = await cache.match(e.request.url)
      if (hit) return hit
      const r = await fetch(e.request)
      if (r.ok) {
        await cache.put(e.request.url, r.clone())
        // only the newest day's picture is kept
        for (const k of await cache.keys()) {
          const d = PICTURE.exec(new URL(k.url).pathname)
          if (d && d[1] < m[1]) await cache.delete(k)
        }
      }
      return r
    })(),
  )
})

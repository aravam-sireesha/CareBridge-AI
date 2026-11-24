/* CareBridge service worker.
 *
 * What it does:  shows Web Push notifications, opens the right page when one is tapped, and shows an offline page when a page cannot be
 *                loaded. It also keeps the app's own static files (icons, fonts, hashed JS/CSS) so repeat visits start fast.
 * What it NEVER does: it never touches /api/ (private, signed-in data, and the live event stream), never caches HTML pages, and never
 *                stores anything a person typed. Pages are always fetched fresh; only when the network fails does it show offline.html.
 * Plain script (service workers have no module support in every browser): tested by running it against a fake worker scope
 * (tests/service-worker.test.jsx).
 */
const VERSION = 'v1'
const SHELL_CACHE = `cb-shell-${VERSION}`
const STATIC_CACHE = `cb-static-${VERSION}`
const OFFLINE_URL = '/offline.html'
const PRECACHE = [OFFLINE_URL, '/icons/icon-192.png', '/icons/badge-96.png', '/favicon.svg']
const STATIC_LIMIT = 80

/** Only same-site paths may be opened from a notification. Anything else falls back to the notifications page. */
function safeUrl(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.includes('\\') || /[\u0000-\u001f]/.test(value)) return '/notifications'
  return value.slice(0, 300)
}

function parsePush(event) {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch (e) { data = {} }       // a malformed payload still shows a generic notice (the browser requires one)
  if (!data || typeof data !== 'object') data = {}
  const text = (v, max) => (typeof v === 'string' ? v.replace(/\s+/g, ' ').trim().slice(0, max) : '')
  return {
    title: text(data.title, 80) || 'CareBridge',
    body: text(data.body, 160) || 'Open CareBridge for details.',
    tag: text(data.tag, 40) || 'cb-general',
    url: safeUrl(data.url),
  }
}

function isStaticAsset(url) {
  return url.pathname.startsWith('/assets/') || url.pathname.startsWith('/icons/') || url.pathname.startsWith('/images/') || url.pathname === '/favicon.svg'
}

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName)
  const keys = await cache.keys()
  for (let i = 0; i < keys.length - max; i++) await cache.delete(keys[i])
}

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => n.startsWith('cb-') && n !== SHELL_CACHE && n !== STATIC_CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return                  // third-party (maps, fonts, tiles) is the browser's business
  if (url.pathname.startsWith('/api/')) return                     // private data and the live stream: straight to the network, never cached
  if (request.mode === 'navigate') {                               // a page: always fresh; offline page only if the network fails
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)))
    return
  }
  if (isStaticAsset(url)) {                                        // content-hashed or rarely changing files: cache first
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((res) => {
        if (res && res.ok && res.type === 'basic') {
          const copy = res.clone()
          caches.open(STATIC_CACHE).then((c) => c.put(request, copy)).then(() => trim(STATIC_CACHE, STATIC_LIMIT)).catch(() => {})
        }
        return res
      })),
    )
  }
})

self.addEventListener('push', (event) => {
  const n = parsePush(event)
  event.waitUntil(self.registration.showNotification(n.title, {
    body: n.body, tag: n.tag, icon: '/icons/icon-192.png', badge: '/icons/badge-96.png', data: { url: n.url },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(safeUrl(event.notification.data && event.notification.data.url), self.location.origin).href
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const open = list.find((c) => new URL(c.url).origin === self.location.origin)
      if (open) return open.focus().then((c) => (c && c.navigate ? c.navigate(target).catch(() => self.clients.openWindow(target)) : null))
      return self.clients.openWindow(target)
    }),
  )
})

// The push service rotated this device's subscription: ask any open page to subscribe again (a worker cannot sign in on its own).
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => list.forEach((c) => c.postMessage({ type: 'cb:resubscribe' }))))
})

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting()
})

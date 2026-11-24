import { describe, it, expect, vi } from 'vitest'
import fs from 'node:fs'
import vm from 'node:vm'

const SOURCE = fs.readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8')
const ORIGIN = 'https://app.example.org'

/** Runs the REAL sw.js in an isolated context with a fake worker scope, and lets tests fire its events. */
function makeWorker({ network = async () => new Response('net', { status: 200 }) } = {}) {
  const handlers = {}, stores = new Map(), shown = [], opened = [], messages = [], fetched = []
  let skipped = 0, claimed = 0
  const cacheApi = (name) => {
    if (!stores.has(name)) stores.set(name, new Map())
    const m = stores.get(name)
    return {
      addAll: async (urls) => urls.forEach((u) => m.set(new URL(u, ORIGIN).href, { url: u })),
      put: async (req, res) => { m.set(typeof req === 'string' ? new URL(req, ORIGIN).href : req.url, res) },
      keys: async () => [...m.keys()].map((url) => ({ url })),
      delete: async (req) => m.delete(req.url ?? req),
    }
  }
  const caches = {
    open: async (n) => cacheApi(n),
    keys: async () => [...stores.keys()],
    delete: async (n) => stores.delete(n),
    match: async (req) => { const k = typeof req === 'string' ? new URL(req, ORIGIN).href : req.url; for (const m of stores.values()) if (m.has(k)) return m.get(k); return undefined },
  }
  const clientList = []
  const scope = {
    location: new URL(`${ORIGIN}/sw.js`),
    addEventListener: (type, fn) => { handlers[type] = fn },
    skipWaiting: () => { skipped++; return Promise.resolve() },
    registration: { showNotification: async (title, opts) => { shown.push({ title, ...opts }) } },
    clients: { claim: async () => { claimed++ }, matchAll: async () => clientList, openWindow: async (u) => { opened.push(u) } },
  }
  const fetchFn = async (req) => { fetched.push(req.url); return network(req) }
  vm.runInNewContext(SOURCE, { self: scope, caches, fetch: fetchFn, URL, Promise, Response, console, setTimeout })
  const fire = async (type, props = {}) => {
    const waits = []; let responded
    const event = { waitUntil: (p) => waits.push(p), respondWith: (p) => { responded = p }, ...props }
    handlers[type]?.(event)
    await Promise.all(waits)
    return { responded, response: responded ? await responded : undefined, handled: responded !== undefined || waits.length > 0 }
  }
  return { fire, stores, shown, opened, messages, fetched, clientList, handlers, get skipped() { return skipped }, get claimed() { return claimed } }
}
const req = (path, extra = {}) => ({ url: `${ORIGIN}${path}`, method: 'GET', mode: 'cors', ...extra })
const res = (extra = {}) => ({ ok: true, type: 'basic', status: 200, clone() { return this }, ...extra })
const pushEvent = (obj, raw) => ({ data: { json: () => { if (raw) throw new SyntaxError('bad json'); return obj } } })

describe('install / activate', () => {
  it('precaches the offline page and activates immediately', async () => {
    const w = makeWorker(); await w.fire('install')
    expect([...w.stores.get('cb-shell-v1').keys()]).toContain(`${ORIGIN}/offline.html`)
    expect(w.skipped).toBe(1)
  })
  it('removes only its own old caches when activating', async () => {
    const w = makeWorker()
    for (const n of ['cb-shell-v0', 'cb-static-v0', 'cb-shell-v1', 'someone-elses-cache']) await (await (async () => w.stores.set(n, new Map()))())
    await w.fire('activate')
    expect([...w.stores.keys()].sort()).toEqual(['cb-shell-v1', 'someone-elses-cache'])
    expect(w.claimed).toBe(1)
  })
})

describe('fetch: what it must never touch', () => {
  it('leaves non-GET requests alone', async () => { const w = makeWorker(); expect((await w.fire('fetch', { request: req('/x', { method: 'POST' }) })).handled).toBe(false) })
  it('leaves other origins alone (maps, tiles, fonts)', async () => { const w = makeWorker(); expect((await w.fire('fetch', { request: { url: 'https://tile.openstreetmap.org/1/2/3.png', method: 'GET', mode: 'cors' } })).handled).toBe(false) })
  it.each(['/api/deliveries/', '/api/events/stream', '/api/me', '/api/push/config', '/api/assets/export.js', '/api/icons/avatar.png', '/api/images/proof.jpg'])('never intercepts or caches %s (private data, live stream), even when the path looks like a static file', async (path) => {
    const w = makeWorker({ network: async () => res() }); const r = await w.fire('fetch', { request: req(path) })
    await new Promise((x) => setTimeout(x, 10))
    expect(r.handled).toBe(false); expect(w.fetched).toEqual([]); expect([...w.stores.keys()]).toEqual([])
  })
  it('never intercepts an /api/ URL even when the browser marks it as a page navigation', async () => {
    const w = makeWorker({ network: async () => res() }); const r = await w.fire('fetch', { request: req('/api/events/stream', { mode: 'navigate' }) })
    expect(r.handled).toBe(false); expect(w.fetched).toEqual([])
  })
})

describe('fetch: pages', () => {
  it('serves pages fresh from the network and does not cache them', async () => {
    const w = makeWorker(); const r = await w.fire('fetch', { request: req('/dashboard', { mode: 'navigate' }) })
    expect(await r.response.text()).toBe('net')
    expect([...w.stores.values()].every((m) => m.size === 0)).toBe(true)
  })
  it('shows the offline page only when the network fails', async () => {
    const w = makeWorker({ network: async () => { throw new TypeError('offline') } })
    await w.fire('install')
    const r = await w.fire('fetch', { request: req('/map', { mode: 'navigate' }) })
    expect(r.response.url).toBe('/offline.html')
  })
})

describe('fetch: static files', () => {
  it('caches a hashed asset on first use and then serves it without the network', async () => {
    const w = makeWorker({ network: async () => res() })
    const r = req('/assets/index-abc123.js')
    await w.fire('fetch', { request: r }); await new Promise((x) => setTimeout(x, 10))
    expect(w.stores.get('cb-static-v1').has(r.url)).toBe(true)
    const before = w.fetched.length
    await w.fire('fetch', { request: r })
    expect(w.fetched.length).toBe(before)
  })
  it('does not cache failures or cross-origin/opaque responses', async () => {
    for (const bad of [{ ok: false, status: 500 }, { type: 'opaque' }, { type: 'cors' }]) {
      const w = makeWorker({ network: async () => res(bad) })
      await w.fire('fetch', { request: req('/assets/x.js') }); await new Promise((x) => setTimeout(x, 10))
      expect((w.stores.get('cb-static-v1') || new Map()).size).toBe(0)
    }
  })
  it('does not cache arbitrary same-origin paths', async () => {
    const w = makeWorker({ network: async () => res() })
    const r = await w.fire('fetch', { request: req('/some/page-data.json') }); await new Promise((x) => setTimeout(x, 10))
    expect(r.handled).toBe(false); expect(w.stores.size).toBe(0)
  })
  it('keeps the static cache from growing without limit', async () => {
    const w = makeWorker({ network: async () => res() })
    for (let i = 0; i < 90; i++) { await w.fire('fetch', { request: req(`/assets/f${i}.js`) }); await new Promise((x) => setTimeout(x, 2)) }
    await new Promise((x) => setTimeout(x, 30))
    expect(w.stores.get('cb-static-v1').size).toBeLessThanOrEqual(80)
  })
})

describe('push', () => {
  it('shows a notification with the brand icon and a same-site link', async () => {
    const w = makeWorker()
    await w.fire('push', pushEvent({ title: 'Delivery #5: In transit', body: 'Open CareBridge for details.', url: '/deliveries?open=5', tag: 'cb-donation' }))
    expect(w.shown).toEqual([{ title: 'Delivery #5: In transit', body: 'Open CareBridge for details.', tag: 'cb-donation', icon: '/icons/icon-192.png', badge: '/icons/badge-96.png', data: { url: '/deliveries?open=5' } }])
  })
  it('still shows a generic notice for a malformed or empty payload (the browser requires one)', async () => {
    for (const ev of [pushEvent(null, true), { data: null }, pushEvent('a string'), pushEvent([1, 2])]) {
      const w = makeWorker(); await w.fire('push', ev)
      expect(w.shown[0].title).toBe('CareBridge'); expect(w.shown[0].data.url).toBe('/notifications')
    }
  })
  it.each(['https://evil.example/phish', '//evil.example', 'javascript:alert(1)', '\\evil', '/a\nb', 42, null])('never lets a push open %s', async (url) => {
    const w = makeWorker(); await w.fire('push', pushEvent({ title: 't', url }))
    expect(w.shown[0].data.url).toBe('/notifications')
  })
  it('bounds the text it shows', async () => {
    const w = makeWorker(); await w.fire('push', pushEvent({ title: 'T'.repeat(500), body: 'B'.repeat(900), tag: 'x'.repeat(200) }))
    expect(w.shown[0].title.length).toBe(80); expect(w.shown[0].body.length).toBe(160); expect(w.shown[0].tag.length).toBe(40)
  })
})

describe('notification click', () => {
  const click = (url) => ({ notification: { data: { url }, close: vi.fn() } })
  it('closes the notification and focuses an open tab, navigating it to the link', async () => {
    const w = makeWorker(); const calls = []
    w.clientList.push({ url: `${ORIGIN}/dashboard`, focus: async function () { calls.push('focus'); return this }, navigate: async (u) => { calls.push(u) } })
    const ev = click('/deliveries?open=5'); await w.fire('notificationclick', ev)
    expect(ev.notification.close).toHaveBeenCalledTimes(1); expect(calls).toEqual(['focus', `${ORIGIN}/deliveries?open=5`]); expect(w.opened).toEqual([])
  })
  it('opens a new window when the app is not open', async () => {
    const w = makeWorker(); await w.fire('notificationclick', click('/map'))
    expect(w.opened).toEqual([`${ORIGIN}/map`])
  })
  it('ignores tabs from other origins', async () => {
    const w = makeWorker(); w.clientList.push({ url: 'https://other.example/x', focus: async () => { throw new Error('must not focus') } })
    await w.fire('notificationclick', click('/map')); expect(w.opened).toEqual([`${ORIGIN}/map`])
  })
  it('falls back to a new window if the open tab cannot be navigated', async () => {
    const w = makeWorker()
    w.clientList.push({ url: `${ORIGIN}/x`, focus: async function () { return this }, navigate: async () => { throw new Error('not controlled') } })
    await w.fire('notificationclick', click('/map')); expect(w.opened).toEqual([`${ORIGIN}/map`])
  })
  it('a tampered link in the notification data cannot open another site', async () => {
    const w = makeWorker(); await w.fire('notificationclick', click('https://evil.example/x'))
    expect(w.opened).toEqual([`${ORIGIN}/notifications`])
  })
  it('a notification with no data opens the notifications page', async () => {
    const w = makeWorker(); await w.fire('notificationclick', { notification: { close() {} } })
    expect(w.opened).toEqual([`${ORIGIN}/notifications`])
  })
})

describe('housekeeping', () => {
  it('asks open pages to subscribe again when the push service rotates the subscription', async () => {
    const w = makeWorker(); const got = []
    w.clientList.push({ url: `${ORIGIN}/a`, postMessage: (m) => got.push(m) }, { url: `${ORIGIN}/b`, postMessage: (m) => got.push(m) })
    await w.fire('pushsubscriptionchange'); expect(got).toEqual([{ type: 'cb:resubscribe' }, { type: 'cb:resubscribe' }])
  })
  it('skips waiting only when told to', async () => {
    const w = makeWorker(); await w.fire('message', { data: { type: 'other' } }); expect(w.skipped).toBe(0)
    await w.fire('message', { data: { type: 'SKIP_WAITING' } }); expect(w.skipped).toBe(1)
  })
})

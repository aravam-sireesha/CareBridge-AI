import { describe, it, expect, vi } from 'vitest'
import { DISMISS_DAYS, bannerDismissed, createInstallController, dismissBanner, isStandalone, platformHint, registerServiceWorker, serviceWorkerAllowed, shouldShowInstall } from '../src/lib/pwa.js'
import { EVENT_STATUS_TEXT, PushError, disablePush, enablePush, pushSupport, thisDeviceSubscribed, urlBase64ToUint8Array } from '../src/lib/push.js'
import { createWakeLock, wakeLockSupported } from '../src/lib/wakeLock.js'

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1'
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36'
const DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36'
const tick = () => new Promise((r) => setTimeout(r, 0))

// ---------------------------------------------------------------- service worker registration
function fakeWin({ protocol = 'https:', hostname = 'app.example.org', ready = 'complete' } = {}) {
  const l = {}
  return { location: { protocol, hostname }, document: { readyState: ready }, addEventListener: (t, fn) => { l[t] = fn }, fire: (t) => l[t]?.(), matchMedia: () => ({ matches: false }) }
}
function fakeNav({ controller = {}, regs = [], failRegister = false } = {}) {
  const handlers = {}; const installing = { state: 'installing', addEventListener: (t, fn) => { handlers.statechange = fn } }
  const registration = { installing, addEventListener: (t, fn) => { handlers.updatefound = fn } }
  const sw = { controller, register: vi.fn(async () => { if (failRegister) throw new Error('blocked'); return registration }), getRegistrations: vi.fn(async () => regs) }
  return { nav: { serviceWorker: sw, userAgent: DESKTOP }, registration, installing, handlers }
}

describe('service worker registration', () => {
  it('is allowed on https and localhost only, and only where the browser has service workers', () => {
    const nav = { serviceWorker: {} }
    expect(serviceWorkerAllowed(fakeWin(), nav)).toBe(true)
    expect(serviceWorkerAllowed(fakeWin({ protocol: 'http:', hostname: 'localhost' }), nav)).toBe(true)
    expect(serviceWorkerAllowed(fakeWin({ protocol: 'http:', hostname: '192.168.1.5' }), nav)).toBe(false)
    expect(serviceWorkerAllowed(fakeWin(), {})).toBe(false)
    expect(serviceWorkerAllowed(null, nav)).toBe(false)
  })
  it('registers /sw.js at the root scope in production', async () => {
    const { nav } = fakeNav()
    expect(await registerServiceWorker({ win: fakeWin(), nav, production: true })).toBeTruthy()
    expect(nav.serviceWorker.register).toHaveBeenCalledWith('/sw.js', { scope: '/' })
  })
  it('waits for the page to finish loading so the worker does not compete with the first paint', async () => {
    const win = fakeWin({ ready: 'loading' }); const { nav } = fakeNav()
    const p = registerServiceWorker({ win, nav, production: true }); await tick()
    expect(nav.serviceWorker.register).toHaveBeenCalledTimes(0)
    win.fire('load'); await p
    expect(nav.serviceWorker.register).toHaveBeenCalledTimes(1)
  })
  it('in development it removes leftover workers and registers nothing', async () => {
    const stale = { unregister: vi.fn() }; const { nav } = fakeNav({ regs: [stale] })
    expect(await registerServiceWorker({ win: fakeWin(), nav, production: false })).toBeNull()
    expect(stale.unregister).toHaveBeenCalledTimes(1); expect(nav.serviceWorker.register).toHaveBeenCalledTimes(0)
  })
  it('announces an update only when a worker was already controlling the page', async () => {
    for (const [controller, expected] of [[{}, 1], [null, 0]]) {
      const { nav, installing, handlers } = fakeNav({ controller }); const onUpdate = vi.fn()
      await registerServiceWorker({ win: fakeWin(), nav, production: true, onUpdate })
      handlers.updatefound(); installing.state = 'installed'; handlers.statechange()
      expect(onUpdate).toHaveBeenCalledTimes(expected)
    }
  })
  it('a failed registration is not fatal', async () => {
    const warn = console.warn; console.warn = () => {}
    const { nav } = fakeNav({ failRegister: true })
    expect(await registerServiceWorker({ win: fakeWin(), nav, production: true })).toBeNull(); console.warn = warn
  })
  it('does nothing where service workers are not allowed', async () => {
    expect(await registerServiceWorker({ win: fakeWin({ protocol: 'http:', hostname: 'example.org' }), nav: { serviceWorker: {} }, production: true })).toBeNull()
  })
})

describe('install banner rules', () => {
  it('detects the installed app', () => {
    expect(isStandalone({ matchMedia: () => ({ matches: true }) }, {})).toBe(true)
    expect(isStandalone({ matchMedia: () => ({ matches: false }) }, { standalone: true })).toBe(true)
    expect(isStandalone({ matchMedia: () => ({ matches: false }) }, {})).toBe(false)
  })
  it('chooses install advice by platform', () => { expect(platformHint(IPHONE)).toBe('ios'); expect(platformHint(ANDROID)).toBe('android'); expect(platformHint(DESKTOP)).toBe('desktop') })
  it('remembers a dismissal for 30 days, then asks again', () => {
    const store = new Map(); const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }
    const t0 = 1_800_000_000_000
    expect(bannerDismissed(storage, t0)).toBe(false)
    dismissBanner(storage, t0)
    expect(bannerDismissed(storage, t0 + 86400_000)).toBe(true)
    expect(bannerDismissed(storage, t0 + (DISMISS_DAYS + 1) * 86400_000)).toBe(false)
  })
  it('survives unusable or corrupted storage', () => {
    const broken = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('denied') } }
    expect(bannerDismissed(broken)).toBe(false); expect(() => dismissBanner(broken)).not.toThrow()
    expect(bannerDismissed({ getItem: () => 'garbage' })).toBe(false)
  })
  it.each([
    [{ canPrompt: true, hint: 'android', standalone: false, dismissed: false }, true],
    [{ canPrompt: false, hint: 'ios', standalone: false, dismissed: false }, true],
    [{ canPrompt: false, hint: 'desktop', standalone: false, dismissed: false }, false],
    [{ canPrompt: true, hint: 'android', standalone: true, dismissed: false }, false],
    [{ canPrompt: true, hint: 'android', standalone: false, dismissed: true }, false],
    [{ canPrompt: false, hint: 'ios', standalone: true, dismissed: false }, false],
  ])('shouldShowInstall %j -> %s', (input, expected) => { expect(shouldShowInstall(input)).toBe(expected) })
})

describe('install controller', () => {
  function fakeWinEvents() { const l = {}; return { addEventListener: (t, fn) => { l[t] = fn }, emit: (t, e) => l[t]?.(e) } }
  const promptEvent = (outcome = 'accepted') => ({ preventDefault: vi.fn(), prompt: vi.fn(async () => {}), userChoice: Promise.resolve({ outcome }) })
  it('captures the browser prompt instead of showing it immediately', () => {
    const win = fakeWinEvents(); const c = createInstallController(win); const e = promptEvent()
    expect(c.state().canPrompt).toBe(false); win.emit('beforeinstallprompt', e)
    expect(e.preventDefault).toHaveBeenCalled(); expect(c.state().canPrompt).toBe(true)
  })
  it('shows the prompt once and reports what the person chose', async () => {
    const win = fakeWinEvents(); const c = createInstallController(win); const e = promptEvent('dismissed'); win.emit('beforeinstallprompt', e)
    expect(await c.prompt()).toEqual({ outcome: 'dismissed' }); expect(e.prompt).toHaveBeenCalledTimes(1)
    expect(await c.prompt()).toEqual({ outcome: 'unavailable' })                         // a deferred prompt cannot be reused
  })
  it('tells subscribers when the app gets installed', () => {
    const win = fakeWinEvents(); const c = createInstallController(win); const seen = []
    c.subscribe((s) => seen.push(s)); win.emit('beforeinstallprompt', promptEvent()); win.emit('appinstalled')
    expect(seen.at(-1)).toEqual({ canPrompt: false, installed: true }); expect(seen[0]).toEqual({ canPrompt: false, installed: false })
  })
})

// ---------------------------------------------------------------- push
describe('urlBase64ToUint8Array', () => {
  it('decodes URL-safe base64 with and without padding', () => {
    expect([...urlBase64ToUint8Array('-_8')]).toEqual([251, 255]); expect([...urlBase64ToUint8Array('AQAB')]).toEqual([1, 0, 1]); expect([...urlBase64ToUint8Array('AQ')]).toEqual([1])
  })
})

const PUBKEY = 'BAEC'                  // 3 bytes: [4, 1, 2]
function pushEnv({ permission = 'default', ua = DESKTOP, hasPush = true, requestResult = 'granted', existing = null, subscribeResult } = {}) {
  const sub = subscribeResult || { endpoint: 'https://fcm.googleapis.com/fcm/send/abc', toJSON() { return { endpoint: this.endpoint, keys: { p256dh: 'P', auth: 'A' } } }, unsubscribe: vi.fn(async () => true), options: {} }
  const pm = { getSubscription: vi.fn(async () => existing), subscribe: vi.fn(async () => sub) }
  const Notification = { permission, requestPermission: vi.fn(async () => requestResult) }
  const win = { Notification: Notification, PushManager: hasPush ? {} : undefined, matchMedia: () => ({ matches: false }) }
  const nav = { userAgent: ua, serviceWorker: { ready: Promise.resolve({ pushManager: pm }), getRegistration: async () => ({ pushManager: pm }) } }
  const api = { pushConfig: vi.fn().mockResolvedValue({ enabled: true, public_key: PUBKEY }), pushSubscribe: vi.fn().mockResolvedValue({ subscribed: true }), pushUnsubscribe: vi.fn().mockResolvedValue({ removed: 1 }) }
  return { win, nav, api, pm, sub, Notification }
}

describe('pushSupport', () => {
  it('reports a browser without push', () => { const e = pushEnv({ hasPush: false }); const s = pushSupport(e); expect(s.supported).toBe(false); expect(s.reason).toMatch(/does not support/) })
  it('explains the iPhone requirement to install first', () => {
    const e = pushEnv({ ua: IPHONE }); const s = pushSupport(e)
    expect(s.supported).toBe(false); expect(s.reason).toMatch(/Home Screen/)
    e.win.matchMedia = () => ({ matches: true }); expect(pushSupport(e).supported).toBe(true)
  })
  it('a blocked permission is supported but explains how to unblock', () => { const s = pushSupport(pushEnv({ permission: 'denied' })); expect(s.supported).toBe(true); expect(s.reason).toMatch(/blocked/) })
  it('is clean when notifications can simply be turned on', () => { expect(pushSupport(pushEnv())).toEqual({ supported: true, permission: 'default', reason: '' }) })
})

describe('enablePush', () => {
  it('asks permission, subscribes with the server key and registers the device', async () => {
    const e = pushEnv()
    expect(await enablePush(e)).toEqual({ subscribed: true })
    expect(e.Notification.requestPermission).toHaveBeenCalledTimes(1)
    const opts = e.pm.subscribe.mock.calls[0][0]
    expect(opts.userVisibleOnly).toBe(true); expect([...opts.applicationServerKey]).toEqual([4, 1, 2])
    expect(e.api.pushSubscribe).toHaveBeenCalledWith({ endpoint: 'https://fcm.googleapis.com/fcm/send/abc', keys: { p256dh: 'P', auth: 'A' }, user_agent: DESKTOP })
  })
  it('does not ask again when permission was already granted', async () => {
    const e = pushEnv({ permission: 'granted' }); await enablePush(e)
    expect(e.Notification.requestPermission).toHaveBeenCalledTimes(0)
  })
  it.each(['denied', 'default'])('if the person answers "%s" nothing is subscribed or sent to the server', async (answer) => {
    const e = pushEnv({ requestResult: answer })
    await expect(enablePush(e)).rejects.toThrow(PushError)
    expect(e.pm.subscribe).toHaveBeenCalledTimes(0); expect(e.api.pushSubscribe).toHaveBeenCalledTimes(0)
  })
  it('does not even show the browser prompt when the server cannot send push', async () => {
    const e = pushEnv(); e.api.pushConfig = vi.fn().mockResolvedValue({ enabled: false, public_key: null })
    await expect(enablePush(e)).rejects.toThrow(/not set up/)
    expect(e.Notification.requestPermission).toHaveBeenCalledTimes(0)
  })
  it('refuses on an unsupported browser before contacting the server', async () => {
    const e = pushEnv({ hasPush: false })
    await expect(enablePush(e)).rejects.toMatchObject({ code: 'unsupported' }); expect(e.api.pushConfig).toHaveBeenCalledTimes(0)
  })
  it('replaces a subscription made with an older server key, and reuses one that matches', async () => {
    const old = { options: { applicationServerKey: new Uint8Array([9, 9, 9]).buffer }, unsubscribe: vi.fn(async () => true) }
    const e1 = pushEnv({ existing: old }); await enablePush(e1)
    expect(old.unsubscribe).toHaveBeenCalledTimes(1); expect(e1.pm.subscribe).toHaveBeenCalledTimes(1)
    const same = { endpoint: 'https://fcm.googleapis.com/fcm/send/same', options: { applicationServerKey: new Uint8Array([4, 1, 2]).buffer }, unsubscribe: vi.fn(), toJSON() { return { endpoint: this.endpoint, keys: { p256dh: 'P', auth: 'A' } } } }
    const e2 = pushEnv({ existing: same }); await enablePush(e2)
    expect(same.unsubscribe).toHaveBeenCalledTimes(0); expect(e2.pm.subscribe).toHaveBeenCalledTimes(0); expect(e2.api.pushSubscribe).toHaveBeenCalledTimes(1)   // still (re)registered with the server
  })
  it('truncates an overlong user agent', async () => {
    const e = pushEnv({ ua: 'x'.repeat(500) }); await enablePush(e)
    expect(e.api.pushSubscribe.mock.calls[0][0].user_agent.length).toBe(200)
  })
})

describe('disablePush / state', () => {
  it('removes the device from the server and the browser', async () => {
    const sub = { endpoint: 'https://fcm.googleapis.com/x', unsubscribe: vi.fn(async () => true) }; const e = pushEnv({ existing: sub })
    expect(await disablePush(e)).toEqual({ unsubscribed: true })
    expect(e.api.pushUnsubscribe).toHaveBeenCalledWith('https://fcm.googleapis.com/x'); expect(sub.unsubscribe).toHaveBeenCalledTimes(1)
  })
  it('still unsubscribes the browser if the server cannot be reached, and says so', async () => {
    const sub = { endpoint: 'https://fcm.googleapis.com/x', unsubscribe: vi.fn(async () => true) }; const e = pushEnv({ existing: sub })
    e.api.pushUnsubscribe = vi.fn().mockRejectedValue(new Error('offline'))
    const r = await disablePush(e)
    expect(sub.unsubscribe).toHaveBeenCalledTimes(1); expect(r).toEqual({ unsubscribed: false, error: 'offline' })
  })
  it('does nothing when this device has no subscription, or no service worker', async () => {
    expect(await disablePush(pushEnv())).toEqual({ unsubscribed: false })
    expect(await disablePush({ api: {}, nav: {} })).toEqual({ unsubscribed: false })
    expect(await thisDeviceSubscribed({ nav: {} })).toBe(false)
    expect(await thisDeviceSubscribed(pushEnv({ existing: { endpoint: 'x' } }))).toBe(true)
  })
  it('never describes a push as delivered', () => {
    for (const text of Object.values(EVENT_STATUS_TEXT)) expect(/delivered|received|seen/i.test(text)).toBe(false)
    expect(EVENT_STATUS_TEXT.accepted_by_provider).toMatch(/push service/)
  })
})

// ---------------------------------------------------------------- screen wake lock
const emitter = () => { const l = {}; return { addEventListener: (t, fn) => { (l[t] ||= new Set()).add(fn) }, removeEventListener: (t, fn) => l[t]?.delete(fn), dispatchEvent: (e) => { [...(l[e.type] || [])].forEach((fn) => fn(e)); return true } } }
function wakeEnv({ supported = true, reject = false } = {}) {
  const sentinels = []; const doc = Object.assign(emitter(), { visibilityState: 'visible' })
  const nav = supported ? { wakeLock: { request: vi.fn(async () => { if (reject) throw new Error('NotAllowedError'); const s = Object.assign(emitter(), { release: vi.fn(async () => { s.dispatchEvent({ type: 'release' }) }) }); sentinels.push(s); return s }) } } : {}
  return { nav, doc, sentinels }
}
describe('wake lock', () => {
  it('is a harmless no-op where unsupported', async () => {
    const e = wakeEnv({ supported: false }); const w = createWakeLock(e)
    expect(wakeLockSupported(e.nav)).toBe(false); expect(await w.acquire()).toBe(false); expect(w.active).toBe(false); await w.release()
  })
  it('holds the screen on while sharing and lets go when sharing stops', async () => {
    const e = wakeEnv(); const changes = []; const w = createWakeLock({ ...e, onChange: (a) => changes.push(a) })
    expect(await w.acquire()).toBe(true); expect(w.active).toBe(true)
    await w.release(); expect(w.active).toBe(false); expect(e.sentinels[0].release).toHaveBeenCalledTimes(1); expect(changes).toEqual([true, false])
  })
  it('takes the lock again when the page becomes visible (browsers drop it when hidden)', async () => {
    const e = wakeEnv(); const w = createWakeLock(e); await w.acquire()
    e.doc.visibilityState = 'hidden'; await e.sentinels[0].release(); await tick(); expect(w.active).toBe(false)
    e.doc.visibilityState = 'visible'; e.doc.dispatchEvent({ type: 'visibilitychange' }); await tick(); await tick()
    expect(w.active).toBe(true); expect(e.nav.wakeLock.request).toHaveBeenCalledTimes(2)
  })
  it('does not ask while the page is hidden', async () => {
    const e = wakeEnv(); e.doc.visibilityState = 'hidden'; const w = createWakeLock(e)
    expect(await w.acquire()).toBe(false); expect(e.nav.wakeLock.request).toHaveBeenCalledTimes(0)
  })
  it('does not re-acquire after release (listener removed)', async () => {
    const e = wakeEnv(); const w = createWakeLock(e); await w.acquire(); await w.release()
    e.doc.dispatchEvent({ type: 'visibilitychange' }); await tick(); expect(e.nav.wakeLock.request).toHaveBeenCalledTimes(1)
  })
  it('a refusal (battery saver) is not an error', async () => {
    const e = wakeEnv({ reject: true }); const w = createWakeLock(e)
    expect(await w.acquire()).toBe(false); expect(w.active).toBe(false)
  })
  it('a lock granted after release() was called is let go immediately', async () => {
    const e = wakeEnv(); const w = createWakeLock(e)
    const pending = w.acquire(); await w.release(); await pending
    expect(w.active).toBe(false); expect(e.sentinels.every((s) => s.release.mock.calls.length >= 1)).toBe(true)
  })
})

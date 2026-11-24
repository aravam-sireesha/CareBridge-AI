// Progressive Web App plumbing: register the service worker, and offer "install" where the browser allows it. Pure and injectable for tests.

export const DISMISS_KEY = 'cb_install_dismissed_at'
export const DISMISS_DAYS = 30

export function serviceWorkerAllowed(win = typeof window !== 'undefined' ? window : null, nav = typeof navigator !== 'undefined' ? navigator : null) {
  if (!win || !nav || !('serviceWorker' in nav)) return false
  const { protocol, hostname } = win.location
  return protocol === 'https:' || hostname === 'localhost' || hostname === '127.0.0.1'      // browsers refuse service workers on plain http elsewhere
}

/** Registers /sw.js once the page has loaded. In development it removes any worker left over from a production build instead, so stale
 *  caches never confuse a developer. `onUpdate(registration)` fires when a new version is waiting. Resolves with the registration or null. */
export async function registerServiceWorker({ win = window, nav = navigator, production = import.meta.env.PROD, onUpdate } = {}) {
  if (!serviceWorkerAllowed(win, nav)) return null
  if (!production) {
    try { (await nav.serviceWorker.getRegistrations()).forEach((r) => r.unregister()) } catch { /* nothing to clean */ }
    return null
  }
  await new Promise((resolve) => { if (win.document.readyState === 'complete') resolve(); else win.addEventListener('load', resolve, { once: true }) })
  try {
    const reg = await nav.serviceWorker.register('/sw.js', { scope: '/' })
    reg.addEventListener?.('updatefound', () => {
      const incoming = reg.installing
      incoming?.addEventListener('statechange', () => { if (incoming.state === 'installed' && nav.serviceWorker.controller) onUpdate?.(reg) })
    })
    return reg
  } catch (e) {
    console.warn('Service worker registration failed', e?.message || e)
    return null
  }
}

export function isStandalone(win = window, nav = navigator) {
  return Boolean(win.matchMedia?.('(display-mode: standalone)')?.matches || nav.standalone === true)
}

/** Which "how to install" advice fits this browser. iOS has no install prompt: the person must use Share > Add to Home Screen. */
export function platformHint(ua = typeof navigator !== 'undefined' ? navigator.userAgent : '') {
  const isIos = /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && typeof document !== 'undefined' && 'ontouchend' in document)
  if (isIos) return 'ios'
  if (/Android/.test(ua)) return 'android'
  return 'desktop'
}

export function bannerDismissed(storage, now = Date.now()) {
  try { const t = Number(storage.getItem(DISMISS_KEY)); return Number.isFinite(t) && t > 0 && now - t < DISMISS_DAYS * 86400_000 } catch { return false }
}
export function dismissBanner(storage, now = Date.now()) { try { storage.setItem(DISMISS_KEY, String(now)) } catch { /* private mode: it will simply show again */ } }

/** Whether to show the install banner: not already installed, not recently dismissed, and either the browser can prompt or it is iOS (instructions only). */
export function shouldShowInstall({ canPrompt, hint, standalone, dismissed }) {
  if (standalone || dismissed) return false
  return Boolean(canPrompt) || hint === 'ios'
}

/** Captures the browser's install prompt so it can be shown from our own button at a sensible moment. */
export function createInstallController(win = window) {
  let deferred = null
  const listeners = new Set()
  const state = () => ({ canPrompt: Boolean(deferred), installed: Boolean(win.__cbInstalled) })
  const emit = () => listeners.forEach((fn) => fn(state()))
  win.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferred = e; emit() })
  win.addEventListener('appinstalled', () => { deferred = null; win.__cbInstalled = true; emit() })
  return {
    state,
    subscribe(fn) { listeners.add(fn); fn(state()); return () => listeners.delete(fn) },
    async prompt() {
      if (!deferred) return { outcome: 'unavailable' }
      const d = deferred; deferred = null; emit()                       // a prompt can only be used once
      await d.prompt()
      const choice = await d.userChoice
      return { outcome: choice?.outcome || 'dismissed' }
    },
  }
}

const controllers = new WeakMap()
/** One controller per window. Create it at startup (main.jsx): the browser can fire beforeinstallprompt before any component mounts. */
export function getInstallController(win = window) {
  if (!controllers.has(win)) controllers.set(win, createInstallController(win))
  return controllers.get(win)
}

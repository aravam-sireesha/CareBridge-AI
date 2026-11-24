// Keeps the screen on while a volunteer shares their location, so the phone keeps reporting. Best effort: unsupported browsers and
// battery-saver refusals simply mean it does not hold. It is released the moment sharing pauses or stops, and re-acquired when the page
// becomes visible again (browsers drop the lock whenever the page is hidden).
export function wakeLockSupported(nav = typeof navigator !== 'undefined' ? navigator : null) { return Boolean(nav?.wakeLock?.request) }

export function createWakeLock({ nav = navigator, doc = document, onChange = () => {} } = {}) {
  let sentinel = null, wanted = false
  const set = (s) => { sentinel = s; onChange(Boolean(s)) }
  async function request() {
    if (!wantedAndVisible() || sentinel) return false
    try {
      const s = await nav.wakeLock.request('screen')
      if (!wanted) { await s.release(); return false }                           // released while the request was in flight
      s.addEventListener?.('release', () => { if (sentinel === s) set(null) })
      set(s); return true
    } catch { set(null); return false }                                           // refused (battery saver, permissions policy)
  }
  const wantedAndVisible = () => wanted && wakeLockSupported(nav) && doc.visibilityState !== 'hidden'
  const onVisible = () => { if (doc.visibilityState === 'visible') request() }
  return {
    async acquire() { wanted = true; doc.addEventListener('visibilitychange', onVisible); return request() },
    async release() { wanted = false; doc.removeEventListener('visibilitychange', onVisible); const s = sentinel; set(null); try { await s?.release() } catch { /* already gone */ } },
    get active() { return Boolean(sentinel) },
  }
}

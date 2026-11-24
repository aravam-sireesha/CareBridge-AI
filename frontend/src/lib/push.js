// Web Push on this device: permission, subscription, and the honest states in between. Pure and injectable for tests.
import { isStandalone, platformHint } from './pwa.js'

export function urlBase64ToUint8Array(base64) {
  const padded = `${base64}${'='.repeat((4 - (base64.length % 4)) % 4)}`.replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(padded)
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

/** { supported, reason, permission } - `reason` is shown to the person, so it explains what they can do about it. */
export function pushSupport({ win = window, nav = navigator } = {}) {
  const permission = win.Notification?.permission || 'unsupported'
  if (!('serviceWorker' in nav) || !win.PushManager || !win.Notification) {
    const ios = platformHint(nav.userAgent) === 'ios'
    return { supported: false, permission, reason: ios && !isStandalone(win, nav) ? 'On iPhone and iPad, notifications work after you add CareBridge to your Home Screen (Share, then Add to Home Screen) and open it from there.' : 'This browser does not support push notifications.' }
  }
  if (platformHint(nav.userAgent) === 'ios' && !isStandalone(win, nav)) return { supported: false, permission, reason: 'On iPhone and iPad, notifications work after you add CareBridge to your Home Screen (Share, then Add to Home Screen) and open it from there.' }
  if (permission === 'denied') return { supported: true, permission, reason: 'Notifications are blocked for this site in your browser settings. Allow them there, then come back and turn them on.' }
  return { supported: true, permission, reason: '' }
}

export class PushError extends Error { constructor(message, code) { super(message); this.code = code } }

/** Turn notifications on for THIS device. Must be called from a click: browsers only allow the permission prompt after a user action. */
export async function enablePush({ api, win = window, nav = navigator } = {}) {
  const support = pushSupport({ win, nav })
  if (!support.supported) throw new PushError(support.reason, 'unsupported')
  const cfg = await api.pushConfig()
  if (!cfg?.enabled || !cfg.public_key) throw new PushError('Push notifications are not set up on this server yet.', 'not_configured')
  const permission = win.Notification.permission === 'granted' ? 'granted' : await win.Notification.requestPermission()
  if (permission !== 'granted') throw new PushError(permission === 'denied' ? 'Notifications were blocked. You can allow them in your browser settings.' : 'Notifications were not turned on.', permission)
  const reg = await nav.serviceWorker.ready
  const key = urlBase64ToUint8Array(cfg.public_key)
  let sub = await reg.pushManager.getSubscription()
  if (sub && !sameKey(sub.options?.applicationServerKey, key)) { await sub.unsubscribe(); sub = null }      // the server's key changed: the old subscription can never work
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key })
  const json = sub.toJSON()
  await api.pushSubscribe({ endpoint: json.endpoint, keys: json.keys, user_agent: String(nav.userAgent || '').slice(0, 200) })
  return { subscribed: true }
}

function sameKey(a, b) {
  if (!a) return true                               // some browsers do not expose it: assume it matches rather than churn subscriptions
  const x = new Uint8Array(a)
  return x.length === b.length && x.every((v, i) => v === b[i])
}

/** Turn notifications off for this device: tell the server and the browser. Either failing must not leave the other half on. */
export async function disablePush({ api, nav = navigator } = {}) {
  let endpoint = null
  try {
    const reg = await nav.serviceWorker?.getRegistration?.()
    const sub = await reg?.pushManager?.getSubscription()
    endpoint = sub?.endpoint || null
    if (endpoint) { try { await api.pushUnsubscribe(endpoint) } finally { await sub.unsubscribe() } }
  } catch (e) { return { unsubscribed: false, error: e?.message || 'Could not turn notifications off.' } }
  return { unsubscribed: Boolean(endpoint) }
}

export async function thisDeviceSubscribed({ nav = navigator } = {}) {
  try { const reg = await nav.serviceWorker?.getRegistration?.(); return Boolean(await reg?.pushManager?.getSubscription()) } catch { return false }
}

/** Plain-language label for what the push service said. "Accepted" is deliberately not "delivered". */
export const EVENT_STATUS_TEXT = {
  queued: 'Sending…', accepted_by_provider: 'Sent to your device\u2019s push service', failed: 'Could not be sent', no_subscription: 'No device to send to', suppressed: 'Not sent (turned off)',
}

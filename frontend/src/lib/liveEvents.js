// One live-event connection per browser tab, shared by every component that wants updates.
import { createEventStream } from './eventStream.js'

const BASE_URL = import.meta.env.VITE_API_URL || '/api'
const listeners = new Map()          // type | '*' -> Set<fn>
const statusListeners = new Set()
let stream = null
let status = 'closed'

export function subscribeLive(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set())
  listeners.get(type).add(fn)
  return () => listeners.get(type)?.delete(fn)
}
export function onLiveStatus(fn) { statusListeners.add(fn); fn(status); return () => statusListeners.delete(fn) }
export const liveStatus = () => status

function dispatch(type, data, id) {
  for (const key of [type, '*']) listeners.get(key)?.forEach((fn) => { try { fn(data, type, id) } catch (e) { console.error('Live listener failed', e) } })
  if (type === 'notification' && typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('cb:notifications-changed'))
}

export function connectLive(getToken, options = {}) {
  if (stream) return
  stream = createEventStream({
    url: `${BASE_URL}/events/stream`, getToken, onEvent: dispatch,
    onStatus: (s) => { status = s; statusListeners.forEach((fn) => fn(s)) },
    onUnauthorized: () => window.dispatchEvent(new CustomEvent('cb:unauthorized')),
    ...options,
  })
  stream.start()
}
export function disconnectLive() { if (stream) { stream.stop(); stream = null } status = 'closed'; statusListeners.forEach((fn) => fn('closed')) }

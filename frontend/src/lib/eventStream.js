// Reads the server's live-event stream (GET /events/stream) with fetch, because EventSource cannot send an Authorization
// header. Handles what a real network does: reconnects with jittered back-off, resumes from the last event id so nothing is
// missed, drops duplicates, notices a silent connection (the server sends a heartbeat every 15 s) and stops for good on 401.
import { createSseParser } from './sse.js'

export const BACKOFF = { base: 1000, max: 30000 }
const SEEN_LIMIT = 300

/** Delay before reconnect attempt number `attempt` (0-based): exponential, capped, with jitter so clients do not stampede. */
export function nextDelay(attempt, random = Math.random) {
  const exp = Math.min(BACKOFF.max, BACKOFF.base * 2 ** Math.max(0, attempt))
  return Math.round(exp / 2 + random() * (exp / 2))
}

const defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * @param {object} o
 * @param {string} o.url
 * @param {() => string|null} o.getToken   read at every (re)connect, so a refreshed login is picked up
 * @param {(type:string, data:object, id?:string) => void} o.onEvent
 * @param {(status:string) => void} [o.onStatus]  connecting | open | reconnecting | unauthorized | closed
 * @param {() => void} [o.onUnauthorized]
 */
export function createEventStream({ url, getToken, onEvent, onStatus = () => {}, onUnauthorized = () => {}, fetchImpl, sleep = defaultSleep, heartbeatMs = 45000, random = Math.random, timers }) {
  const T = timers || { setTimeout: (...a) => setTimeout(...a), clearTimeout: (...a) => clearTimeout(...a) }
  const doFetch = fetchImpl || ((...a) => fetch(...a))
  let stopped = true
  let lastId = null
  let attempt = 0
  let controller = null
  let running = null
  let status = 'closed'
  const seen = new Set()
  const order = []

  const setStatus = (s) => { if (s !== status) { status = s; onStatus(s) } }
  const remember = (id) => { seen.add(id); order.push(id); if (order.length > SEEN_LIMIT) seen.delete(order.shift()) }

  async function connectOnce() {
    const token = getToken()
    if (!token) return 'stop'
    controller = new AbortController()
    let timer = null
    const arm = () => { T.clearTimeout(timer); timer = T.setTimeout(() => controller.abort(), heartbeatMs) }
    setStatus(attempt === 0 ? 'connecting' : 'reconnecting')
    const headers = { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' }
    if (lastId) headers['Last-Event-ID'] = lastId
    let res
    try { res = await doFetch(url, { headers, signal: controller.signal, cache: 'no-store' }) } catch { return 'retry' }
    if (res.status === 401) { setStatus('unauthorized'); onUnauthorized(); return 'stop' }
    if (res.status === 429) { await sleep(Math.max(1, Number(res.headers?.get?.('Retry-After')) || 10) * 1000); return 'wait' }
    if (!res.ok || !res.body) return 'retry'
    setStatus('open')
    arm()
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    const parser = createSseParser((type, payload, id) => {
      if (id) { if (seen.has(id)) return; remember(id); lastId = id }
      if (type === 'hello') attempt = 0
      const data = payload && typeof payload === 'object' && 'payload' in payload ? payload.payload : payload
      try { onEvent(type, data, id) } catch (e) { console.error('Live event handler failed', e) }
    })
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        arm()                                                  // any bytes, including heartbeats, prove the connection is alive
        parser.push(decoder.decode(value, { stream: true }))
      }
    } catch { /* aborted by the watchdog or dropped by the network: reconnect below */ } finally { T.clearTimeout(timer) }
    return 'retry'
  }

  async function run() {
    while (!stopped) {
      const outcome = await connectOnce()
      if (stopped || outcome === 'stop') break
      if (outcome === 'retry') { await sleep(nextDelay(attempt, random)); attempt += 1 }
      setStatus('reconnecting')
    }
    if (status !== 'unauthorized') setStatus('closed')
  }

  return {
    start() { if (running) return; stopped = false; attempt = 0; running = run().finally(() => { running = null }) },
    stop() { stopped = true; if (controller) controller.abort() },
    get status() { return status },
    get lastEventId() { return lastId },
  }
}

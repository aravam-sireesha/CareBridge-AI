import { describe, it, expect, vi } from 'vitest'
import { createEventStream, nextDelay, BACKOFF } from '../src/lib/eventStream.js'
import { createSseParser } from '../src/lib/sse.js'

const frame = (id, type, payload = {}) => `${id ? `id: ${id}\n` : ''}event: ${type}\ndata: ${JSON.stringify({ id, type, payload, ts: 1 })}\n\n`
const enc = new TextEncoder()

/** A fake fetch whose n-th call returns responses[n]. A response is { status, chunks, hang }; `hang` keeps the stream open until aborted. */
function fakeFetch(responses, onCall) {
  const calls = []
  const fn = async (url, init) => {
    const spec = responses[Math.min(calls.length, responses.length - 1)]
    calls.push({ url, init })
    onCall?.(calls.length, spec)
    if (spec.throws) throw new TypeError('network down')
    const body = new ReadableStream({
      start(c) {
        ;(spec.chunks || []).forEach((t) => c.enqueue(enc.encode(t)))
        if (!spec.hang) c.close()
        init.signal.addEventListener('abort', () => { try { c.error(new Error('aborted')) } catch { /* already closed */ } })
      },
    })
    return new Response(spec.status === 200 || !spec.status ? body : null, { status: spec.status || 200, headers: spec.headers || {} })
  }
  fn.calls = calls
  return fn
}
const noSleep = async () => {}
const until = async (cond, ms = 1000) => { const t = Date.now(); while (!cond()) { if (Date.now() - t > ms) throw new Error('timed out waiting'); await new Promise((r) => setTimeout(r, 2)) } }

describe('nextDelay', () => {
  it('grows exponentially, is capped, and stays within the jitter band', () => {
    expect(nextDelay(0, () => 0)).toBe(BACKOFF.base / 2)
    expect(nextDelay(0, () => 1)).toBe(BACKOFF.base)
    expect(nextDelay(3, () => 1)).toBe(BACKOFF.base * 8)
    expect(nextDelay(50, () => 1)).toBe(BACKOFF.max)
    expect(nextDelay(50, () => 0)).toBe(BACKOFF.max / 2)
  })
})

describe('SSE parser', () => {
  it('passes the event id only when the server sent one', () => {
    const got = []
    const p = createSseParser((...a) => got.push(a))
    p.push(frame('5-0', 'delivery.status', { task_id: 1 }))
    p.push('event: hello\ndata: {"x":1}\n\n')
    p.push(': ping\n\n')
    expect(got.length).toBe(2)
    expect(got[0][2]).toBe('5-0')
    expect(got[1].length).toBe(2)
  })
  it('handles a frame split across chunks', () => {
    const got = []
    const p = createSseParser((...a) => got.push(a))
    const f = frame('9-0', 'notification', { kind: 'k' })
    p.push(f.slice(0, 20)); p.push(f.slice(20))
    expect(got.length).toBe(1)
  })
})

describe('createEventStream', () => {
  it('sends the bearer token, unwraps the payload and reports open', async () => {
    const events = []; const statuses = []
    const fetchImpl = fakeFetch([{ chunks: [frame(null, 'hello', { replayed: 0 }), frame('1-0', 'delivery.status', { task_id: 7, status: 'picked_up' })], hang: true }])
    const s = createEventStream({ url: '/api/events/stream', getToken: () => 'tok', onEvent: (t, d, id) => events.push([t, d, id]), onStatus: (x) => statuses.push(x), fetchImpl, sleep: noSleep })
    s.start(); await until(() => events.length === 2); s.stop()
    expect(fetchImpl.calls[0].init.headers.Authorization).toBe('Bearer tok')
    expect(fetchImpl.calls[0].init.headers['Last-Event-ID']).toBeUndefined()
    expect(events[1]).toEqual(['delivery.status', { task_id: 7, status: 'picked_up' }, '1-0'])
    expect(statuses).toContain('open')
  })

  it('reconnects with Last-Event-ID so missed events are replayed, and drops duplicates', async () => {
    const events = []
    const fetchImpl = fakeFetch([
      { chunks: [frame('1-0', 'delivery.status', { task_id: 1 }), frame('2-0', 'delivery.status', { task_id: 2 })] },        // ends: connection drops
      { chunks: [frame('2-0', 'delivery.status', { task_id: 2 }), frame('3-0', 'delivery.status', { task_id: 3 })], hang: true }, // replay overlaps
    ])
    const s = createEventStream({ url: '/e', getToken: () => 't', onEvent: (t, d, id) => events.push(id), fetchImpl, sleep: noSleep })
    s.start(); await until(() => events.length >= 3); s.stop()
    expect(fetchImpl.calls[1].init.headers['Last-Event-ID']).toBe('2-0')
    expect(events).toEqual(['1-0', '2-0', '3-0'])                                  // 2-0 was delivered once
  })

  it('stops for good on 401 and tells the app the session is over', async () => {
    const onUnauthorized = vi.fn(); const statuses = []
    const fetchImpl = fakeFetch([{ status: 401 }])
    const s = createEventStream({ url: '/e', getToken: () => 't', onEvent() {}, onStatus: (x) => statuses.push(x), onUnauthorized, fetchImpl, sleep: noSleep })
    s.start(); await until(() => statuses.includes('unauthorized')); await new Promise((r) => setTimeout(r, 20))
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(fetchImpl.calls.length).toBe(1)                                         // no retry loop against a rejected token
    expect(s.status).toBe('unauthorized')
  })

  it('retries with growing delays after network errors', async () => {
    const delays = []
    const fetchImpl = fakeFetch([{ throws: true }, { throws: true }, { throws: true }, { chunks: [frame(null, 'hello')], hang: true }])
    const s = createEventStream({ url: '/e', getToken: () => 't', onEvent() {}, fetchImpl, random: () => 1, sleep: async (ms) => { delays.push(ms) } })
    s.start(); await until(() => fetchImpl.calls.length === 4); s.stop()
    expect(delays.slice(0, 3)).toEqual([BACKOFF.base, BACKOFF.base * 2, BACKOFF.base * 4])
  })

  it('honours Retry-After on 429 without growing the back-off', async () => {
    const waits = []
    const fetchImpl = fakeFetch([{ status: 429, headers: { 'Retry-After': '7' } }, { chunks: [frame(null, 'hello')], hang: true }])
    const s = createEventStream({ url: '/e', getToken: () => 't', onEvent() {}, fetchImpl, sleep: async (ms) => { waits.push(ms) } })
    s.start(); await until(() => fetchImpl.calls.length === 2); s.stop()
    expect(waits[0]).toBe(7000)
  })

  it('does not connect without a token', async () => {
    const fetchImpl = fakeFetch([{ hang: true }])
    const s = createEventStream({ url: '/e', getToken: () => null, onEvent() {}, fetchImpl, sleep: noSleep })
    s.start(); await new Promise((r) => setTimeout(r, 20))
    expect(fetchImpl.calls.length).toBe(0)
  })

  it('treats a silent connection as dead and reconnects (heartbeat watchdog)', async () => {
    const pending = []
    const timers = { setTimeout: (fn) => { pending.push(fn); return pending.length }, clearTimeout: () => {} }
    const fetchImpl = fakeFetch([{ chunks: [frame(null, 'hello')], hang: true }, { chunks: [frame(null, 'hello')], hang: true }])
    const s = createEventStream({ url: '/e', getToken: () => 't', onEvent() {}, fetchImpl, sleep: noSleep, timers })
    s.start(); await until(() => pending.length > 0)
    pending[pending.length - 1]()                                                  // the watchdog fires: no bytes for too long
    await until(() => fetchImpl.calls.length === 2); s.stop()
    expect(fetchImpl.calls.length).toBe(2)
  })

  it('stop() ends the loop and aborts the open request', async () => {
    const fetchImpl = fakeFetch([{ chunks: [frame(null, 'hello')], hang: true }])
    const statuses = []
    const s = createEventStream({ url: '/e', getToken: () => 't', onEvent() {}, onStatus: (x) => statuses.push(x), fetchImpl, sleep: noSleep })
    s.start(); await until(() => statuses.includes('open')); s.stop()
    await until(() => s.status === 'closed')
    expect(fetchImpl.calls.length).toBe(1)
  })

  it('a throwing handler does not kill the stream', async () => {
    const seen = []
    const fetchImpl = fakeFetch([{ chunks: [frame('1-0', 'a'), frame('2-0', 'b')], hang: true }])
    const s = createEventStream({ url: '/e', getToken: () => 't', onEvent: (t) => { seen.push(t); if (t === 'a') throw new Error('boom') }, fetchImpl, sleep: noSleep })
    const orig = console.error; console.error = () => {}
    s.start(); await until(() => seen.length === 2); s.stop(); console.error = orig
    expect(seen).toEqual(['a', 'b'])
  })
})

import { describe, it, expect } from 'vitest'
import { applyTrackingState, buildFix, classifyTrackingError, createSeq, isStale, remoteFromEvent, SEQ_EPOCH_MS } from '../src/lib/trackingPayload.js'

const pos = (coords, timestamp = 1_800_000_000_000) => ({ coords: { latitude: 17.385, longitude: 78.4867, accuracy: 9, heading: null, speed: null, ...coords }, timestamp })

describe('buildFix', () => {
  it('sends only what the device actually reported', () => {
    expect(buildFix(pos({}), { seq: 4 })).toEqual({ latitude: 17.385, longitude: 78.4867, accuracy_m: 9, timestamp: 1_800_000_000_000, seq: 4 })
  })
  it('includes heading, speed and the session id when present', () => {
    const f = buildFix(pos({ heading: 90, speed: 4.2 }), { seq: 1, sessionId: 'abc' })
    expect(f.heading).toBe(90); expect(f.speed).toBe(4.2); expect(f.tracking_session_id).toBe('abc')
  })
  it('drops values the server would refuse instead of sending them', () => {
    const f = buildFix(pos({ heading: NaN, speed: -1, accuracy: Infinity }), { seq: 1 })
    expect('heading' in f).toBe(false); expect('speed' in f).toBe(false); expect('accuracy_m' in f).toBe(false)
    expect('speed' in buildFix(pos({ speed: 500 }), { seq: 1 })).toBe(false)
    expect('timestamp' in buildFix({ coords: pos({}).coords }, { seq: 1 })).toBe(false)
  })
})

describe('createSeq', () => {
  it('always increases, even if the clock stands still or goes backwards', () => {
    let t = SEQ_EPOCH_MS + 100_000
    const next = createSeq(() => t)
    const a = next(), b = next(); t -= 50_000; const c = next()
    expect(b).toBeGreaterThan(a); expect(c).toBeGreaterThan(b)
  })
  it('a fresh page (or another device) starts above anything an earlier page sent', () => {
    let t = SEQ_EPOCH_MS + 1_000_000
    const first = createSeq(() => t); first(); first(); const last = first()
    t += 10_000
    expect(createSeq(() => t)()).toBeGreaterThan(last)
  })
  it('is never negative', () => { expect(createSeq(() => 0)()).toBe(0) })
})

describe('classifyTrackingError', () => {
  it.each([
    ['Live sharing is off for this delivery. Start sharing first.', 'ended'],
    ['That sharing session has ended. Start sharing again.', 'ended'],
    ['The sharing time limit was reached and sharing has stopped. Start sharing again if you are still delivering.', 'ended'],
    ['Sharing is paused. Resume it to continue.', 'paused'],
    ['Positions are accepted every few seconds. Please slow down.', 'slow'],
    ['Too many position updates. Please slow down.', 'slow'],
    ['That position is out of date (the device sent an old reading). Wait for a fresh GPS fix.', 'bad_time'],
    ['The device clock looks wrong: the position is dated in the future.', 'bad_time'],
    ['Something else', 'other'],
  ])('%s -> %s', (msg, kind) => { expect(classifyTrackingError(msg)).toBe(kind) })
})

describe('staleness and live events', () => {
  it('a position that stopped updating becomes "last known" on the client even if no new message arrives', () => {
    expect(isStale(10)).toBe(false); expect(isStale(120)).toBe(false); expect(isStale(121)).toBe(true)
    expect(isStale(null)).toBe(true); expect(isStale(5, true)).toBe(true)
  })
  it('a location event looks like the HTTP response and is fresh', () => {
    const r = remoteFromEvent({ latitude: 1.5, longitude: 2.5, accuracy_m: 8, recorded_at: 'x' }, 42)
    expect(r).toEqual({ sharing: true, has_position: true, latitude: 1.5, longitude: 2.5, accuracy_m: 8, age_seconds: 0, stale: false, recorded_at: 'x', fetchedAt: 42 })
  })
  it('tracking-state events hide the marker when paused or stopped, and keep it when resumed', () => {
    const before = { sharing: true, has_position: true, latitude: 1, longitude: 2 }
    expect(applyTrackingState(before, 'paused')).toEqual({ sharing: true, paused: true, has_position: false })
    expect(applyTrackingState(before, 'stopped')).toEqual({ sharing: false, has_position: false })
    expect(applyTrackingState(before, 'resumed').latitude).toBe(1)
    expect(applyTrackingState(null, 'started').sharing).toBe(true)
    expect(applyTrackingState(before, 'unknown')).toBe(before)
  })
})

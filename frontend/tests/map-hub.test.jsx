import { describe, it, expect } from 'vitest'
import { applyLiveEvent, deliveryMarkers, deliveryRisks, etaSummary, filterDeliveries, seedLive } from '../src/lib/mapHub.js'

const NOW = Date.parse('2026-11-05T12:00:00Z')
const hoursAgo = (h) => new Date(NOW - h * 3600_000).toISOString()
const d = (id, status, extra = {}) => ({ id, status, need: { title: `Item ${id}`, category: 'food' }, created_at: hoursAgo(1), milestones: {}, points: {}, ...extra })

describe('filterDeliveries', () => {
  const list = [d(1, 'in_transit'), d(2, 'receipt_confirmed'), d(3, 'accepted', { need: { title: 'x', category: 'medical' } }), d(4, 'delivered', { created_at: hoursAgo(24 * 40) })]
  it('"active" keeps only deliveries a volunteer is holding', () => { expect(filterDeliveries(list, { status: 'active' }, NOW).map((x) => x.id)).toEqual([1, 3, 4]) })
  it('filters by exact status, category and age', () => {
    expect(filterDeliveries(list, { status: 'accepted' }, NOW).map((x) => x.id)).toEqual([3])
    expect(filterDeliveries(list, { category: 'medical' }, NOW).map((x) => x.id)).toEqual([3])
    expect(filterDeliveries(list, { days: 30 }, NOW).map((x) => x.id)).toEqual([1, 2, 3])
  })
  it('copes with missing data', () => { expect(filterDeliveries(null)).toEqual([]); expect(filterDeliveries([{ id: 9, status: 'accepted' }], { days: 7 }, NOW)).toEqual([]) })
})

describe('deliveryMarkers', () => {
  const pts = { pickup: { latitude: 17.4, longitude: 78.4 }, delivery: { latitude: 17.5, longitude: 78.5 } }
  it('draws only the places the server revealed', () => {
    expect(deliveryMarkers([d(1, 'accepted', { points: { pickup: null, delivery: pts.delivery } })], {}, NOW).map((m) => m.id)).toEqual(['d1:dest'])
    expect(deliveryMarkers([d(1, 'accepted', { points: {} })], {}, NOW)).toEqual([])
  })
  it('skips deliveries nobody is carrying', () => { expect(deliveryMarkers([d(1, 'receipt_confirmed', { points: pts }), d(2, 'offered', { points: pts })], {}, NOW)).toEqual([]) })
  it('adds the live volunteer, marked as not-for-fitting, and flags a silent one as last known', () => {
    const live = { 1: { latitude: 17.45, longitude: 78.45, receivedAt: NOW, ageBase: 0 }, 2: { latitude: 17.46, longitude: 78.46, receivedAt: NOW - 300_000, ageBase: 0 } }
    const m = deliveryMarkers([d(1, 'in_transit', { points: pts }), d(2, 'in_transit', { points: pts })], live, NOW)
    const v1 = m.find((x) => x.id === 'd1:vol'), v2 = m.find((x) => x.id === 'd2:vol')
    expect(v1.noFit).toBe(true); expect(v1.stale).toBe(false); expect(v2.stale).toBe(true); expect(v1.kind).toBe('volunteer')
  })
  it('takes the age the server reported into account', () => {
    const m = deliveryMarkers([d(1, 'in_transit')], { 1: { latitude: 17, longitude: 78, receivedAt: NOW, ageBase: 400 } }, NOW)
    expect(m[0].stale).toBe(true)
  })
})

describe('deliveryRisks', () => {
  it('flags long transits, unconfirmed receipts and quantity discrepancies, and nothing else', () => {
    const r = deliveryRisks([
      d(1, 'in_transit', { milestones: { in_transit_at: hoursAgo(7) } }), d(2, 'in_transit', { milestones: { in_transit_at: hoursAgo(2) } }),
      d(3, 'delivered', { milestones: { delivered_at: hoursAgo(30) } }), d(4, 'delivered', { milestones: { delivered_at: hoursAgo(3) } }),
      d(5, 'receipt_confirmed', { quantity_mismatch: true }), d(6, 'accepted'),
    ], NOW)
    expect(r.map((x) => [x.id, x.kind])).toEqual([[1, 'delayed'], [3, 'unconfirmed_receipt'], [5, 'discrepancy']])
  })
  it('ignores missing or unreadable timestamps', () => { expect(deliveryRisks([d(1, 'in_transit', { milestones: { in_transit_at: 'garbage' } }), d(2, 'delivered')], NOW)).toEqual([]) })
})

describe('applyLiveEvent / seedLive', () => {
  it('stores a position from a location event', () => {
    const next = applyLiveEvent({}, 'delivery.location', { task_id: 7, latitude: 17.4, longitude: 78.4, accuracy_m: 8 }, NOW)
    expect(next[7]).toEqual({ latitude: 17.4, longitude: 78.4, accuracy_m: 8, receivedAt: NOW, ageBase: 0 })
  })
  it('ignores events without a usable position or a task', () => {
    const live = { 1: { latitude: 1, longitude: 2, receivedAt: NOW } }
    expect(applyLiveEvent(live, 'delivery.location', { task_id: 7, latitude: 'x', longitude: 4 }, NOW)).toBe(live)
    expect(applyLiveEvent(live, 'delivery.location', { latitude: 1, longitude: 2 }, NOW)).toBe(live)
    expect(applyLiveEvent(live, 'something.else', { task_id: 1 }, NOW)).toBe(live)
  })
  it('forgets the position when sharing pauses or stops, or the leg ends', () => {
    const live = { 7: { latitude: 1, longitude: 2, receivedAt: NOW } }
    expect(applyLiveEvent(live, 'delivery.tracking', { task_id: 7, state: 'paused' }, NOW)).toEqual({})
    expect(applyLiveEvent(live, 'delivery.tracking', { task_id: 7, state: 'stopped' }, NOW)).toEqual({})
    expect(applyLiveEvent(live, 'delivery.status', { task_id: 7, status: 'delivered' }, NOW)).toEqual({})
    expect(applyLiveEvent(live, 'delivery.status', { task_id: 7, status: 'in_transit' }, NOW)).toBe(live)
    expect(applyLiveEvent(live, 'delivery.tracking', { task_id: 7, state: 'resumed' }, NOW)).toBe(live)
  })
  it('does not mutate the previous state', () => {
    const live = Object.freeze({ 7: Object.freeze({ latitude: 1, longitude: 2, receivedAt: NOW }) })
    expect(() => applyLiveEvent(live, 'delivery.tracking', { task_id: 7, state: 'stopped' }, NOW)).not.toThrow()
  })
  it('seeds from an HTTP response and removes the entry when there is no position', () => {
    const live = seedLive({}, 3, { has_position: true, latitude: 17, longitude: 78, age_seconds: 12 }, NOW)
    expect(live[3].ageBase).toBe(12)
    expect(seedLive(live, 3, { has_position: false }, NOW)).toEqual({})
    expect(seedLive(live, 3, { has_position: true, paused: true, latitude: 1 }, NOW)).toEqual({})
    expect(seedLive({}, 4, { has_position: false }, NOW)).toEqual({})
  })
})

describe('etaSummary', () => {
  const route = { duration_s: 1260, distance_m: 11250, traffic_aware: true, arrival_at: '2026-11-05T10:21:00Z', polyline: '_p~iF~ps|U_ulLnnqC' }
  it('describes a road route and says whether traffic was considered', () => {
    const e = etaSummary(route)
    expect(e.headline).toBe('21 min'); expect(e.detail).toMatch(/11 km by road/); expect(e.detail).toMatch(/arrives about/)
    expect(e.traffic).toBe('Includes current traffic'); expect(e.line.length).toBe(2)
    expect(etaSummary({ ...route, traffic_aware: false }).traffic).toBe('Does not include traffic')
  })
  it('returns nothing for a missing or broken route, and tolerates a bad arrival time', () => {
    expect(etaSummary(null)).toBeNull(); expect(etaSummary({})).toBeNull()
    expect(etaSummary({ ...route, arrival_at: 'nope' }).detail).toBe('11 km by road')
  })
})

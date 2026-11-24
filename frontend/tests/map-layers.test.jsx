import { describe, it, expect } from 'vitest'
import { adminCounts, adminMarkers, nearbyNeedMarkers, urgencyKind, DEFAULT_ADMIN_FILTERS } from '../src/lib/mapLayers.js'
import { metresPerPixel, project, ringExtent, haversineKm, fitZoom } from '../src/lib/mapMath.js'

const near = (a, b, eps) => Math.abs(a - b) <= eps
const data = {
  organizations: [{ id: 1, name: 'Hope Home', verified: true, position: { lat: 17.385, lon: 78.4867 } }, { id: 2, name: 'New Home', verified: false, position: { lat: 17.4, lon: 78.5 } }],
  needs: [
    { id: 10, title: 'Meals', urgency: 'high', verified_org: true, position: { lat: 17.385, lon: 78.4867 } },
    { id: 11, title: 'Books', urgency: 'low', verified_org: false, position: { lat: 17.4, lon: 78.5 } }
  ],
  donors: [{ id: 1, name: 'Dana', position: { lat: 17.39, lon: 78.48 } }],
  volunteers: [{ id: 1, name: 'Vik', position: { lat: 17.39, lon: 78.49 } }],
  live_deliveries: [{ task_id: 7, position: { lat: 17.3851, lon: 78.4868 }, stale: false }],
  gaps: [{ need_id: 11 }]
}

describe('pin kinds', () => {
  it('maps urgency to a colour class and falls back safely', () => {
    expect(urgencyKind('High')).toBe('need-high'); expect(urgencyKind('critical')).toBe('need-critical')
    expect(urgencyKind(undefined)).toBe('need'); expect(urgencyKind('weird')).toBe('need')
  })
})

describe('nearby needs markers', () => {
  it('draws the person and each need that has a position, and nothing when no location is shared', () => {
    const out = nearbyNeedMarkers({ located: true, origin: { lat: 17.39, lon: 78.48 }, needs: [{ need_id: 5, title: 'Meals', urgency: 'high', position: { lat: 17.38, lon: 78.49 } }, { need_id: 6, title: 'No pin' }] })
    expect(out.map((m) => m.id)).toEqual(['me', 'need-5']); expect(out[1].kind).toBe('need-high'); expect(out[1].needId).toBe(5)
    expect(nearbyNeedMarkers({ located: false })).toEqual([]); expect(nearbyNeedMarkers(null)).toEqual([])
  })
})

describe('administrator map layers', () => {
  it('shows every layer by default and marks live pins so they never re-zoom the map', () => {
    const out = adminMarkers(data)
    expect(out.length).toBe(7)
    expect(out.find((m) => m.id === 'live-7').noFit).toBe(true)
    expect(out.find((m) => m.id === 'org-2').kind).toBe('org-unverified')
    expect(out.find((m) => m.id === 'need-11').kind).toBe('need-low gap')
  })
  it('turns layers off', () => {
    const out = adminMarkers(data, { layers: { donors: false, volunteers: false, live: false } })
    expect(out.map((m) => m.id).sort()).toEqual(['need-10', 'need-11', 'org-1', 'org-2'])
  })
  it('filters by urgency and by verified organizations', () => {
    expect(adminMarkers(data, { urgency: 'high' }).filter((m) => m.type === 'need').map((m) => m.id)).toEqual(['need-10'])
    const v = adminMarkers(data, { verifiedOnly: true })
    expect(v.some((m) => m.id === 'org-2')).toBe(false); expect(v.some((m) => m.id === 'need-11')).toBe(false)
  })
  it('"only needs with no volunteer in range" leaves just those needs', () => {
    expect(adminMarkers(data, { gapsOnly: true }).map((m) => m.id)).toEqual(['need-11'])
  })
  it('counts each layer and copes with no data', () => {
    expect(adminCounts(data)).toEqual({ organizations: 2, needs: 2, donors: 1, volunteers: 1, live: 1, gaps: 1 })
    expect(adminMarkers(null)).toEqual([]); expect(adminCounts(null).needs).toBe(0)
    expect(DEFAULT_ADMIN_FILTERS.layers.live).toBe(true)
  })
})

describe('search rings', () => {
  it('computes edge points about one radius away and a pixel size that shrinks as you zoom in', () => {
    const [n, s, e, w] = ringExtent(17.385, 78.4867, 25)
    expect(near(haversineKm(17.385, 78.4867, n.lat, n.lon), 25, 0.2)).toBe(true)
    expect(near(haversineKm(17.385, 78.4867, e.lat, e.lon), 25, 0.2)).toBe(true)
    expect(s.lat < 17.385 && w.lon < 78.4867).toBe(true)
    expect(metresPerPixel(17.385, 10) > metresPerPixel(17.385, 12)).toBe(true)
    expect(near(metresPerPixel(0, 0), 156543.03, 1)).toBe(true)
  })
  it('lets a map fit a ring: a 100 km ring needs a lower zoom than a 5 km ring', () => {
    const z = (km) => fitZoom(ringExtent(17.385, 78.4867, km), 600, 340)
    expect(z(100) < z(5)).toBe(true)
  })
  it('a pin dragged right ends up to the right of where it started (pan direction)', () => {
    // TileMap: centerPx = project(centre) - shift; screen x = project(pin).x - (centerPx.x - width/2); dragging right adds +dx to shift
    const screenX = (shiftDx) => project(17.385, 78.4867, 12).x - ((project(17.385, 78.4867, 12).x - shiftDx) - 300)
    expect(screenX(100) > screenX(0)).toBe(true)
  })
})

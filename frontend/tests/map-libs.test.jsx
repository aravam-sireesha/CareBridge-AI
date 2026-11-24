import { describe, it, expect } from 'vitest'
import { decodePolyline, formatDuration, formatRoadDistance } from '../src/lib/polyline.js'
import { clusterMarkers, zoomForHeight } from '../src/lib/clustering.js'
import { loadCesium, resetCesiumLoaderForTests, webglAvailable } from '../src/lib/cesiumLoader.js'

describe('decodePolyline', () => {
  it("decodes Google's documented example", () => {
    const pts = decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@')
    expect(pts).toEqual([{ lat: 38.5, lon: -120.2 }, { lat: 40.7, lon: -120.95 }, { lat: 43.252, lon: -126.453 }])
  })
  it('returns nothing for empty, non-string or garbage input and never throws', () => {
    for (const bad of ['', null, undefined, 42, {}, '!!!!', '\u0000\u0001']) expect(decodePolyline(bad)).toEqual([])
  })
  it('keeps the points it could read from a truncated line', () => {
    const full = '_p~iF~ps|U_ulLnnqC_mqNvxq`@'
    const pts = decodePolyline(full.slice(0, 14))
    expect(pts.length).toBeGreaterThan(0); expect(pts.length).toBeLessThan(3)
  })
  it('stops at the point limit so a hostile response cannot hang the page', () => {
    const many = '??'.repeat(50000)                      // 50 000 identical (0,0) steps
    expect(decodePolyline(many, { maxPoints: 100 }).length).toBe(100)
  })
  it('refuses coordinates that fall outside the world', () => {
    expect(decodePolyline('~~~~~~~~~~~~')).toEqual([])
  })
})

describe('formatting', () => {
  it('formats durations', () => {
    expect(formatDuration(30)).toBe('1 min'); expect(formatDuration(1260)).toBe('21 min'); expect(formatDuration(3900)).toBe('1 h 5 min'); expect(formatDuration(7200)).toBe('2 h')
    expect(formatDuration(-1)).toBe(''); expect(formatDuration(NaN)).toBe('')
  })
  it('formats road distance', () => {
    expect(formatRoadDistance(850)).toBe('850 m'); expect(formatRoadDistance(11250)).toBe('11 km'); expect(formatRoadDistance(2500)).toBe('2.5 km')
    expect(formatRoadDistance(-5)).toBe(''); expect(formatRoadDistance(undefined)).toBe('')
  })
})

const pin = (id, lat, lon, kind = 'need-high') => ({ id, lat, lon, kind, label: id })

describe('clusterMarkers', () => {
  it('groups pins that are close together and keeps distant ones separate', () => {
    const m = [pin('a', 17.385, 78.486), pin('b', 17.3851, 78.4861), pin('c', 17.3852, 78.4862), pin('far', 28.61, 77.2)]
    const out = clusterMarkers(m, 10)
    const cluster = out.find((x) => x.kind === 'cluster')
    expect(cluster.count).toBe(3); expect(cluster.members.sort()).toEqual(['a', 'b', 'c'])
    expect(out.find((x) => x.id === 'far')).toBeTruthy(); expect(out.length).toBe(2)
  })
  it('splits groups apart as the map zooms in', () => {
    const m = [pin('a', 17.385, 78.486), pin('b', 17.395, 78.496)]
    expect(clusterMarkers(m, 8).some((x) => x.kind === 'cluster')).toBe(true)
    expect(clusterMarkers(m, 16).some((x) => x.kind === 'cluster')).toBe(false)
  })
  it("never hides the person's own position or a live volunteer inside a group", () => {
    const m = [pin('me', 17.385, 78.486, 'me'), pin('vol', 17.3851, 78.4861, 'volunteer'), pin('live', 17.3852, 78.4862, 'live'), pin('n1', 17.3853, 78.4863), pin('n2', 17.3854, 78.4864)]
    const out = clusterMarkers(m, 8)
    for (const id of ['me', 'vol', 'live']) expect(out.find((x) => x.id === id)).toBeTruthy()
    expect(out.find((x) => x.kind === 'cluster').count).toBe(2)
  })
  it('puts a group at the average position of its members', () => {
    const out = clusterMarkers([pin('a', 17.0, 78.0), pin('b', 17.0004, 78.0004)], 8)
    expect(out[0].lat).toBeCloseTo(17.0002, 3); expect(out[0].lon).toBeCloseTo(78.0002, 3)
  })
  it('drops pins without usable coordinates and never mutates its input', () => {
    const m = [pin('a', NaN, 1), pin('b', 17, 78), { id: 'c', lat: null, lon: null, kind: 'x' }]
    const copy = JSON.stringify(m.map((x) => ({ ...x })))
    expect(clusterMarkers(m, 10).map((x) => x.id)).toEqual(['b'])
    expect(JSON.stringify(m.map((x) => ({ ...x })))).toBe(copy)
  })
  it('handles empty input', () => { expect(clusterMarkers([], 10)).toEqual([]) })
  it('maps camera height to a sensible zoom', () => {
    expect(zoomForHeight(500)).toBeGreaterThan(zoomForHeight(50000)); expect(zoomForHeight(0)).toBe(14); expect(zoomForHeight(NaN)).toBe(14)
    expect(zoomForHeight(1e9)).toBe(3); expect(zoomForHeight(1)).toBe(18)
  })
})

function fakeDom({ webgl = true, outcome = 'load' } = {}) {
  const appended = []
  const doc = {
    head: { appendChild: (n) => { appended.push(n); if (n.tagName === 'script') setTimeout(() => (outcome === 'load' ? (win.Cesium = { ok: true }, n.onload()) : n.onerror()), 0) } },
    createElement: (tag) => (tag === 'canvas'
      ? { getContext: () => (webgl ? {} : null) }
      : { tagName: tag, remove() {}, set src(v) { this._src = v }, get src() { return this._src } }),
  }
  const win = {}
  return { doc, win, appended }
}

describe('loadCesium', () => {
  it('loads the pinned version from the CDN once and sets the asset base URL', async () => {
    resetCesiumLoaderForTests()
    const { doc, win, appended } = fakeDom()
    const [a, b] = await Promise.all([loadCesium({ version: '1.121', doc, win }), loadCesium({ version: '1.121', doc, win })])
    expect(a).toBe(b); expect(win.CESIUM_BASE_URL).toBe('https://cesium.com/downloads/cesiumjs/releases/1.121/Build/Cesium')
    expect(appended.filter((n) => n.tagName === 'script').length).toBe(1)
    expect(appended.find((n) => n.tagName === 'script').src).toBe('https://cesium.com/downloads/cesiumjs/releases/1.121/Build/Cesium/Cesium.js')
  })
  it('refuses a version string that could point somewhere else', async () => {
    resetCesiumLoaderForTests()
    for (const v of ['../../evil', '1.121/../x', 'latest', '1.2.3.4', '']) {
      const { doc, win } = fakeDom(); resetCesiumLoaderForTests()
      await expect(loadCesium({ version: v, doc, win })).rejects.toThrow()
    }
  })
  it('explains when WebGL is missing, without trying to download anything', async () => {
    resetCesiumLoaderForTests()
    const { doc, win, appended } = fakeDom({ webgl: false })
    await expect(loadCesium({ doc, win })).rejects.toThrow(/WebGL/)
    expect(appended.length).toBe(0); expect(webglAvailable(doc)).toBe(false)
  })
  it('reports a failed download and allows a retry', async () => {
    resetCesiumLoaderForTests()
    const bad = fakeDom({ outcome: 'error' })
    await expect(loadCesium({ doc: bad.doc, win: bad.win })).rejects.toThrow(/could not be downloaded/)
    const good = fakeDom()
    await expect(loadCesium({ doc: good.doc, win: good.win })).resolves.toBeTruthy()
  })
})

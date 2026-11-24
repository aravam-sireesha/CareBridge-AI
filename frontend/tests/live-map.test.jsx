import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react'
import LiveMap from '../src/components/map/LiveMap.jsx'
import CesiumView from '../src/components/map/CesiumView.jsx'
import { api } from '../src/api/client.js'

// ---------------------------------------------------------------- a fake Cesium that records what it is asked to do
function makeCesium({ tileset = 'ok' } = {}) {
  const rec = { viewers: [], entities: [], handlers: [], tilesets: [], flyTo: [], fly: [], providers: [], destroyed: 0, handlerDestroyed: 0, render: 0, keySet: null }
  class Handler { constructor() { this.actions = {}; rec.handlers.push(this) } setInputAction(fn, type) { this.actions[type] = fn } destroy() { rec.handlerDestroyed++ } }
  class Viewer {
    constructor(el, opts) {
      this.el = el; this.opts = opts; rec.viewers.push(this); this._destroyed = false
      this.entities = { removeAll: () => { rec.entities = [] }, add: (e) => { rec.entities.push(e); return e } }
      this.imageryLayers = { addImageryProvider: (p) => rec.providers.push(p) }
      this.scene = { canvas: {}, globe: { show: true }, primitives: { add: (t) => rec.tilesets.push(t) }, pick: (pos) => this.pickResult, requestRender: () => { rec.render++ }, renderError: { addEventListener: (fn) => { this.renderErrorFn = fn } } }
      this.camera = { percentageChanged: 0, changed: { addEventListener: (fn) => { this.changedFn = fn } }, flyTo: (a) => rec.fly.push(a), flyToBoundingSphere: (s, o) => rec.flyTo.push({ s, o }), positionCartographic: { height: 5000 } }
    }
    isDestroyed() { return this._destroyed }
    destroy() { this._destroyed = true; rec.destroyed++ }
  }
  const C = {
    Viewer, ScreenSpaceEventHandler: Handler, ScreenSpaceEventType: { LEFT_CLICK: 'click' },
    UrlTemplateImageryProvider: class { constructor(o) { Object.assign(this, o) } },
    Cartesian3: { fromDegrees: (lon, lat, h = 0) => ({ lon, lat, h }), fromDegreesArray: (a) => a },
    Cartesian2: class { constructor(x, y) { this.x = x; this.y = y } },
    Color: { fromCssColorString: (c) => ({ css: c }), WHITE: { css: '#fff' } },
    LabelStyle: { FILL_AND_OUTLINE: 2 }, PolylineOutlineMaterialProperty: class { constructor(o) { Object.assign(this, o) } },
    BoundingSphere: { fromPoints: (p) => ({ radius: p.length > 1 ? 1000 : 0, n: p.length }) }, HeadingPitchRange: class { constructor(h, p, r) { this.range = r } },
    Math: { toRadians: (d) => (d * Math.PI) / 180 }, GoogleMaps: { defaultApiKey: null },
  }
  if (tileset !== 'missing') C.createGooglePhotorealistic3DTileset = async () => { if (tileset === 'fail') throw new Error('403'); return { show: true, isTileset: true } }
  return { C, rec }
}
const pin = (id, lat, lon, kind = 'need-high', extra = {}) => ({ id, lat, lon, kind, label: id, ...extra })
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })

afterEach(() => cleanup())

// ---------------------------------------------------------------- CesiumView
describe('CesiumView', () => {
  it('starts on OpenStreetMap imagery with no Cesium ion dependency', () => {
    const { C, rec } = makeCesium()
    render(<CesiumView cesium={C} markers={[]} />)
    expect(rec.viewers[0].opts.baseLayer).toBe(false)
    expect(rec.viewers[0].opts.geocoder).toBe(false)                      // Cesium's own geocoder would need an ion token
    expect(rec.providers[0].url).toBe('https://tile.openstreetmap.org/{z}/{x}/{y}.png')
  })

  it('without a browser key it says so and never touches the Google tiles', async () => {
    const { C, rec } = makeCesium(); const why = vi.fn()
    render(<CesiumView cesium={C} markers={[]} onTilesUnavailable={why} />)
    await flush()
    expect(why).toHaveBeenCalledWith('no_key'); expect(rec.tilesets.length).toBe(0); expect(C.GoogleMaps.defaultApiKey).toBeNull()
  })

  it('with a key it adds the photorealistic tiles and hides the street globe under them', async () => {
    const { C, rec } = makeCesium()
    render(<CesiumView cesium={C} markers={[]} apiKey="BROWSER-KEY" layer="satellite" />)
    await flush()
    expect(C.GoogleMaps.defaultApiKey).toBe('BROWSER-KEY'); expect(rec.tilesets.length).toBe(1)
    expect(rec.tilesets[0].show).toBe(true); expect(rec.viewers[0].scene.globe.show).toBe(false)
  })

  it('switching to Streets hides the tiles and shows the globe again', async () => {
    const { C, rec } = makeCesium()
    const { rerender } = render(<CesiumView cesium={C} markers={[]} apiKey="K" layer="satellite" />)
    await flush()
    rerender(<CesiumView cesium={C} markers={[]} apiKey="K" layer="streets" />)
    expect(rec.tilesets[0].show).toBe(false); expect(rec.viewers[0].scene.globe.show).toBe(true)
  })

  it.each([['fail', 'unavailable'], ['missing', 'unsupported']])('tile problem "%s" is reported as %s and the globe keeps working', async (mode, expected) => {
    const { C, rec } = makeCesium({ tileset: mode }); const why = vi.fn()
    render(<CesiumView cesium={C} markers={[pin('a', 17.4, 78.4)]} apiKey="K" onTilesUnavailable={why} />)
    await flush()
    expect(why).toHaveBeenCalledWith(expected); expect(rec.tilesets.length).toBe(0); expect(rec.entities.length).toBe(1)
  })

  it('draws one entity per marker with a stable id, and replaces them when the data changes', () => {
    const { C, rec } = makeCesium()
    const { rerender } = render(<CesiumView cesium={C} markers={[pin('a', 17.4, 78.4), pin('b', 17.5, 78.5, 'org')]} />)
    expect(rec.entities.map((e) => e.id)).toEqual(['a', 'b'])
    rerender(<CesiumView cesium={C} markers={[pin('c', 17.6, 78.6)]} />)
    expect(rec.entities.map((e) => e.id)).toEqual(['c'])
  })

  it('skips pins without usable coordinates', () => {
    const { C, rec } = makeCesium()
    render(<CesiumView cesium={C} markers={[pin('a', NaN, 78), pin('b', 17, 78), { id: 'c' }]} />)
    expect(rec.entities.map((e) => e.id)).toEqual(['b'])
  })

  it('marks last-known (stale) positions as such', () => {
    const { C, rec } = makeCesium()
    render(<CesiumView cesium={C} markers={[pin('vol', 17.4, 78.4, 'volunteer', { stale: true })]} />)
    expect(rec.entities[0].label.text).toContain('(last known)'); expect(rec.entities[0].point.color.css).toBe('#9ca3af')
  })

  it('draws a route line only when it has at least two points', () => {
    const { C, rec } = makeCesium()
    const { rerender } = render(<CesiumView cesium={C} markers={[]} lines={[{ id: 'r', points: [{ lat: 17.4, lon: 78.4 }] }]} />)
    expect(rec.entities.some((e) => e.polyline)).toBe(false)
    rerender(<CesiumView cesium={C} markers={[]} lines={[{ id: 'r', points: [{ lat: 17.4, lon: 78.4 }, { lat: 17.5, lon: 78.5 }] }]} />)
    const line = rec.entities.find((e) => e.polyline)
    expect(line.id).toBe('line-r'); expect(line.polyline.positions).toEqual([78.4, 17.4, 78.5, 17.5])
  })

  it('reports a click on a pin', () => {
    const { C, rec } = makeCesium(); const onSelect = vi.fn()
    render(<CesiumView cesium={C} markers={[pin('m1', 17.4, 78.4)]} onSelect={onSelect} />)
    rec.viewers[0].pickResult = { id: { id: 'm1' } }
    rec.handlers[0].actions.click({ position: { x: 1, y: 1 } })
    expect(onSelect).toHaveBeenCalledWith('m1')
    rec.viewers[0].pickResult = undefined; rec.handlers[0].actions.click({ position: {} })
    expect(onSelect).toHaveBeenCalledTimes(1)                              // a click on empty ground selects nothing
  })

  it('fits the camera when the set of pins changes, but not when a moving (noFit) pin moves', () => {
    const { C, rec } = makeCesium()
    const fixed = pin('org', 17.4, 78.4)
    const { rerender } = render(<CesiumView cesium={C} markers={[fixed, pin('vol', 17.41, 78.41, 'volunteer', { noFit: true })]} />)
    expect(rec.flyTo.length).toBe(1)
    rerender(<CesiumView cesium={C} markers={[fixed, pin('vol', 17.42, 78.42, 'volunteer', { noFit: true })]} />)
    expect(rec.flyTo.length).toBe(1)
    rerender(<CesiumView cesium={C} markers={[fixed, pin('org2', 17.9, 78.9)]} />)
    expect(rec.flyTo.length).toBe(2)
  })

  it('flies to a requested place and reports camera height for grouping', () => {
    const { C, rec } = makeCesium(); const onHeight = vi.fn()
    const { rerender } = render(<CesiumView cesium={C} markers={[]} onHeightChange={onHeight} />)
    rec.viewers[0].changedFn()
    expect(onHeight).toHaveBeenCalledWith(5000)
    rerender(<CesiumView cesium={C} markers={[]} onHeightChange={onHeight} focus={{ lat: 17.4, lon: 78.4, key: 'k1' }} />)
    expect(rec.fly.length).toBe(1); expect(rec.fly[0].destination).toEqual({ lon: 78.4, lat: 17.4, h: 900 })
  })

  it('destroys the viewer and its event handler on unmount (no leaked WebGL contexts)', () => {
    const { C, rec } = makeCesium()
    const { unmount } = render(<CesiumView cesium={C} markers={[]} />)
    unmount()
    expect(rec.destroyed).toBe(1); expect(rec.handlerDestroyed).toBe(1)
  })

  it('reports a viewer that cannot start, and a rendering failure later', () => {
    const { C } = makeCesium(); const onError = vi.fn()
    C.Viewer = class { constructor() { throw new Error('WebGL context lost') } }
    render(<CesiumView cesium={C} markers={[]} onError={onError} />)
    expect(onError).toHaveBeenCalledWith('WebGL context lost')
    const ok = makeCesium(); const onError2 = vi.fn()
    render(<CesiumView cesium={ok.C} markers={[]} onError={onError2} />)
    ok.rec.viewers[0].renderErrorFn()
    expect(onError2).toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------- LiveMap
let geo
beforeEach(() => {
  api.mapsConfig = vi.fn().mockResolvedValue({ geocoding: false, routes: false })
  api.mapsAutocomplete = vi.fn().mockResolvedValue({ suggestions: [] })
  api.mapsPlace = vi.fn().mockResolvedValue({ latitude: 17.41, longitude: 78.43 })
  geo = { getCurrentPosition: vi.fn((ok) => ok({ coords: { latitude: 17.4, longitude: 78.45, accuracy: 20 } })) }
  Object.defineProperty(navigator, 'geolocation', { value: geo, configurable: true })
})
const spread = [pin('far1', 17.0, 78.0), pin('far2', 18.0, 79.0), pin('far3', 17.0, 79.0), pin('far4', 18.0, 78.0)]
const packed = (n) => Array.from({ length: n }, (_, i) => pin(`p${i}`, 17.5 + i * 0.00001, 78.5 + i * 0.00001, 'need-medium'))

describe('LiveMap', () => {
  it('opens in 2D, with the view and layer controls labelled', () => {
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} cesiumLoader={async () => { throw new Error('unused') }} />)
    expect(screen.getByRole('group', { name: 'Map view' })).toBeTruthy()
    expect(screen.getByText('2D').getAttribute('aria-pressed')).toBe('true')
    expect(screen.queryByRole('group', { name: '3D layer' })).toBeNull()
    expect(document.querySelector('[data-marker="a"]')).toBeTruthy()
  })

  it('switches to the 3D view when the library loads', async () => {
    const { C, rec } = makeCesium()
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} cesiumLoader={async () => C} apiKey="K" />)
    fireEvent.click(screen.getByText('3D'))
    await waitFor(() => expect(rec.viewers.length).toBe(1))
    expect(screen.getByText('3D').getAttribute('aria-pressed')).toBe('true')
    expect(screen.queryByRole('group', { name: '3D layer' })).toBeTruthy()
    await waitFor(() => expect(rec.tilesets.length).toBe(1))
  })

  it('stays on the 2D map and explains why when 3D cannot load (offline, no WebGL, blocked)', async () => {
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} cesiumLoader={async () => { throw new Error('This device or browser does not support the 3D map (WebGL).') }} />)
    fireEvent.click(screen.getByText('3D'))
    await waitFor(() => expect(screen.queryByText(/does not support the 3D map/)).toBeTruthy())
    expect(screen.queryByText(/Showing the standard map instead/)).toBeTruthy()
    expect(screen.getByText('2D').getAttribute('aria-pressed')).toBe('true')
    expect(document.querySelector('[data-marker="a"]')).toBeTruthy()      // the data is still on screen
  })

  it('without a Google browser key, 3D still works on street imagery and Satellite is disabled with an explanation', async () => {
    const { C } = makeCesium()
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} cesiumLoader={async () => C} apiKey="" />)
    fireEvent.click(screen.getByText('3D'))
    await waitFor(() => expect(screen.queryByText(/need a Google Maps key/)).toBeTruthy())
    expect(screen.getByText('Satellite').disabled).toBe(true)
    expect(screen.getByText('Streets').getAttribute('aria-pressed')).toBe('true')
  })

  it('tells the person when 3D buildings are unavailable here (no coverage / refused) and falls back to streets', async () => {
    const { C } = makeCesium({ tileset: 'fail' })
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} cesiumLoader={async () => C} apiKey="K" />)
    fireEvent.click(screen.getByText('3D'))
    await waitFor(() => expect(screen.queryByText(/3D buildings are not available here/)).toBeTruthy())
    expect(screen.getByText('Satellite').disabled).toBe(true)
  })

  it('falls back to 2D if the 3D view crashes while running', async () => {
    const { C, rec } = makeCesium()
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} cesiumLoader={async () => C} />)
    fireEvent.click(screen.getByText('3D'))
    await waitFor(() => expect(rec.viewers.length).toBe(1))
    await act(async () => { rec.viewers[0].renderErrorFn() })
    await waitFor(() => expect(screen.getByText('2D').getAttribute('aria-pressed')).toBe('true'))
    expect(screen.queryByText(/Showing the standard map instead/)).toBeTruthy()
  })

  it('shows a loading skeleton, then an error with a working retry', () => {
    const retry = vi.fn()
    const { rerender } = render(<LiveMap markers={[]} loading />)
    expect(screen.getByRole('status').textContent).toContain('Loading map')
    rerender(<LiveMap markers={[]} error="Could not load the map data." onRetry={retry} />)
    expect(screen.getByRole('alert').textContent).toContain('Could not load the map data.')
    fireEvent.click(screen.getByText('Try again')); expect(retry).toHaveBeenCalledTimes(1)
  })

  it('passes a normal pin selection to the page', () => {
    const onSelect = vi.fn()
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} onSelect={onSelect} />)
    fireEvent.click(document.querySelector('[data-marker="a"]'))
    expect(onSelect).toHaveBeenCalledTimes(1); expect(onSelect.mock.calls[0][0].id).toBe('a')
  })

  it('groups a crowd of nearby pins, opens a group on click, and regroups on request', async () => {
    const onSelect = vi.fn()
    render(<LiveMap markers={[...packed(20), ...spread]} onSelect={onSelect} />)
    const group = await waitFor(() => { const g = document.querySelector('.cbmap-marker--cluster'); if (!g) throw new Error('no group yet'); return g })
    expect(group.textContent).toContain('20')
    expect(document.querySelector('[data-marker="p0"]')).toBeNull()
    fireEvent.click(group)
    await waitFor(() => expect(document.querySelector('[data-marker="p0"]')).toBeTruthy())
    expect(onSelect).toHaveBeenCalledTimes(0)                              // opening a group is not "selecting a place"
    fireEvent.click(screen.getByText('Group pins again'))
    await waitFor(() => expect(document.querySelector('[data-marker="p0"]')).toBeNull())
  })

  it('never groups the person\'s own location', async () => {
    render(<LiveMap markers={[...packed(20), ...spread]} />)
    fireEvent.click(screen.getByText('Use my location'))
    await waitFor(() => expect(document.querySelector('[data-marker="you-are-here"]')).toBeTruthy())
  })

  it('"Use my location" explains a blocked permission instead of failing silently', async () => {
    geo.getCurrentPosition = vi.fn((ok, err) => err({ code: 1 }))
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} />)
    fireEvent.click(screen.getByText('Use my location'))
    await waitFor(() => expect(screen.queryByText(/Location permission was blocked/)).toBeTruthy())
    expect(document.querySelector('[data-marker="you-are-here"]')).toBeNull()
  })

  it('shows no search box unless the server has address search switched on', async () => {
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} />)
    await flush()
    expect(screen.queryByLabelText('Search an address or area')).toBeNull()
  })

  it('searches an address through the server and keeps one billing session from first keystroke to the pick', async () => {
    api.mapsConfig = vi.fn().mockResolvedValue({ geocoding: true, routes: false })
    api.mapsAutocomplete = vi.fn().mockResolvedValue({ suggestions: [{ place_id: 'ChIJabcdefghijk', text: 'Banjara Hills, Hyderabad', main_text: 'Banjara Hills', secondary_text: 'Hyderabad' }] })
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} />)
    const input = await screen.findByLabelText('Search an address or area')
    fireEvent.change(input, { target: { value: 'banj' } })
    expect(api.mapsAutocomplete).toHaveBeenCalledTimes(0)                  // debounced: not on every key
    const option = await screen.findByRole('option', {}, { timeout: 2000 })
    const sessionFromSearch = api.mapsAutocomplete.mock.calls[0][1].session
    fireEvent.click(option)
    await waitFor(() => expect(api.mapsPlace).toHaveBeenCalledTimes(1))
    expect(api.mapsPlace.mock.calls[0][0]).toBe('ChIJabcdefghijk'); expect(api.mapsPlace.mock.calls[0][1]).toBe(sessionFromSearch)
    await waitFor(() => expect(document.querySelector('[data-marker="you-are-here"]')).toBeTruthy())
  })

  it('does not search for fewer than three characters', async () => {
    api.mapsConfig = vi.fn().mockResolvedValue({ geocoding: true })
    render(<LiveMap markers={[]} />)
    fireEvent.change(await screen.findByLabelText('Search an address or area'), { target: { value: 'ba' } })
    await new Promise((r) => setTimeout(r, 450))
    expect(api.mapsAutocomplete).toHaveBeenCalledTimes(0)
  })

  it('shows a search error without breaking the map', async () => {
    api.mapsConfig = vi.fn().mockResolvedValue({ geocoding: true })
    api.mapsAutocomplete = vi.fn().mockRejectedValue(new Error('The map service is busy. Please try again shortly.'))
    render(<LiveMap markers={[pin('a', 17.4, 78.4)]} />)
    fireEvent.change(await screen.findByLabelText('Search an address or area'), { target: { value: 'banjara' } })
    await waitFor(() => expect(screen.queryByText(/map service is busy/)).toBeTruthy(), { timeout: 2000 })
    expect(document.querySelector('[data-marker="a"]')).toBeTruthy()
  })

  it('in 3D, choosing a group flies the camera in instead of opening it', async () => {
    const { C, rec } = makeCesium()
    render(<LiveMap markers={[...packed(20), ...spread]} cesiumLoader={async () => C} apiKey="K" />)
    fireEvent.click(screen.getByText('3D'))
    await waitFor(() => expect(rec.viewers.length).toBe(1))
    const cluster = rec.entities.find((e) => String(e.id).startsWith('cluster-'))
    expect(cluster).toBeTruthy()
    rec.viewers[0].pickResult = { id: { id: cluster.id } }
    await act(async () => { rec.handlers[0].actions.click({ position: {} }) })
    await waitFor(() => expect(rec.fly.length).toBe(1))
    expect(rec.fly[0].destination.h).toBe(1500)
  })
})

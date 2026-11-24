import React, { useEffect, useRef } from 'react'
import { LEGEND_COLOURS } from '../../lib/mapLayers.js'

const FALLBACK_COLOUR = '#0f766e'
const colourFor = (m) => (m.stale ? '#9ca3af' : m.kind === 'cluster' ? '#115E59' : LEGEND_COLOURS[m.kind] || FALLBACK_COLOUR)

/**
 * The 3D map. `cesium` is the already-loaded global (see lib/cesiumLoader.js), so this component never downloads anything itself.
 *  - Base: OpenStreetMap imagery on the globe ("streets"), plus Google Photorealistic 3D Tiles ("satellite") when a browser key is given.
 *  - If the 3D Tiles cannot be created (no key, no coverage, quota, old Cesium) it says so through onTilesUnavailable and keeps working
 *    on the OpenStreetMap globe. It never hides the tiles' attribution: Cesium's credit display is left switched on, as Google requires.
 *  - Draws only what it is given. No simulated positions.
 * Real rendering needs WebGL and cannot be verified without a browser; the wiring is unit-tested with a fake Cesium.
 */
export default function CesiumView({ cesium: C, markers, lines = [], layer = 'satellite', apiKey, focus, selectedId, onSelect, onHeightChange, onTilesUnavailable, onError, height = 420, ariaLabel = '3D map' }) {
  const box = useRef(null)
  const state = useRef({ viewer: null, handler: null, tileset: null, fitKey: null, destroyed: false })
  const cb = useRef({})
  cb.current = { onSelect, onHeightChange, onTilesUnavailable, onError, markers }

  // create once, destroy on unmount
  useEffect(() => {
    const s = state.current
    s.destroyed = false
    let viewer
    try {
      viewer = new C.Viewer(box.current, {
        baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false, navigationHelpButton: false,
        animation: false, timeline: false, fullscreenButton: false, infoBox: false, selectionIndicator: false, requestRenderMode: true,
      })
      viewer.imageryLayers.addImageryProvider(new C.UrlTemplateImageryProvider({ url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', maximumLevel: 19, credit: '© OpenStreetMap contributors' }))
      s.viewer = viewer
      viewer.scene.renderError?.addEventListener?.(() => cb.current.onError?.('The 3D view stopped working on this device.'))
      s.handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas)
      s.handler.setInputAction((click) => {
        const picked = viewer.scene.pick(click.position)
        const id = picked && picked.id && picked.id.id
        if (id) cb.current.onSelect?.(String(id))
      }, C.ScreenSpaceEventType.LEFT_CLICK)
      viewer.camera.percentageChanged = 0.25
      viewer.camera.changed.addEventListener(() => { const h = viewer.camera.positionCartographic?.height; if (Number.isFinite(h)) cb.current.onHeightChange?.(h) })
    } catch (e) {
      cb.current.onError?.(e && e.message ? e.message : 'The 3D view could not start.')
      return undefined
    }
    return () => {
      s.destroyed = true
      try { s.handler?.destroy() } catch { /* already gone */ }
      try { if (viewer && !viewer.isDestroyed()) viewer.destroy() } catch { /* already gone */ }
      s.viewer = s.handler = s.tileset = null
    }
  }, [C])

  // Google Photorealistic 3D Tiles (only with a key; failure is reported, never fatal)
  useEffect(() => {
    const s = state.current
    if (!s.viewer || s.tileset || !apiKey) { if (!apiKey) cb.current.onTilesUnavailable?.('no_key'); return undefined }
    let cancelled = false
    ;(async () => {
      try {
        if (typeof C.createGooglePhotorealistic3DTileset !== 'function' || !C.GoogleMaps) throw new Error('unsupported')
        C.GoogleMaps.defaultApiKey = apiKey
        const tileset = await C.createGooglePhotorealistic3DTileset()
        if (cancelled || s.destroyed || !s.viewer) return
        s.tileset = tileset
        s.viewer.scene.primitives.add(tileset)
        tileset.show = layer === 'satellite'
        s.viewer.scene.globe.show = layer !== 'satellite'
        s.viewer.scene.requestRender()
      } catch (e) {
        if (!cancelled) cb.current.onTilesUnavailable?.(e && e.message === 'unsupported' ? 'unsupported' : 'unavailable')
      }
    })()
    return () => { cancelled = true }
  }, [C, apiKey])                                                         // eslint-disable-line react-hooks/exhaustive-deps

  // satellite <-> streets
  useEffect(() => {
    const s = state.current
    if (!s.viewer) return
    if (s.tileset) { s.tileset.show = layer === 'satellite'; s.viewer.scene.globe.show = layer !== 'satellite' } else s.viewer.scene.globe.show = true
    s.viewer.scene.requestRender()
  }, [layer])

  // pins and route lines
  useEffect(() => {
    const s = state.current; const viewer = s.viewer
    if (!viewer) return
    viewer.entities.removeAll()
    const positions = []
    for (const m of markers) {
      if (!Number.isFinite(m.lat) || !Number.isFinite(m.lon)) continue
      const pos = C.Cartesian3.fromDegrees(m.lon, m.lat)
      positions.push(pos)
      viewer.entities.add({
        id: String(m.id), position: pos,
        point: { pixelSize: m.kind === 'cluster' ? 26 : selectedId === m.id ? 18 : 13, color: C.Color.fromCssColorString(colourFor(m)), outlineColor: C.Color.WHITE, outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
        label: { text: m.kind === 'cluster' ? String(m.count) : `${m.label || ''}${m.stale ? ' (last known)' : ''}`, font: m.kind === 'cluster' ? 'bold 13px sans-serif' : '12px sans-serif',
                 style: C.LabelStyle.FILL_AND_OUTLINE, fillColor: C.Color.WHITE, outlineColor: C.Color.fromCssColorString('#23342F'), outlineWidth: 3,
                 pixelOffset: new C.Cartesian2(0, m.kind === 'cluster' ? 0 : -20), disableDepthTestDistance: Number.POSITIVE_INFINITY, show: m.kind === 'cluster' || markers.length <= 40 || selectedId === m.id },
      })
    }
    for (const l of lines) {
      const flat = (l.points || []).filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon)).flatMap((p) => [p.lon, p.lat])
      if (flat.length < 4) continue
      const colour = C.Color.fromCssColorString(l.color || '#2563eb')
      viewer.entities.add({ id: `line-${l.id}`, polyline: { positions: C.Cartesian3.fromDegreesArray(flat), width: 7, material: new C.PolylineOutlineMaterialProperty({ color: colour, outlineWidth: 2, outlineColor: C.Color.WHITE }), depthFailMaterial: colour } })
    }
    const key = markers.filter((m) => !m.noFit).map((m) => `${m.id}:${m.lat?.toFixed?.(4)},${m.lon?.toFixed?.(4)}`).join('|')
    if (positions.length && key !== s.fitKey) {                           // fit the camera when the SET of pins changes, not on every live position update
      s.fitKey = key
      const sphere = C.BoundingSphere.fromPoints(positions)
      viewer.camera.flyToBoundingSphere(sphere, { duration: 0.8, offset: new C.HeadingPitchRange(0, C.Math.toRadians(-40), Math.max(sphere.radius * 2.5, 700)) })
    }
    viewer.scene.requestRender()
  }, [C, markers, lines, selectedId])

  // move the camera onto a place the page asked for (a search result, a clicked list row)
  const focusKey = focus ? focus.key : null
  useEffect(() => {
    const viewer = state.current.viewer
    if (!viewer || !focus || !Number.isFinite(focus.lat) || !Number.isFinite(focus.lon)) return
    viewer.camera.flyTo({ destination: C.Cartesian3.fromDegrees(focus.lon, focus.lat, focus.height || 900), orientation: { heading: 0, pitch: C.Math.toRadians(-45), roll: 0 }, duration: 1.2 })
  }, [focusKey])                                                          // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={box} className="cbmap3d" style={{ height }} role="application" aria-label={`${ariaLabel}. Drag to move, scroll to zoom, hold Ctrl and drag to tilt.`} tabIndex={0} />
}

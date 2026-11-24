import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import '../../map.css'
import TileMap from '../TileMap.jsx'
import CesiumView from './CesiumView.jsx'
import { api } from '../../api/client.js'
import { clusterMarkers, zoomForHeight } from '../../lib/clustering.js'
import { loadCesium } from '../../lib/cesiumLoader.js'
import { describeGeoError, getCurrentPosition } from '../../lib/geo.js'
import { useDebounced } from '../../hooks/useDebounced.js'

const CLUSTER_ABOVE = 12                          // fewer pins than this are always drawn individually
const BROWSER_KEY = (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_GOOGLE_MAPS_API_KEY) || ''
const newSession = () => `cb${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`

/**
 * One map for every role. 2D (the always-available OpenStreetMap view) or 3D (CesiumJS + Google Photorealistic 3D Tiles).
 * 3D is an enhancement: with no browser key, no WebGL, no network, or no 3D coverage the person simply keeps the 2D map and is told why.
 * It draws only the markers/lines it is given; what each role may see is decided by the server endpoints that produce them.
 *
 *   markers   [{ id, lat, lon, kind, label, stale?, noFit?, noCluster? }]     lines [{ id, points:[{lat,lon}], color? }]
 *   loading / error / onRetry            states for the data behind the map
 *   onSelect(marker)                     a pin (or group) was chosen; groups are handled here, not passed on
 *   focusRequest { lat, lon, key }       the page asks the camera to move (e.g. a row was chosen in a list); acts when `key` changes
 */
export default function LiveMap({ markers = [], lines = [], height = 460, selectedId, onSelect, loading = false, error = '', onRetry, ariaLabel = 'Map', allowSearch = true,
                                 focusRequest = null, cesiumLoader = loadCesium, apiKey = BROWSER_KEY, emptyText = 'Nothing to show on the map yet.' }) {
  const [mode, setMode] = useState('2d')
  const [layer, setLayer] = useState('satellite')
  const [notice, setNotice] = useState('')
  const [cesium, setCesium] = useState(null)
  const [busy3d, setBusy3d] = useState(false)
  const [tiles, setTiles] = useState('unknown')              // unknown | ok | no_key | unsupported | unavailable
  const [zoom2d, setZoom2d] = useState(12)
  const [height3d, setHeight3d] = useState(8000)
  const [expanded, setExpanded] = useState(null)             // a group the person opened (2D)
  const [focus, setFocus] = useState(null)
  const [located, setLocated] = useState(null)
  const [geoBusy, setGeoBusy] = useState(false)

  // ---- 3D availability
  const want3d = useCallback(async () => {
    setBusy3d(true); setNotice('')
    try { setCesium(await cesiumLoader()); setMode('3d') } catch (e) { setMode('2d'); setNotice(`${e.message} Showing the standard map instead.`) } finally { setBusy3d(false) }
  }, [cesiumLoader])
  const choose = (m) => { if (m === '3d') { if (cesium) setMode('3d'); else want3d() } else setMode('2d') }
  const tilesNote = { no_key: '3D buildings need a Google Maps key, which is not set up here. The 3D globe uses street imagery.', unsupported: 'This 3D library version cannot show 3D buildings. The 3D globe uses street imagery.',
                      unavailable: '3D buildings are not available here (no coverage, or the map service refused). The 3D globe uses street imagery.' }[tiles]

  // ---- pins to draw: the search/locate pins join the data; groups when there are many
  const extra = useMemo(() => (located ? [{ id: 'you-are-here', kind: 'me', lat: located.lat, lon: located.lon, label: 'You', noFit: true }] : []), [located])
  const all = useMemo(() => [...markers, ...extra], [markers, extra])
  const display = useMemo(() => {
    if (all.length <= CLUSTER_ABOVE) return all
    const z = mode === '3d' ? zoomForHeight(height3d) : zoom2d
    if (!expanded) return clusterMarkers(all, z)
    const open = new Set(expanded.members)
    return [...all.filter((m) => open.has(m.id)), ...clusterMarkers(all.filter((m) => !open.has(m.id)), z)]
  }, [all, mode, zoom2d, height3d, expanded])
  const select = useCallback((m) => {
    if (m.kind !== 'cluster') { onSelect?.(m); return }
    if (mode === '3d') setFocus({ lat: m.lat, lon: m.lon, key: `c-${m.id}`, height: 1500 }); else setExpanded(m)
  }, [mode, onSelect])
  const selectById = useCallback((id) => { const m = display.find((x) => String(x.id) === id); if (m) select(m) }, [display, select])

  useEffect(() => { if (focusRequest && Number.isFinite(focusRequest.lat) && Number.isFinite(focusRequest.lon)) setFocus(focusRequest) }, [focusRequest?.key]) // eslint-disable-line react-hooks/exhaustive-deps

  // ---- locate me
  const locate = async () => {
    setGeoBusy(true); setNotice('')
    try { const p = await getCurrentPosition({ highAccuracy: false }); setLocated({ lat: p.latitude, lon: p.longitude }); setFocus({ lat: p.latitude, lon: p.longitude, key: `me-${Date.now()}` }) }
    catch (e) { setNotice(describeGeoError(e)) } finally { setGeoBusy(false) }
  }

  // ---- address search (only when the server has it switched on)
  const [searchOn, setSearchOn] = useState(false)
  const [q, setQ] = useState('')
  const dq = useDebounced(q, 300)
  const [suggestions, setSuggestions] = useState([])
  const session = useRef(newSession())
  useEffect(() => { if (!allowSearch) return; let alive = true; api.mapsConfig().then((c) => alive && setSearchOn(Boolean(c?.geocoding))).catch(() => {}); return () => { alive = false } }, [allowSearch])
  useEffect(() => {
    if (!searchOn || dq.trim().length < 3) { setSuggestions([]); return undefined }
    let alive = true
    api.mapsAutocomplete(dq.trim(), { session: session.current, lat: located?.lat, lon: located?.lon })
      .then((r) => alive && setSuggestions(r?.suggestions || [])).catch((e) => { if (alive) { setSuggestions([]); setNotice(e.message) } })
    return () => { alive = false }
  }, [dq, searchOn]) // eslint-disable-line react-hooks/exhaustive-deps
  const pick = async (s) => {
    setSuggestions([]); setQ(s.main_text || s.text)
    try { const p = await api.mapsPlace(s.place_id, session.current); setLocated({ lat: p.latitude, lon: p.longitude }); setFocus({ lat: p.latitude, lon: p.longitude, key: `s-${s.place_id}` }); session.current = newSession() }
    catch (e) { setNotice(e.message) }
  }

  const lines2d = useMemo(() => lines.map((l) => ({ ...l, points: l.points })), [lines])
  const empty = !loading && !error && all.length === 0

  return (
    <div className="cblm" data-mode={mode}>
      <div className="cblm-bar">
        <div role="group" aria-label="Map view" className="cblm-seg">
          <button type="button" aria-pressed={mode === '2d'} onClick={() => choose('2d')}>2D</button>
          <button type="button" aria-pressed={mode === '3d'} onClick={() => choose('3d')} disabled={busy3d}>{busy3d ? 'Loading 3D…' : '3D'}</button>
        </div>
        {mode === '3d' && (
          <div role="group" aria-label="3D layer" className="cblm-seg">
            <button type="button" aria-pressed={layer === 'satellite'} onClick={() => setLayer('satellite')} disabled={tiles === 'no_key' || tiles === 'unsupported' || tiles === 'unavailable'}>Satellite</button>
            <button type="button" aria-pressed={layer === 'streets'} onClick={() => setLayer('streets')}>Streets</button>
          </div>
        )}
        <button type="button" className="cblm-btn" onClick={locate} disabled={geoBusy}>{geoBusy ? 'Finding you…' : 'Use my location'}</button>
        {searchOn && (
          <div className="cblm-search">
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search an address or area" aria-label="Search an address or area" autoComplete="off" />
            {suggestions.length > 0 && (
              <ul role="listbox" aria-label="Search suggestions">
                {suggestions.map((s) => <li key={s.place_id} role="option" aria-selected="false" tabIndex={0} onClick={() => pick(s)} onKeyDown={(e) => { if (e.key === 'Enter') pick(s) }}><strong>{s.main_text || s.text}</strong> <span>{s.secondary_text}</span></li>)}
              </ul>
            )}
          </div>
        )}
        {expanded && mode === '2d' && <button type="button" className="cblm-btn" onClick={() => setExpanded(null)}>Group pins again</button>}
      </div>

      {notice && <p className="cblm-note" role="status">{notice}</p>}
      {mode === '3d' && tilesNote && <p className="cblm-note" role="status">{tilesNote}</p>}

      <div className="cblm-stage" style={{ minHeight: height }}>
        {loading && <div className="cblm-skeleton" role="status" aria-live="polite" style={{ height }}>Loading map…</div>}
        {!loading && error && (
          <div className="cblm-error" role="alert" style={{ height }}>
            <p>{error}</p>{onRetry && <button type="button" className="cblm-btn" onClick={onRetry}>Try again</button>}
          </div>
        )}
        {!loading && !error && mode === '2d' && (
          <TileMap markers={display} lines={lines2d} height={height} ariaLabel={ariaLabel} onSelect={select} selectedId={selectedId} labels={display.length > 12 ? 'selected' : 'all'} focus={focus} onZoomChange={setZoom2d} />
        )}
        {!loading && !error && mode === '3d' && cesium && (
          <CesiumView cesium={cesium} markers={display} lines={lines} layer={layer} apiKey={apiKey} focus={focus} selectedId={selectedId} height={height} ariaLabel={ariaLabel}
            onSelect={selectById} onHeightChange={setHeight3d}
            onTilesUnavailable={(why) => { setTiles(why); setLayer('streets') }}
            onError={(msg) => { setMode('2d'); setCesium(null); setNotice(`${msg} Showing the standard map instead.`) }} />
        )}
        {empty && mode === '3d' && <p className="cblm-note">{emptyText}</p>}
      </div>
    </div>
  )
}

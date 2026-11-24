import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import '../map.css'
import { TILE, centerOf, fitZoom, metresPerPixel, project, ringExtent, tileUrl, unproject, visibleTiles } from '../lib/mapMath.js'

// OpenStreetMap's public tile server is fine for light use; for a busy production site point VITE_TILE_URL at a tile
// provider you have an account with (the URL needs {z}, {x} and {y}). The attribution below is required either way.
const DEFAULT_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TEMPLATE = (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_TILE_URL) || DEFAULT_TILES

/**
 * A small slippy map. markers = [{ id, lat, lon, label, kind, stale?, accuracy? }]. `kind` only picks the pin colour (see map.css).
 * It only draws what it is given: no simulated movement, no placeholder positions.
 *   rings      = [{ id, lat, lon, radiusKm }]   circles (a search radius); the map zooms out to fit them
 *   onSelect   = (marker) => void               makes pins clickable / keyboard-selectable; selectedId highlights one
 *   labels     = 'all' | 'selected'             with many pins, show a name only for the selected one (hover still shows it)
 *   focus      = { lat, lon, key }              re-centres on a point whenever `key` changes
 *   lines      = [{ id, points:[{lat,lon}], color?, width? }]   road routes etc. drawn under the pins
 *   onZoomChange = (zoom) => void               lets a page group nearby pins (see lib/clustering.js) as the person zooms
 */
export default function TileMap({ markers, height = 320, ariaLabel = 'Map', template = TEMPLATE, rings = [], onSelect, selectedId, labels = 'all', focus, lines = [], onZoomChange }) {
  const box = useRef(null)
  const [size, setSize] = useState({ w: 600, h: height })
  const [shift, setShift] = useState({ dx: 0, dy: 0, dz: 0 })     // what the person changed by dragging or zooming
  const [loaded, setLoaded] = useState(0)
  const [failed, setFailed] = useState(0)
  const drag = useRef(null)

  useEffect(() => {
    if (!box.current || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.max(200, Math.round(e.contentRect.width)), h: height }))
    ro.observe(box.current); return () => ro.disconnect()
  }, [height])

  const pts = useMemo(() => markers.filter((m) => Number.isFinite(m.lat) && Number.isFinite(m.lon)), [markers])
  const fitBase = useMemo(() => { const still = pts.filter((p) => !p.noFit); return still.length ? still : pts }, [pts])   // `noFit` pins (moving ones) never re-zoom the map
  const key = fitBase.map((p) => `${p.id}:${p.lat.toFixed(5)},${p.lon.toFixed(5)}`).join('|')
  const ringKey = rings.map((r) => `${r.id}:${r.lat},${r.lon},${r.radiusKm}`).join('|')
  const fitPts = useMemo(() => fitBase.concat(rings.flatMap((r) => ringExtent(r.lat, r.lon, r.radiusKm))), [key, ringKey])   // eslint-disable-line react-hooks/exhaustive-deps
  const fitKey = `${key}#${ringKey}`
  const baseZoom = useMemo(() => fitZoom(fitPts, size.w, size.h), [fitKey, size.w, size.h])        // eslint-disable-line react-hooks/exhaustive-deps
  const zoom = Math.max(2, Math.min(18, baseZoom + shift.dz))
  const c = useMemo(() => (fitPts.length ? centerOf(fitPts, zoom) : { lat: 20.5937, lon: 78.9629 }), [fitKey, zoom])   // eslint-disable-line react-hooks/exhaustive-deps
  const centerPx = useMemo(() => { const p = project(c.lat, c.lon, zoom); return { x: p.x - shift.dx, y: p.y - shift.dy } }, [c, zoom, shift.dx, shift.dy])
  const tiles = useMemo(() => visibleTiles(centerPx, zoom, size.w, size.h), [centerPx, zoom, size.w, size.h])
  useEffect(() => { setLoaded(0); setFailed(0) }, [template])
  const left = centerPx.x - size.w / 2; const top = centerPx.y - size.h / 2
  useEffect(() => { onZoomChange?.(zoom) }, [zoom])   // eslint-disable-line react-hooks/exhaustive-deps

  const focusKey = focus ? focus.key : null
  useEffect(() => {          // move the view onto a point the page asked for (e.g. a row clicked in a list)
    if (!focus || !Number.isFinite(focus.lat) || !Number.isFinite(focus.lon)) return
    const target = project(focus.lat, focus.lon, zoom); const base = project(c.lat, c.lon, zoom)
    setShift((s) => ({ ...s, dx: base.x - target.x, dy: base.y - target.y }))
  }, [focusKey])   // eslint-disable-line react-hooks/exhaustive-deps
  const down = (e) => { drag.current = { x: e.clientX, y: e.clientY }; e.currentTarget.setPointerCapture?.(e.pointerId) }
  const move = (e) => { if (!drag.current) return; const dx = e.clientX - drag.current.x; const dy = e.clientY - drag.current.y; drag.current = { x: e.clientX, y: e.clientY }; setShift((s) => ({ ...s, dx: s.dx + dx, dy: s.dy + dy })) }
  const up = () => { drag.current = null }
  const zoomBy = useCallback((d) => setShift((s) => ({ dx: 0, dy: 0, dz: s.dz + d })), [])
  const recenter = () => setShift({ dx: 0, dy: 0, dz: 0 })
  const key2 = (e) => { if (e.key === '+' || e.key === '=') zoomBy(1); else if (e.key === '-') zoomBy(-1); else if (e.key === '0') recenter(); else if (e.key.startsWith('Arrow')) { e.preventDefault(); const s = 60; setShift((v) => ({ ...v, dx: v.dx - (e.key === 'ArrowRight' ? s : e.key === 'ArrowLeft' ? -s : 0), dy: v.dy - (e.key === 'ArrowDown' ? s : e.key === 'ArrowUp' ? -s : 0) })) } }

  const broken = failed >= 3 && loaded === 0
  return (
    <div ref={box} className="cbmap" style={{ height }} role="application" aria-label={`${ariaLabel}. Use plus and minus to zoom, arrow keys to move, zero to re-centre.`} tabIndex={0} onKeyDown={key2}>
      <div className="cbmap-layer" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
        {tiles.map((t) => <img key={t.key} className="cbmap-tile" alt="" width={TILE} height={TILE} draggable={false} src={tileUrl(template, t)} style={{ left: t.left, top: t.top }} onLoad={() => setLoaded((n) => n + 1)} onError={() => setFailed((n) => n + 1)} />)}
        {lines.length > 0 && (
          <svg className="cbmap-lines" width={size.w} height={size.h} aria-hidden="true" focusable="false">
            {lines.map((l) => (
              <polyline key={l.id} fill="none" stroke={l.color || '#2563eb'} strokeWidth={l.width || 5} strokeLinejoin="round" strokeLinecap="round" opacity="0.85"
                points={(l.points || []).filter((q) => Number.isFinite(q.lat) && Number.isFinite(q.lon)).map((q) => { const p = project(q.lat, q.lon, zoom); return `${(p.x - left).toFixed(1)},${(p.y - top).toFixed(1)}` }).join(' ')} />
            ))}
          </svg>
        )}
        {rings.map((r) => {
          const p = project(r.lat, r.lon, zoom); const px = (r.radiusKm * 1000) / metresPerPixel(r.lat, zoom)
          return <div key={`ring-${r.id}`} className="cbmap-ring" style={{ left: p.x - left, top: p.y - top, width: px * 2, height: px * 2 }} aria-hidden="true" />
        })}
        {pts.map((m) => {
          const p = project(m.lat, m.lon, zoom); const x = p.x - left; const y = p.y - top
          const metres = m.accuracy && m.accuracy > 15 ? m.accuracy / (156543.03 * Math.cos((m.lat * Math.PI) / 180) / 2 ** zoom) : 0
          return (
            <React.Fragment key={m.id}>
              {metres > 6 && <div className="cbmap-accuracy" style={{ left: x, top: y, width: metres * 2, height: metres * 2 }} />}
              <div className={`cbmap-marker ${String(m.kind).split(' ').map((k) => `cbmap-marker--${k}`).join(' ')}${m.stale ? ' cbmap-marker--stale' : ''}${onSelect ? ' cbmap-marker--clickable' : ''}${selectedId === m.id ? ' cbmap-marker--selected' : ''}${labels === 'selected' && selectedId !== m.id ? ' cbmap-marker--nolabel' : ''}`}
                style={{ left: x, top: y }} title={m.label} data-marker={m.id}
                {...(onSelect ? {
                  role: 'button', tabIndex: 0, 'aria-label': `${m.label}${m.stale ? ' (last known)' : ''}`, 'aria-pressed': selectedId === m.id,
                  onPointerDown: (e) => e.stopPropagation(),            // a click on a pin selects it; it must not start a drag
                  onClick: () => onSelect(m),
                  onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onSelect(m) } }
                } : {})}>
                <span className="cbmap-pin">{m.count || null}</span><span className="cbmap-label">{m.label}{m.stale ? ' (last known)' : ''}</span>
              </div>
            </React.Fragment>
          )
        })}
      </div>
      <div className="cbmap-controls">
        <button type="button" onClick={() => zoomBy(1)} aria-label="Zoom in">+</button>
        <button type="button" onClick={() => zoomBy(-1)} aria-label="Zoom out">−</button>
        <button type="button" onClick={recenter} aria-label="Re-centre the map" style={{ fontSize: 13 }}>⌖</button>
      </div>
      {broken && <div className="cbmap-note" role="alert">The map pictures could not be loaded. Check your connection, or ask your administrator about the map provider setting. Your positions and links still work.</div>}
      {!pts.length && !broken && <div className="cbmap-note">Nothing to show on the map yet.</div>}
      <div className="cbmap-attrib">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors</div>
    </div>
  )
}

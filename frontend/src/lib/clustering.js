// Groups nearby pins into one numbered pin so a large map stays readable. Pure; works in screen pixels at the given zoom.
import { project, unproject } from './mapMath.js'

// These are never grouped: the person's own position, and a live volunteer position, must always stay individually visible.
export const NEVER_CLUSTER = new Set(['me', 'live', 'volunteer', 'route-start', 'route-end'])

/**
 * @param {Array<{id,lat,lon,kind,label}>} markers
 * @param {number} zoom        slippy-map zoom level
 * @param {{cellPx?:number, minSize?:number}} opts  cellPx: pins closer than this (roughly) are grouped
 * @returns markers with groups replaced by { id:'cluster-…', kind:'cluster', count, lat, lon, label, members:[ids] }
 */
export function clusterMarkers(markers, zoom, { cellPx = 56, minSize = 2 } = {}) {
  const cells = new Map()
  const fixed = []
  for (const m of markers) {
    if (!Number.isFinite(m.lat) || !Number.isFinite(m.lon)) continue
    if (NEVER_CLUSTER.has(String(m.kind)) || m.noCluster) { fixed.push(m); continue }
    const p = project(m.lat, m.lon, zoom)
    const key = `${Math.floor(p.x / cellPx)}:${Math.floor(p.y / cellPx)}`
    if (!cells.has(key)) cells.set(key, [])
    cells.get(key).push(m)
  }
  const out = [...fixed]
  for (const [key, group] of cells) {
    if (group.length < minSize) { out.push(...group); continue }
    const sum = group.reduce((a, m) => { const p = project(m.lat, m.lon, zoom); return { x: a.x + p.x, y: a.y + p.y } }, { x: 0, y: 0 })
    const c = unproject(sum.x / group.length, sum.y / group.length, zoom)
    out.push({ id: `cluster-${zoom}-${key}`, kind: 'cluster', count: group.length, lat: c.lat, lon: c.lon,
               label: `${group.length} places`, members: group.map((m) => m.id) })
  }
  return out
}

/** Roughly the zoom at which a camera `heightMetres` above the ground sees a city-sized area (for the 3D view). */
export function zoomForHeight(heightMetres) {
  if (!Number.isFinite(heightMetres) || heightMetres <= 0) return 14
  return Math.max(3, Math.min(18, Math.round(Math.log2(40_000_000 / heightMetres))))
}

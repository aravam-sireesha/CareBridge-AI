// Pure map helpers for the dependency-free tile map and for navigation. No DOM, no network.
export const TILE = 256
const MAX_LAT = 85.0511
const clampLat = (lat) => Math.max(-MAX_LAT, Math.min(MAX_LAT, lat))
const rad = (d) => (d * Math.PI) / 180

/** Web-Mercator position in "world pixels" at an integer zoom (the standard slippy-map scheme used by OpenStreetMap tiles). */
export function project(lat, lon, zoom) {
  const n = TILE * 2 ** zoom
  const s = Math.sin(rad(clampLat(lat)))
  return { x: ((lon + 180) / 360) * n, y: (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n }
}
export function unproject(x, y, zoom) {
  const n = TILE * 2 ** zoom
  const lon = (x / n) * 360 - 180
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI
  return { lat, lon }
}

/** Highest zoom at which every point fits inside width x height (minus padding). One point (or none) gets a street-level zoom. */
export function fitZoom(points, width, height, { pad = 48, minZoom = 3, maxZoom = 16 } = {}) {
  if (!points.length) return 4
  for (let z = maxZoom; z >= minZoom; z--) {
    const ps = points.map((p) => project(p.lat, p.lon, z))
    const xs = ps.map((p) => p.x); const ys = ps.map((p) => p.y)
    if (Math.max(...xs) - Math.min(...xs) <= width - 2 * pad && Math.max(...ys) - Math.min(...ys) <= height - 2 * pad) return Math.min(z, points.length === 1 ? 15 : maxZoom)
  }
  return minZoom
}
/** Centre of the bounding box of the points, as latitude/longitude. */
export function centerOf(points, zoom) {
  const ps = points.map((p) => project(p.lat, p.lon, zoom))
  const xs = ps.map((p) => p.x); const ys = ps.map((p) => p.y)
  return unproject((Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2, zoom)
}

/** The tiles needed to fill a viewport, with pixel offsets. `center` is {x, y} in world pixels. Tiles above/below the world are skipped; x wraps. */
export function visibleTiles(center, zoom, width, height) {
  const n = 2 ** zoom; const left = center.x - width / 2; const top = center.y - height / 2
  const out = []
  for (let ty = Math.floor(top / TILE); ty <= Math.floor((top + height) / TILE); ty++) {
    if (ty < 0 || ty >= n) continue
    for (let tx = Math.floor(left / TILE); tx <= Math.floor((left + width) / TILE); tx++) {
      const wx = ((tx % n) + n) % n
      out.push({ key: `${zoom}/${wx}/${ty}@${tx}`, x: wx, y: ty, z: zoom, left: Math.round(tx * TILE - left), top: Math.round(ty * TILE - top) })
    }
  }
  return out
}
export const tileUrl = (template, t) => template.replace('{z}', t.z).replace('{x}', t.x).replace('{y}', t.y)

export function haversineKm(lat1, lon1, lat2, lon2) {
  const a = Math.sin(rad(lat2 - lat1) / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lon2 - lon1) / 2) ** 2
  return 2 * 6371.0088 * Math.asin(Math.min(1, Math.sqrt(a)))
}
/** "Straight-line" distance in words: metres under 1 km (to the nearest 10), one decimal under 10 km, whole km beyond. */
export function formatDistance(km) {
  if (!Number.isFinite(km)) return ''
  if (km < 1) return `${Math.max(10, Math.round((km * 1000) / 10) * 10)} m`
  return km < 10 ? `${km.toFixed(1)} km` : `${Math.round(km)} km`
}
const POINTS = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west']
export function bearingLabel(lat1, lon1, lat2, lon2) {
  const y = Math.sin(rad(lon2 - lon1)) * Math.cos(rad(lat2))
  const x = Math.cos(rad(lat1)) * Math.sin(rad(lat2)) - Math.sin(rad(lat1)) * Math.cos(rad(lat2)) * Math.cos(rad(lon2 - lon1))
  const deg = ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360
  return POINTS[Math.round(deg / 45) % 8]
}

/** Links that hand the destination to a real navigation app. We never calculate road routes ourselves. */
export function navLinks(lat, lon, label = 'Destination') {
  const ll = `${Number(lat).toFixed(6)},${Number(lon).toFixed(6)}`
  return {
    google: `https://www.google.com/maps/dir/?api=1&destination=${ll}&travelmode=driving`,
    geo: `geo:${ll}?q=${ll}(${encodeURIComponent(label)})`,
    osm: `https://www.openstreetmap.org/?mlat=${Number(lat).toFixed(6)}&mlon=${Number(lon).toFixed(6)}#map=16/${Number(lat).toFixed(5)}/${Number(lon).toFixed(5)}`
  }
}

export function ageText(seconds) {
  if (seconds == null) return 'unknown'
  if (seconds < 10) return 'just now'
  if (seconds < 90) return `${Math.round(seconds)} s ago`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`
  return `${Math.round(seconds / 3600)} h ago`
}

/** Metres covered by one screen pixel at a latitude and zoom (standard Web-Mercator scale). */
export const metresPerPixel = (lat, zoom) => (156543.03392 * Math.cos(rad(clampLat(lat)))) / 2 ** zoom

/** The north, south, east and west edge points of a circle, so a map can fit a search ring on screen. */
export function ringExtent(lat, lon, radiusKm) {
  const dLat = radiusKm / 111.32
  const dLon = radiusKm / (111.32 * Math.max(0.01, Math.cos(rad(clampLat(lat)))))
  return [
    { lat: clampLat(lat + dLat), lon }, { lat: clampLat(lat - dLat), lon },
    { lat, lon: lon + dLon }, { lat, lon: lon - dLon }
  ]
}

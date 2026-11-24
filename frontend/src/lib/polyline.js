// Decodes a Google "encoded polyline" (precision 5), the route line returned by /maps/route, into [{lat, lon}].
// Defensive on purpose: the string comes from a network response, so a truncated or hostile value must never hang or throw.
export function decodePolyline(encoded, { maxPoints = 20000 } = {}) {
  if (typeof encoded !== 'string' || !encoded) return []
  const out = []
  let index = 0, lat = 0, lon = 0
  const readValue = () => {
    let result = 0, shift = 0, byte
    do {
      if (index >= encoded.length) return null              // truncated
      byte = encoded.charCodeAt(index++) - 63
      if (byte < 0 || byte > 63) return null                // not a polyline character
      result |= (byte & 0x1f) << shift
      shift += 5
      if (shift > 35) return null                           // absurdly long number
    } while (byte >= 0x20)
    return result & 1 ? ~(result >> 1) : result >> 1
  }
  while (index < encoded.length && out.length < maxPoints) {
    const dLat = readValue(); if (dLat === null) break
    const dLon = readValue(); if (dLon === null) break
    lat += dLat; lon += dLon
    const p = { lat: lat / 1e5, lon: lon / 1e5 }
    if (Math.abs(p.lat) > 90 || Math.abs(p.lon) > 180) break
    out.push(p)
  }
  return out
}

/** "21 min" / "1 h 5 min" for a duration in seconds. */
export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return ''
  const m = Math.max(1, Math.round(seconds / 60))
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}`
}

/** Road distance in metres -> "11.3 km" / "850 m". */
export function formatRoadDistance(metres) {
  if (!Number.isFinite(metres) || metres < 0) return ''
  return metres < 1000 ? `${Math.round(metres / 10) * 10} m` : `${(metres / 1000).toFixed(metres < 10000 ? 1 : 0)} km`
}

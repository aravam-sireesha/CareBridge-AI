// Browser location helpers. Deliberately small:
//  * One reading, only when the person presses a button (getCurrentPosition). We never call watchPosition,
//    so nothing here can track anyone continuously or in the background.
//  * Nothing is sent to the server until the person reviews the numbers and presses Save.

export const ROUGH_ACCURACY_M = 5000 // a reading this vague (e.g. from an IP address) deserves a warning

/** Can this browser give us a position, and if not, why (so the screen can explain instead of failing silently). */
export function geolocationSupport() {
  if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
    return { available: false, reason: 'This browser cannot share its location. You can type the coordinates instead.' }
  }
  if (typeof window !== 'undefined' && window.isSecureContext === false) {
    return { available: false, reason: 'Browsers only share location on secure (https) pages or on localhost. You can type the coordinates instead.' }
  }
  return { available: true, reason: '' }
}

/** Turn a GeolocationPositionError (or anything else) into one clear sentence. */
export function describeGeoError(err) {
  switch (err && err.code) {
    case 1: return 'Location permission was blocked. Allow it for this site in your browser settings, or type the coordinates instead.'
    case 2: return 'Your device could not work out its position. Try again, or type the coordinates instead.'
    case 3: return 'Finding your position took too long. Try again, or type the coordinates instead.'
    default: return (err && err.message) || 'Could not read your location. You can type the coordinates instead.'
  }
}

/** Ask the browser once. Resolves { latitude, longitude, accuracy } (accuracy in metres) or rejects with the browser's error. */
export function getCurrentPosition({ timeout = 15000, maximumAge = 60000, highAccuracy = false } = {}) {
  return new Promise((resolve, reject) => {
    const support = geolocationSupport()
    if (!support.available) {
      reject(Object.assign(new Error(support.reason), { code: 0 }))
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy }),
      (err) => reject(err),
      { enableHighAccuracy: highAccuracy, timeout, maximumAge }
    )
  })
}

/** Same rules as the server: a real latitude/longitude, and (0, 0) counts as "no data". */
export function isValidCoordinate(lat, lon) {
  if (typeof lat === 'boolean' || typeof lon === 'boolean') return false
  const la = typeof lat === 'string' ? Number(lat.trim()) : lat
  const lo = typeof lon === 'string' ? Number(lon.trim()) : lon
  if (typeof la !== 'number' || typeof lo !== 'number' || !Number.isFinite(la) || !Number.isFinite(lo)) return false
  if (typeof lat === 'string' && lat.trim() === '') return false
  if (typeof lon === 'string' && lon.trim() === '') return false
  if (la < -90 || la > 90 || lo < -180 || lo > 180) return false
  return !(la === 0 && lo === 0)
}

/** Check the two text boxes. Returns { ok, latitude, longitude, errors: { latitude?, longitude? } }. */
export function parseCoordinates(latText, lonText) {
  const errors = {}
  const num = (t) => (String(t ?? '').trim() === '' ? NaN : Number(String(t).trim()))
  const lat = num(latText)
  const lon = num(lonText)
  if (!Number.isFinite(lat)) errors.latitude = 'Enter a number, for example 17.385'
  else if (lat < -90 || lat > 90) errors.latitude = 'Latitude must be between -90 and 90'
  if (!Number.isFinite(lon)) errors.longitude = 'Enter a number, for example 78.4867'
  else if (lon < -180 || lon > 180) errors.longitude = 'Longitude must be between -180 and 180'
  if (!errors.latitude && !errors.longitude && lat === 0 && lon === 0) errors.latitude = '0, 0 is treated as "no data". Enter your real position.'
  return { ok: Object.keys(errors).length === 0, latitude: lat, longitude: lon, errors }
}

/** Optional radius for volunteers. Empty is allowed (no limit). */
export function parseRadius(text, max = 500) {
  const t = String(text ?? '').trim()
  if (t === '') return { ok: true, value: null }
  const n = Number(t)
  if (!Number.isFinite(n) || n <= 0) return { ok: false, error: 'Enter a number above 0, or leave it empty' }
  if (n > max) return { ok: false, error: `The largest allowed range is ${max} km` }
  return { ok: true, value: n }
}

/** Short, honest description of a reading's quality. */
export function describeAccuracy(accuracyM) {
  if (!Number.isFinite(accuracyM)) return ''
  if (accuracyM >= 1000) return `accurate to about ${Math.round(accuracyM / 1000)} km`
  return `accurate to about ${Math.max(1, Math.round(accuracyM))} m`
}

export const isRoughReading = (accuracyM) => Number.isFinite(accuracyM) && accuracyM > ROUGH_ACCURACY_M

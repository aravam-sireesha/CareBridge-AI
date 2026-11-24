// Loads CesiumJS on demand from Cesium's CDN, so the ~4 MB library is only fetched when someone opens the 3D view, and the rest of
// the app does not depend on it. If anything fails (offline, blocked, no WebGL) the caller shows the 2D map instead.
export const CESIUM_VERSION = (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_CESIUM_VERSION) || '1.121'
const VERSION_OK = /^\d{1,2}\.\d{1,3}(\.\d{1,2})?$/
const BASE = (v) => `https://cesium.com/downloads/cesiumjs/releases/${v}/Build/Cesium`

let pending = null

export function webglAvailable(doc = typeof document !== 'undefined' ? document : null) {
  try {
    const canvas = doc.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch { return false }
}

/** Resolves with the global `Cesium` object, or rejects with an Error whose message is safe to show. */
export function loadCesium({ version = CESIUM_VERSION, doc = typeof document !== 'undefined' ? document : null, win = typeof window !== 'undefined' ? window : null } = {}) {
  if (win?.Cesium) return Promise.resolve(win.Cesium)
  if (pending) return pending
  if (!doc || !win) return Promise.reject(new Error('3D view is not available here.'))
  if (!VERSION_OK.test(String(version))) return Promise.reject(new Error('The 3D map version setting is not valid.'))
  if (!webglAvailable(doc)) return Promise.reject(new Error('This device or browser does not support the 3D map (WebGL).'))
  win.CESIUM_BASE_URL = BASE(version)
  pending = new Promise((resolve, reject) => {
    const css = doc.createElement('link')
    css.rel = 'stylesheet'; css.href = `${BASE(version)}/Widgets/widgets.css`; css.crossOrigin = 'anonymous'
    doc.head.appendChild(css)
    const script = doc.createElement('script')
    script.src = `${BASE(version)}/Cesium.js`; script.async = true; script.crossOrigin = 'anonymous'
    script.onload = () => (win.Cesium ? resolve(win.Cesium) : reject(new Error('The 3D map library loaded but is not usable.')))
    script.onerror = () => { pending = null; script.remove(); css.remove(); reject(new Error('The 3D map library could not be downloaded. Check your connection.')) }
    doc.head.appendChild(script)
  })
  return pending
}

export function resetCesiumLoaderForTests() { pending = null }

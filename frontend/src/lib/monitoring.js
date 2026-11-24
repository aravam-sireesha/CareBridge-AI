// Browser error monitoring (Sentry), only when VITE_SENTRY_DSN is set, and scrubbed the same way as the server: no credentials, personal
// details, children's information or coordinates may leave the browser in an error report. If scrubbing fails the event is dropped.
const SENSITIVE_KEYS = /pass(word|wd)?|secret|token|otp|authorization|cookie|api[-_]?key|private|signature|session|phone|mobile|email|address|street|lat(itude)?|lng|lon(gitude)?|coord|location|position|geo|gps|heading|speed|accuracy|child|children|guardian|beneficiar|dob|birth|aadhaar|aadhar/i
const PATTERNS = [
  [/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, '[email]'],
  [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*/g, '[jwt]'],
  [/\bbearer\s+[A-Za-z0-9._~+/=-]{8,}/gi, 'Bearer [token]'],
  [/(?<![\d.])[-+]?\d{1,3}\.\d{4,}\s*[,;/ ]\s*[-+]?\d{1,3}\.\d{4,}(?!\d)/g, '[coordinates]'],
  [/(?<!\w)\+?\d[\d\s\-().]{8,}\d(?!\w)/g, '[number]'],
]
export const REDACTED = '[Filtered]'

export const scrubString = (s) => PATTERNS.reduce((acc, [re, to]) => acc.replace(re, to), s)

export function scrub(value, depth = 0) {
  if (depth > 12) return REDACTED
  if (Array.isArray(value)) return value.map((v) => scrub(v, depth + 1))
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, SENSITIVE_KEYS.test(k) ? REDACTED : scrub(v, depth + 1)]))
  return typeof value === 'string' ? scrubString(value) : value
}

export function beforeSend(event) {
  try {
    const clean = scrub(event)
    clean.user = event.user?.id != null ? { id: String(event.user.id) } : {}
    if (clean.request) { delete clean.request.data; delete clean.request.cookies; delete clean.request.query_string; clean.request.headers = {} }
    return clean
  } catch { return null }                                       // never send an event that could not be scrubbed
}

export function beforeBreadcrumb(crumb) {
  try {
    if (crumb.category === 'fetch' || crumb.category === 'xhr') { const { url, ...rest } = crumb.data || {}; return scrub({ ...crumb, data: rest }) }   // request URLs can carry ids and keys
    return scrub(crumb)
  } catch { return null }
}

export async function initMonitoring({ dsn = import.meta.env?.VITE_SENTRY_DSN, environment = import.meta.env?.VITE_SENTRY_ENVIRONMENT || 'production', importer = () => import('@sentry/browser') } = {}) {
  if (!dsn) return false
  try {
    const Sentry = await importer()
    Sentry.init({ dsn, environment, sendDefaultPii: false, tracesSampleRate: 0, beforeSend, beforeBreadcrumb })
    return true
  } catch (e) { console.warn('Error monitoring could not start', e?.message || e); return false }          // the app must still work
}

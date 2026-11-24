// Pure helpers for the volunteer availability editor. The server validates everything again (services/availability.py).
export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
export const SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
export const MODE_LABEL = { walking: 'On foot', bicycle: 'Bicycle', motorbike: 'Motorbike or scooter', car: 'Car', van: 'Van or pick-up truck' }
export const TIMEZONES = ['Asia/Kolkata', 'UTC', 'Asia/Dubai', 'Asia/Singapore', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Los_Angeles', 'Australia/Sydney']
export const MAX_SLOTS = 28
export const emptySlot = (weekday = 0) => ({ weekday, start: '09:00', end: '17:00' })

const minutes = (t) => { const m = /^(\d{1,2}):(\d{2})$/.exec(String(t || '').trim()); return m && +m[1] < 24 && +m[2] < 60 ? +m[1] * 60 + +m[2] : null }

/** Instant feedback. Returns an array of messages (empty = fine), one per problem, naming the slot. */
export function slotProblems(slots) {
  const out = []
  if (slots.length > MAX_SLOTS) out.push(`Please keep it to ${MAX_SLOTS} time slots or fewer.`)
  slots.forEach((s, i) => {
    const a = minutes(s.start); const b = minutes(s.end); const label = `Slot ${i + 1} (${WEEKDAYS[s.weekday] || '?'})`
    if (a == null || b == null) out.push(`${label}: enter both times.`)
    else if (b <= a) out.push(`${label}: the end must be after the start. For a night shift, add two slots.`)
    else if (b - a < 15) out.push(`${label}: a slot must be at least 15 minutes long.`)
  })
  const byDay = {}
  slots.forEach((s) => { const a = minutes(s.start); const b = minutes(s.end); if (a != null && b != null && b > a) (byDay[s.weekday] ||= []).push([a, b]) })
  for (const [d, list] of Object.entries(byDay)) { list.sort((x, y) => x[0] - y[0]); for (let i = 1; i < list.length; i++) if (list[i][0] < list[i - 1][1]) { out.push(`${WEEKDAYS[d]}: two of your slots overlap.`); break } }
  return out
}

/** "Mon 09:00-17:00, Sat 10:00-14:00" */
export function summarize(slots) {
  if (!slots?.length) return 'No schedule saved'
  return [...slots].sort((a, b) => a.weekday - b.weekday || a.start.localeCompare(b.start)).map((s) => `${SHORT[s.weekday]} ${s.start}-${s.end}`).join(', ')
}

/** Capacity text to a number or an error. Empty is allowed (not stated). */
export function parseCapacity(text) {
  const t = String(text ?? '').trim()
  if (t === '') return { ok: true, value: null }
  const n = Number(t)
  if (!Number.isFinite(n) || n <= 0) return { ok: false, error: 'Enter a number of kilograms above 0, or leave it empty.' }
  if (n > 5000) return { ok: false, error: 'The largest allowed value is 5000 kg.' }
  return { ok: true, value: n }
}

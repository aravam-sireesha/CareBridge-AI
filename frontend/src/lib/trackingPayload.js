// What the volunteer's device sends to the server, and how the server's answers are understood. Pure, so it is unit-tested.

// Sequence numbers must only ever increase for a session, including after a page reload or from a second device. Seconds
// since a fixed date satisfy that without remembering anything; a fix is sent at most every 5 s, so two never collide.
export const SEQ_EPOCH_MS = 1_700_000_000_000

export function createSeq(now = () => Date.now()) {
  let last = -1
  return () => { last = Math.max(last + 1, Math.floor((now() - SEQ_EPOCH_MS) / 1000)); return last }
}

const finite = (v) => typeof v === 'number' && Number.isFinite(v)

/** Browser GeolocationPosition -> request body. Optional fields are left out (never sent as null/NaN) when the device has none. */
export function buildFix(pos, { sessionId = null, seq } = {}) {
  const c = pos.coords
  const out = { latitude: c.latitude, longitude: c.longitude }
  if (finite(c.accuracy) && c.accuracy >= 0) out.accuracy_m = c.accuracy
  if (finite(c.heading) && c.heading >= 0 && c.heading <= 360) out.heading = c.heading          // null/NaN while standing still
  if (finite(c.speed) && c.speed >= 0 && c.speed <= 120) out.speed = c.speed
  if (finite(pos.timestamp) && pos.timestamp > 0) out.timestamp = pos.timestamp
  if (seq != null) out.seq = seq
  if (sessionId) out.tracking_session_id = sessionId
  return out
}

/** Decide what a rejected position means, from the server's message. */
export function classifyTrackingError(message = '') {
  if (/Start sharing first|switched off|session has ended|time limit/i.test(message)) return 'ended'
  if (/paused/i.test(message)) return 'paused'
  if (/every few seconds|Too many position updates|slow down/i.test(message)) return 'slow'
  if (/out of date|old reading|clock looks wrong|dated in the future/i.test(message)) return 'bad_time'
  return 'other'
}

export const STALE_AFTER_SECONDS = 120

/** A live position older than this is shown as "last known", even if the last server message said it was fresh. */
export function isStale(ageSeconds, serverSaysStale = false) {
  return Boolean(serverSaysStale) || ageSeconds == null || ageSeconds > STALE_AFTER_SECONDS
}

/** Turn a live `delivery.location` event into the same shape the HTTP endpoint returns. */
export function remoteFromEvent(data, now = Date.now()) {
  return { sharing: true, has_position: true, latitude: data.latitude, longitude: data.longitude, accuracy_m: data.accuracy_m ?? null,
           age_seconds: 0, stale: false, recorded_at: data.recorded_at, fetchedAt: now }
}

/** Apply a `delivery.tracking` event ({state}) to what the viewer currently shows. */
export function applyTrackingState(remote, state) {
  if (state === 'paused') return { sharing: true, paused: true, has_position: false }
  if (state === 'stopped') return { sharing: false, has_position: false }
  if (state === 'started' || state === 'resumed') return { ...(remote || {}), sharing: true, paused: false }
  return remote
}

// Pure logic behind the live map page: which deliveries to show, the pins for them, risk flags, live-position bookkeeping, ETA wording.
import { decodePolyline, formatDuration, formatRoadDistance } from './polyline.js'
import { isStale } from './trackingPayload.js'

export const IN_MOTION = ['accepted', 'pickup_scheduled', 'picked_up', 'in_transit', 'delivered']   // a volunteer holds the task (mirrors the backend)
export const LIVE_STATUSES = ['picked_up', 'in_transit']                                             // the stages in which a live position may be shown to others
export const DELAYED_AFTER_HOURS = 6                      // in transit for longer than this is flagged
export const UNCONFIRMED_AFTER_HOURS = 24                 // delivered but the organization has not confirmed receipt
const HOUR = 3600_000

export const inMotion = (d) => IN_MOTION.includes(d.status)

export function filterDeliveries(list, { status = 'all', category = 'all', days = 0 } = {}, now = Date.now()) {
  const since = days > 0 ? now - days * 24 * HOUR : null
  return (list || []).filter((d) => {
    if (status === 'active' ? !inMotion(d) : status !== 'all' && d.status !== status) return false
    if (category !== 'all' && (d.need?.category || '') !== category) return false
    if (since != null) { const t = Date.parse(d.created_at || d.updated_at || ''); if (!Number.isFinite(t) || t < since) return false }
    return true
  })
}

const ageSeconds = (p, now) => (p.ageBase || 0) + Math.max(0, Math.round((now - p.receivedAt) / 1000))

/** Pins for deliveries: pickup and destination (only when the server revealed them) plus the live volunteer where one is known. */
export function deliveryMarkers(deliveries, live = {}, now = Date.now()) {
  const out = []
  for (const d of deliveries || []) {
    if (!inMotion(d)) continue
    const title = d.need?.title || `Delivery #${d.id}`
    const { pickup, delivery } = d.points || {}
    if (pickup && Number.isFinite(pickup.latitude)) out.push({ id: `d${d.id}:pickup`, deliveryId: d.id, kind: 'donor', lat: pickup.latitude, lon: pickup.longitude, label: `Pickup: ${title}` })
    if (delivery && Number.isFinite(delivery.latitude)) out.push({ id: `d${d.id}:dest`, deliveryId: d.id, kind: 'org', lat: delivery.latitude, lon: delivery.longitude, label: `Deliver: ${title}` })
    const p = live[d.id]
    if (p && Number.isFinite(p.latitude)) out.push({ id: `d${d.id}:vol`, deliveryId: d.id, kind: 'volunteer', lat: p.latitude, lon: p.longitude, label: `Volunteer: ${title}`, stale: isStale(ageSeconds(p, now)), accuracy: p.accuracy_m, noFit: true })
  }
  return out
}

/** Things an administrator should look at. Based only on what the server already sent; no guessing. */
export function deliveryRisks(deliveries, now = Date.now()) {
  const risks = []
  for (const d of deliveries || []) {
    const title = d.need?.title || `Delivery #${d.id}`
    if (d.status === 'in_transit') {
      const t = Date.parse(d.milestones?.in_transit_at || '')
      if (Number.isFinite(t) && now - t > DELAYED_AFTER_HOURS * HOUR) risks.push({ id: d.id, kind: 'delayed', message: `${title} has been in transit for over ${DELAYED_AFTER_HOURS} hours.` })
    }
    if (d.status === 'delivered') {
      const t = Date.parse(d.milestones?.delivered_at || '')
      if (Number.isFinite(t) && now - t > UNCONFIRMED_AFTER_HOURS * HOUR) risks.push({ id: d.id, kind: 'unconfirmed_receipt', message: `${title} was delivered over ${UNCONFIRMED_AFTER_HOURS} hours ago and the organization has not confirmed receipt.` })
    }
    if (d.quantity_mismatch) risks.push({ id: d.id, kind: 'discrepancy', message: `${title}: the quantity received differs from the quantity sent.` })
  }
  return risks
}

/** Apply one live event to the map of known volunteer positions. */
export function applyLiveEvent(live, type, data, now = Date.now()) {
  const id = data?.task_id
  if (id == null) return live
  if (type === 'delivery.location' && Number.isFinite(data.latitude) && Number.isFinite(data.longitude)) {
    return { ...live, [id]: { latitude: data.latitude, longitude: data.longitude, accuracy_m: data.accuracy_m ?? null, receivedAt: now, ageBase: 0 } }
  }
  if (type === 'delivery.tracking' && (data.state === 'paused' || data.state === 'stopped')) {
    if (!(id in live)) return live
    const { [id]: _gone, ...rest } = live
    return rest
  }
  if (type === 'delivery.status' && !LIVE_STATUSES.includes(data.status) && id in live) {   // the leg ended: forget the position
    const { [id]: _gone, ...rest } = live
    return rest
  }
  return live
}

/** Store a position fetched over HTTP (initial load, or after a resync). */
export function seedLive(live, taskId, res, now = Date.now()) {
  if (!res?.has_position || res.paused || !Number.isFinite(res.latitude)) { if (!(taskId in live)) return live; const { [taskId]: _g, ...rest } = live; return rest }
  return { ...live, [taskId]: { latitude: res.latitude, longitude: res.longitude, accuracy_m: res.accuracy_m ?? null, receivedAt: now, ageBase: res.age_seconds || 0 } }
}

/** Wording for a /maps/route result. Always says whether traffic was considered; never presents a straight line as a road. */
export function etaSummary(route, locale = 'en-IN') {
  if (!route || !Number.isFinite(route.duration_s)) return null
  const at = new Date(route.arrival_at)
  const time = Number.isNaN(at.getTime()) ? '' : at.toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' })
  return {
    headline: formatDuration(route.duration_s),
    detail: `${formatRoadDistance(route.distance_m)} by road${time ? ` · arrives about ${time}` : ''}`,
    traffic: route.traffic_aware ? 'Includes current traffic' : 'Does not include traffic',
    line: decodePolyline(route.polyline),
  }
}

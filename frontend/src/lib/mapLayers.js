// Pure helpers that turn API data into map pins and legends for the map screens. No DOM, no network.

export const URGENCY_KIND = { critical: 'need-critical', high: 'need-high', medium: 'need-medium', low: 'need-low' }
export const urgencyKind = (urgency) => URGENCY_KIND[String(urgency || '').toLowerCase()] || 'need'

export const LEGEND_COLOURS = {
  'need-critical': '#b91c1c', 'need-high': '#ea580c', 'need-medium': '#ca8a04', 'need-low': '#0284c7',
  org: '#115E59', 'org-unverified': '#9ca3af', donor: '#db2777', volunteer: '#7c3aed', live: '#16a34a', me: '#2563eb'
}

const has = (p) => p && Number.isFinite(p.lat) && Number.isFinite(p.lon)

/** Pins for the "needs near you" map: the person's own saved position plus each need at its (approximate) place. */
export function nearbyNeedMarkers(data) {
  if (!data?.located) return []
  const out = []
  if (has(data.origin)) out.push({ id: 'me', kind: 'me', lat: data.origin.lat, lon: data.origin.lon, label: 'You' })
  for (const n of data.needs || []) {
    if (!has(n.position)) continue
    out.push({ id: `need-${n.need_id}`, kind: urgencyKind(n.urgency), lat: n.position.lat, lon: n.position.lon, label: n.title || n.category || 'Need', needId: n.need_id })
  }
  return out
}

/** The administrator map: which layers and filters are on decides which pins are drawn. */
export const DEFAULT_ADMIN_FILTERS = {
  layers: { organizations: true, needs: true, donors: true, volunteers: true, live: true },
  urgency: 'all', verifiedOnly: false, gapsOnly: false
}

export function adminMarkers(data, filters = DEFAULT_ADMIN_FILTERS) {
  if (!data) return []
  const { layers, urgency, verifiedOnly, gapsOnly } = { ...DEFAULT_ADMIN_FILTERS, ...filters, layers: { ...DEFAULT_ADMIN_FILTERS.layers, ...(filters.layers || {}) } }
  const gapIds = new Set((data.gaps || []).map((g) => g.need_id))
  const out = []
  const add = (id, kind, position, label, extra = {}) => { if (has(position)) out.push({ id, kind, lat: position.lat, lon: position.lon, label, ...extra }) }

  if (layers.organizations && !gapsOnly) for (const o of data.organizations || []) { if (verifiedOnly && !o.verified) continue; add(`org-${o.id}`, o.verified ? 'org' : 'org-unverified', o.position, o.name, { record: o, type: 'organization' }) }
  if (layers.needs) for (const n of data.needs || []) {
    if (urgency !== 'all' && String(n.urgency || '').toLowerCase() !== urgency) continue
    if (verifiedOnly && !n.verified_org) continue
    const isGap = gapIds.has(n.id)
    if (gapsOnly && !isGap) continue
    add(`need-${n.id}`, `${urgencyKind(n.urgency)}${isGap ? ' gap' : ''}`, n.position, n.title, { record: n, type: 'need', gap: isGap })
  }
  if (layers.donors && !gapsOnly) for (const d of data.donors || []) add(`donor-${d.id}`, 'donor', d.position, d.name || `Donor #${d.id}`, { record: d, type: 'donor' })
  if (layers.volunteers && !gapsOnly) for (const v of data.volunteers || []) add(`vol-${v.id}`, 'volunteer', v.position, v.name || `Volunteer #${v.id}`, { record: v, type: 'volunteer' })
  if (layers.live && !gapsOnly) for (const l of data.live_deliveries || []) add(`live-${l.task_id}`, 'live', l.position, `Delivery #${l.task_id}`, { record: l, type: 'live', stale: l.stale, noFit: true })
  return out
}

/** Counts shown beside each layer switch. */
export function adminCounts(data) {
  return {
    organizations: data?.organizations?.length || 0, needs: data?.needs?.length || 0, donors: data?.donors?.length || 0,
    volunteers: data?.volunteers?.length || 0, live: data?.live_deliveries?.length || 0, gaps: data?.gaps?.length || 0
  }
}

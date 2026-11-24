import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import TileMap from '../components/TileMap.jsx'
import MapLegend from '../components/MapLegend.jsx'
import { Button, EmptyState, ErrorState, PageHeader, Pill, Skeleton } from '../components/ui.jsx'
import { IconPin } from '../components/icons.jsx'
import { DEFAULT_ADMIN_FILTERS, adminCounts, adminMarkers } from '../lib/mapLayers.js'
import { ageText } from '../lib/mapMath.js'

const RADII = [10, 25, 50, 100, 200]
const LAYERS = [
  ['organizations', 'Organizations'], ['needs', 'Open needs'], ['donors', 'Donors'], ['volunteers', 'Volunteers'], ['live', 'Live deliveries']
]
const KEY = [
  { kind: 'org', label: 'Verified organization' }, { kind: 'org-unverified', label: 'Not verified' },
  { kind: 'need-critical', label: 'Need: critical' }, { kind: 'need-high', label: 'high' }, { kind: 'need-medium', label: 'medium' }, { kind: 'need-low', label: 'low' },
  { kind: 'donor', label: 'Donor' }, { kind: 'volunteer', label: 'Volunteer' }, { kind: 'live', label: 'Delivery in progress' }
]
const REFRESH_MS = 30000

function Detail({ marker }) {
  const r = marker.record
  const row = (k, v) => (v == null || v === '' ? null : <div key={k}><dt className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{k}</dt><dd className="mt-0.5 text-sm text-ink">{v}</dd></div>)
  const body = {
    organization: { title: r.name, rows: [row('Status', r.status), row('Address', r.address)], link: ['/admin/organizations', 'Open organizations'] },
    need: { title: r.title, rows: [row('Organization', r.organization_name), row('Quantity', r.quantity), row('Volunteers in range', r.volunteers_in_range), row('Donors in range', r.donors_in_range), row('Place taken from', r.located_via === 'need' ? 'the need' : 'its organization')], link: ['/admin/needs', 'Open all needs'] },
    donor: { title: r.name || `Donor #${r.id}`, rows: [row('Position', 'Shown to within about 1 km')], link: ['/admin/donors', 'Open all donors'] },
    volunteer: { title: r.name || `Volunteer #${r.id}`, rows: [row('Position', 'Shown to within about 1 km'), row('Travel range', r.service_radius_km != null ? `${r.service_radius_km} km` : 'not set')], link: ['/admin/volunteers', 'Open all volunteers'] },
    live: { title: `Delivery #${r.task_id}`, rows: [row('Item', r.need_title), row('Stage', String(r.status || '').replace(/_/g, ' ')), row('Last update', r.stale ? `${ageText(r.age_seconds)} (last known)` : ageText(r.age_seconds))], link: ['/deliveries', 'Open deliveries'] }
  }[marker.type]
  if (!body) return null
  return (
    <div className="rounded-xl border border-line p-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-ink">{body.title}</h3>
        {marker.type === 'need' && r.urgency && <StatusBadge status={r.urgency} />}
        {marker.gap && <Pill tone="red">No volunteer in range</Pill>}
      </div>
      <dl className="mt-2 grid gap-2 sm:grid-cols-2">{body.rows}</dl>
      <Link to={body.link[0]} className="btn-soft mt-3 inline-flex">{body.link[1]}</Link>
    </div>
  )
}

export default function AdminMap() {
  const [radius, setRadius] = useState(25)
  const [filters, setFilters] = useState(DEFAULT_ADMIN_FILTERS)
  const [selectedId, setSelectedId] = useState(null)
  const [focus, setFocus] = useState(null)
  const { data, loading, error, reload } = useAsync(() => api.adminMap(radius), [radius])

  // Keep live deliveries fresh while this page is open and visible.
  useEffect(() => {
    if (!filters.layers.live) return undefined
    const id = setInterval(() => { if (!document.hidden) reload({ silent: true }) }, REFRESH_MS)
    return () => clearInterval(id)
  }, [filters.layers.live, reload])

  const markers = useMemo(() => adminMarkers(data, filters), [data, filters])
  const counts = useMemo(() => adminCounts(data), [data])
  const selected = markers.find((m) => m.id === selectedId) || null
  const setLayer = (key) => setFilters((f) => ({ ...f, layers: { ...f.layers, [key]: !f.layers[key] } }))
  const pickGap = (g) => { setSelectedId(`need-${g.need_id}`); setFocus({ lat: g.position.lat, lon: g.position.lon, key: `${g.need_id}-${Date.now()}` }) }
  const unplaced = data?.unplaced || {}
  const unplacedTotal = (unplaced.organizations || 0) + (unplaced.needs || 0) + (unplaced.donors || 0) + (unplaced.volunteers || 0)

  return (
    <Layout title="Map overview">
      <PageHeader icon={IconPin} title="Map overview" subtitle="See where organizations, open needs, donors, volunteers and deliveries are, and which needs have nobody close enough to help."
        actions={<button type="button" onClick={() => reload()} className="btn bg-white/15 text-white hover:bg-white/25">Refresh</button>} />

      {error && !data ? <ErrorState message={error} onRetry={reload} /> : loading && !data ? <Skeleton className="h-96 w-full" /> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="card p-3">
            {markers.length === 0 && <EmptyState icon={IconPin} title="Nothing to show with these settings" text="Turn a layer on, or ask organizations, donors and volunteers to save their location in Settings." />}
            <TileMap markers={markers} height={560} ariaLabel="Administrator map overview" selectedId={selectedId} labels="selected" focus={focus}
              onSelect={(m) => setSelectedId((cur) => (cur === m.id ? null : m.id))} />
            <MapLegend items={KEY} />
            <p className="mt-1 text-xs text-ink-muted">{data?.precision_note}</p>
            {selected && <div className="mt-3"><Detail marker={selected} /></div>}
          </div>

          <aside className="space-y-4">
            <section className="card p-4" aria-label="Layers and filters">
              <h2 className="text-sm font-semibold text-ink">Show on the map</h2>
              <ul className="mt-2 space-y-1.5">
                {LAYERS.map(([key, label]) => (
                  <li key={key}>
                    <label className="flex items-center justify-between gap-2 text-sm text-ink">
                      <span className="flex items-center gap-2"><input type="checkbox" checked={filters.layers[key]} onChange={() => setLayer(key)} />{label}</span>
                      <Pill tone="gray">{counts[key]}</Pill>
                    </label>
                  </li>
                ))}
              </ul>
              <div className="mt-3 grid gap-2">
                <label className="flex items-center justify-between gap-2 text-xs font-semibold text-ink-muted">Need urgency
                  <select className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold text-ink" value={filters.urgency} onChange={(e) => setFilters((f) => ({ ...f, urgency: e.target.value }))}>
                    <option value="all">All</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
                  </select>
                </label>
                <label className="flex items-center justify-between gap-2 text-xs font-semibold text-ink-muted">A volunteer counts if within
                  <select className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold text-ink" value={radius} onChange={(e) => setRadius(Number(e.target.value))}>
                    {RADII.map((r) => <option key={r} value={r}>{r} km</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={filters.verifiedOnly} onChange={() => setFilters((f) => ({ ...f, verifiedOnly: !f.verifiedOnly }))} />Verified organizations only</label>
                <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={filters.gapsOnly} onChange={() => setFilters((f) => ({ ...f, gapsOnly: !f.gapsOnly }))} />Only needs with no volunteer in range</label>
              </div>
            </section>

            <section className="card p-4" aria-label="Needs with no volunteer nearby">
              <h2 className="text-sm font-semibold text-ink">No volunteer within {data?.radius_km ?? radius} km <Pill tone={counts.gaps ? 'red' : 'green'}>{counts.gaps}</Pill></h2>
              <p className="mt-1 text-xs text-ink-muted">Open needs that no volunteer can reach, counting each volunteer's own travel range. Most urgent first.</p>
              {counts.gaps === 0 ? <p className="mt-2 text-sm text-ink-muted">Every located need has at least one volunteer in range.</p> : (
                <ul className="mt-2 max-h-72 divide-y divide-line overflow-y-auto">
                  {data.gaps.map((g) => (
                    <li key={g.need_id}>
                      <button type="button" onClick={() => pickGap(g)} className="flex w-full items-center gap-2 py-2 text-left">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold text-ink">{g.title}</span>
                          <span className="block truncate text-xs text-ink-muted">{g.organization_name || 'Organization'} · {g.nearest_volunteer_km != null ? `nearest volunteer about ${g.nearest_volunteer_km} km away` : 'no volunteer has shared a location'}</span>
                        </span>
                        {g.urgency && <StatusBadge status={g.urgency} />}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {unplacedTotal > 0 && (
              <section className="card p-4 text-xs text-ink-muted" aria-label="Records without a location">
                <h2 className="text-sm font-semibold text-ink">Not on the map</h2>
                <p className="mt-1">These have no saved location, so they are not drawn and not guessed:</p>
                <ul className="mt-1 list-disc pl-5">
                  {unplaced.organizations > 0 && <li>{unplaced.organizations} organization{unplaced.organizations === 1 ? '' : 's'}</li>}
                  {unplaced.needs > 0 && <li>{unplaced.needs} open need{unplaced.needs === 1 ? '' : 's'}</li>}
                  {unplaced.donors > 0 && <li>{unplaced.donors} donor{unplaced.donors === 1 ? '' : 's'}</li>}
                  {unplaced.volunteers > 0 && <li>{unplaced.volunteers} volunteer{unplaced.volunteers === 1 ? '' : 's'}</li>}
                </ul>
              </section>
            )}
          </aside>
        </div>
      )}
    </Layout>
  )
}

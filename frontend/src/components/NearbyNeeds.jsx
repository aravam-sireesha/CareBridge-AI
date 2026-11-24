import React, { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import StatusBadge from './StatusBadge.jsx'
import TileMap from './TileMap.jsx'
import MapLegend from './MapLegend.jsx'
import { EmptyState, ErrorState, Pill, Skeleton } from './ui.jsx'
import { IconPin, IconArrowRight } from './icons.jsx'
import { nearbyNeedMarkers } from '../lib/mapLayers.js'

const RADII = [10, 25, 50, 100]
const KEY = [
  { kind: 'me', label: 'You' }, { kind: 'need-critical', label: 'Critical' }, { kind: 'need-high', label: 'High' },
  { kind: 'need-medium', label: 'Medium' }, { kind: 'need-low', label: 'Low' }
]

/** Open needs from verified organizations near the position the signed-in donor or volunteer chose to share, as a list or on a map. */
export default function NearbyNeeds() {
  const [radius, setRadius] = useState(null) // null = the server's default (a volunteer's own travel range, else the default)
  const [view, setView] = useState('list')
  const [selectedId, setSelectedId] = useState(null)
  const { data, loading, error, reload } = useAsync(() => api.nearbyNeeds(radius), [radius])
  const markers = useMemo(() => nearbyNeedMarkers(data), [data])
  const rings = useMemo(() => (data?.located && data.origin ? [{ id: 'reach', lat: data.origin.lat, lon: data.origin.lon, radiusKm: data.radius_km }] : []), [data])

  if (loading && !data) return <div className="card space-y-3 p-4"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-full" /></div>
  if (error && !data) return <ErrorState message={error} onRetry={reload} />

  if (!data?.located) {
    return (
      <div className="card p-2">
        <EmptyState icon={IconPin} title="Share your location to see needs near you"
          text={data?.message || 'It is optional, and you can remove it at any time.'}
          action={<Link to="/settings?tab=location" className="btn-soft">Set my location</Link>} />
      </div>
    )
  }

  const shown = data.radius_km
  const selected = data.needs.find((n) => `need-${n.need_id}` === selectedId)
  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-ink-muted">Within <strong className="text-ink">{shown} km</strong> of your saved location</p>
        <div className="flex flex-wrap items-center gap-3">
          <div className="cbm-switch" role="group" aria-label="Show needs as">
            <button type="button" aria-pressed={view === 'list'} onClick={() => setView('list')}>List</button>
            <button type="button" aria-pressed={view === 'map'} onClick={() => setView('map')}>Map</button>
          </div>
          <label className="flex items-center gap-2 text-xs font-semibold text-ink-muted">
            Search radius
            <select className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold text-ink" value={radius ?? ''} onChange={(e) => setRadius(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Default ({shown} km)</option>
              {RADII.map((r) => <option key={r} value={r}>{r} km</option>)}
            </select>
          </label>
        </div>
      </div>

      {view === 'map' && (
        <div className="mb-3">
          <TileMap markers={markers} rings={rings} height={340} ariaLabel="Needs near you" selectedId={selectedId} labels="selected"
            onSelect={(m) => m.needId && setSelectedId((cur) => (cur === m.id ? null : m.id))} />
          <MapLegend items={KEY} />
          <p className="mt-1 text-xs text-ink-muted">The dashed ring is your search radius. Need pins are placed to within about 1 km of the organization, not at its door. Select a pin for details.</p>
          {selected && (
            <Link to={`/needs?open=${selected.need_id}`} className="group mt-2 flex items-center gap-3 rounded-xl border border-line p-3" aria-label={`Open need: ${selected.title || selected.category || 'Need'}`}>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-ink">{selected.title || selected.category || 'Need'}</span>
                <span className="block truncate text-xs text-ink-muted">{selected.organization_name || 'Organization'}{selected.quantity != null ? ` · ${selected.quantity} needed` : ''}</span>
              </span>
              {selected.urgency && <StatusBadge status={selected.urgency} />}
              <Pill tone="teal">{selected.distance_label}</Pill>
              <IconArrowRight className="h-4 w-4 text-ink-muted group-hover:text-teal-700" />
            </Link>
          )}
        </div>
      )}

      {data.needs.length === 0 ? (
        <EmptyState icon={IconPin} title="No open needs in this area" text="Try a wider radius. Needs appear here once a verified organization posts them." />
      ) : (
        <ul className={`divide-y divide-line ${view === 'map' ? 'hidden' : ''}`}>
          {data.needs.map((n) => (
            <li key={n.need_id}>
              <Link to={`/needs?open=${n.need_id}`} className="group flex items-center gap-3 py-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-teal-50 text-teal-700"><IconPin className="h-[18px] w-[18px]" /></span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-ink">{n.title || n.category || 'Need'}</span>
                  <span className="block truncate text-xs text-ink-muted">{n.organization_name || 'Organization'}{n.quantity != null ? ` · ${n.quantity} needed` : ''}</span>
                </span>
                {n.urgency && <StatusBadge status={n.urgency} />}
                <Pill tone="teal">{n.distance_label}</Pill>
                <IconArrowRight className="h-4 w-4 text-ink-muted group-hover:text-teal-700" />
              </Link>
            </li>
          ))}
        </ul>
      )}
      {data.note && <p className="mt-3 text-xs text-ink-muted">{data.note}</p>}
    </div>
  )
}

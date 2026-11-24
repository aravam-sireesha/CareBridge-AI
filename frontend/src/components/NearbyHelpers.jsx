import React, { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAsync } from '../hooks/useAsync.js'
import { ErrorState, Pill, Skeleton } from './ui.jsx'
import TileMap from './TileMap.jsx'

const RADII = [10, 25, 50, 100]

function PeopleList({ title, people, missing, kind }) {
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{title}</h4>
      {people.length === 0 ? (
        <p className="mt-1 text-sm text-ink-muted">None with a shared location in this range.</p>
      ) : (
        <ul className="mt-1.5 divide-y divide-line rounded-xl border border-line">
          {people.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
              <span className="min-w-0 truncate font-medium text-ink">{p.name || `${kind} #${p.id}`}</span>
              <span className="flex shrink-0 items-center gap-1.5">
                {kind === 'volunteer' && p.within_service_radius === false && <Pill tone="amber">Outside their travel range</Pill>}
                {kind === 'volunteer' && p.within_service_radius === true && <Pill tone="green">In their travel range</Pill>}
                <Pill tone="teal">{p.distance_label}</Pill>
              </span>
            </li>
          ))}
        </ul>
      )}
      {missing > 0 && <p className="mt-1 text-xs text-ink-muted">{missing} not shown because they have not shared a location.</p>}
    </div>
  )
}

/** Donors and volunteers near one need. Rounded distances only; the server decides whose records the caller may see. */
export default function NearbyHelpers({ needId }) {
  const [radius, setRadius] = useState(null)
  const { data, loading, error, reload } = useAsync(() => api.helpersNearNeed(needId, radius), [needId, radius])
  const [showMap, setShowMap] = useState(false)
  const origin = data?.origin
  const markers = useMemo(() => (origin ? [{ id: 'need', kind: 'need', lat: origin.lat, lon: origin.lon, label: 'This need' }] : []), [origin])
  const rings = useMemo(() => (origin && data?.radius_km ? [{ id: 'reach', lat: origin.lat, lon: origin.lon, radiusKm: data.radius_km }] : []), [origin, data?.radius_km])

  if (loading && !data) return <div className="space-y-2"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-10 w-full" /></div>
  if (error && !data) return <ErrorState message={error} onRetry={reload} />

  return (
    <div className="space-y-4 border-t border-line pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">Helpers near this need</h3>
        {data?.located && (
          <label className="flex items-center gap-2 text-xs font-semibold text-ink-muted">
            Radius
            <select className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold text-ink" value={radius ?? ''} onChange={(e) => setRadius(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Default ({data.radius_km} km)</option>
              {RADII.map((r) => <option key={r} value={r}>{r} km</option>)}
            </select>
          </label>
        )}
      </div>

      {!data?.located ? (
        <p className="text-sm text-ink-muted">{data?.message} <Link to="/settings?tab=location" className="font-semibold text-teal-700 underline">Set the location</Link></p>
      ) : (
        <>
          <PeopleList title="Donors" kind="donor" people={data.donors} missing={data.donors_without_location} />
          <PeopleList title="Volunteers" kind="volunteer" people={data.volunteers} missing={data.volunteers_without_location} />
          {origin && (
            <div>
              <button type="button" className="text-xs font-semibold text-teal-700 underline" aria-expanded={showMap} onClick={() => setShowMap((v) => !v)}>{showMap ? 'Hide map' : 'Show reach on a map'}</button>
              {showMap && (
                <div className="mt-2">
                  <TileMap markers={markers} rings={rings} height={280} ariaLabel="Search area around this need" />
                  <p className="mt-1 text-xs text-ink-muted">The dashed ring is the {data.radius_km} km search area around this need: {data.donors.length} donor{data.donors.length === 1 ? '' : 's'} and {data.volunteers.length} volunteer{data.volunteers.length === 1 ? '' : 's'} inside it. Individual donors and volunteers are not pinned, to protect their privacy.</p>
                </div>
              )}
            </div>
          )}
          <p className="text-xs text-ink-muted">{data.note} Distance is measured from {data.distance_basis === 'need' ? "this need's location" : "your organization's location"}.</p>
        </>
      )}
    </div>
  )
}

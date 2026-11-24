import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Layout from '../components/Layout.jsx'
import LiveMap from '../components/map/LiveMap.jsx'
import MapLegend from '../components/MapLegend.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { EmptyState, PageHeader } from '../components/ui.jsx'
import { IconPin } from '../components/icons.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api/client.js'
import { useLiveEvent, useLiveStatus } from '../hooks/useLiveEvent.js'
import { DEFAULT_ADMIN_FILTERS, adminMarkers, nearbyNeedMarkers } from '../lib/mapLayers.js'
import { describeGeoError, getCurrentPosition } from '../lib/geo.js'
import { LIVE_STATUSES, applyLiveEvent, deliveryMarkers, deliveryRisks, etaSummary, filterDeliveries, inMotion, seedLive } from '../lib/mapHub.js'

const KEY = [{ kind: 'donor', label: 'Pickup' }, { kind: 'org', label: 'Destination' }, { kind: 'volunteer', label: 'Volunteer (live)' }, { kind: 'need-critical', label: 'Open need' }]
const STATUS_OPTIONS = [['active', 'In progress'], ['all', 'All'], ['accepted', 'Accepted'], ['picked_up', 'Picked up'], ['in_transit', 'In transit'], ['delivered', 'Delivered, awaiting receipt']]
const PERIODS = [[0, 'Any time'], [7, 'Last 7 days'], [30, 'Last 30 days']]
const MODES = [['drive', 'Car'], ['two_wheeler', 'Two-wheeler'], ['walk', 'Walking']]
const SEED_LIMIT = 25

/** One live map for every role. What each role can see is decided by the server: this page only draws what it is sent. */
export default function MapHub() {
  const { user } = useAuth()
  const role = user?.role
  const isVolunteer = role === 'volunteer'
  const liveOpen = useLiveStatus() === 'open'

  const [deliveries, setDeliveries] = useState([])
  const [needs, setNeeds] = useState(null)
  const [needsNote, setNeedsNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [live, setLive] = useState({})
  const [filters, setFilters] = useState({ status: 'active', category: 'all', days: 0 })
  const [showNeeds, setShowNeeds] = useState(role !== 'organization')
  const [selectedId, setSelectedId] = useState(null)
  const [panelOpen, setPanelOpen] = useState(true)
  const [focusRequest, setFocusRequest] = useState(null)
  const [mode, setMode] = useState('drive')
  const [route, setRoute] = useState({})
  const [trail, setTrail] = useState(null)
  const [alerts, setAlerts] = useState([])

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const list = await api.listDeliveries()
      setDeliveries(Array.isArray(list) ? list : [])
      setError('')
      const watchable = (Array.isArray(list) ? list : []).filter((d) => d.tracking?.can_watch && !d.tracking?.can_share && LIVE_STATUSES.includes(d.status)).slice(0, SEED_LIMIT)
      const seeded = await Promise.allSettled(watchable.map((d) => api.getDeliveryLocation(d.id).then((r) => [d.id, r])))
      setLive((cur) => seeded.reduce((acc, r) => (r.status === 'fulfilled' ? seedLive(acc, r.value[0], r.value[1]) : acc), cur))
    } catch (e) { setError(e.message || 'Could not load deliveries.') } finally { setLoading(false) }
  }, [])
  useEffect(() => {                                           // the optional "open needs" layer: its own endpoint, its own failure note
    let alive = true
    const fetcher = role === 'admin' ? api.adminMap : role === 'donor' || role === 'volunteer' ? api.nearbyNeeds : null
    if (!fetcher) return undefined
    fetcher().then((d) => alive && setNeeds(d)).catch((e) => alive && setNeedsNote(`The open-needs layer could not be loaded: ${e.message}`))
    return () => { alive = false }
  }, [role])
  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(() => { if (!document.hidden) load(true) }, liveOpen ? 120000 : 15000); return () => clearInterval(t) }, [load, liveOpen])

  // live updates: positions and status changes arrive over the event stream
  const quietReload = useRef(null)
  const scheduleReload = () => { clearTimeout(quietReload.current); quietReload.current = setTimeout(() => load(true), 1200) }
  useEffect(() => () => clearTimeout(quietReload.current), [])
  useLiveEvent('delivery.location', (d) => setLive((l) => applyLiveEvent(l, 'delivery.location', d)))
  useLiveEvent('delivery.tracking', (d) => setLive((l) => applyLiveEvent(l, 'delivery.tracking', d)))
  useLiveEvent('delivery.status', (d) => { setLive((l) => applyLiveEvent(l, 'delivery.status', d)); scheduleReload() })
  useLiveEvent('system.resync', () => load(true))
  useLiveEvent('risk.alert', (d) => { if (role === 'admin') setAlerts((a) => [{ ...d, at: Date.now() }, ...a].slice(0, 5)) })

  const visible = useMemo(() => filterDeliveries(deliveries, filters), [deliveries, filters])
  const categories = useMemo(() => [...new Set(deliveries.map((d) => d.need?.category).filter(Boolean))].sort(), [deliveries])
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(t) }, [])
  const risks = useMemo(() => (role === 'admin' ? deliveryRisks(deliveries, now) : []), [deliveries, role, now])

  const deliveryPins = useMemo(() => deliveryMarkers(visible, live, now), [visible, live, now])
  const needPins = useMemo(() => {
    if (!showNeeds || !needs) return []
    const pins = role === 'admin'
      ? adminMarkers(needs, { ...DEFAULT_ADMIN_FILTERS, layers: { ...DEFAULT_ADMIN_FILTERS.layers, organizations: true, needs: true, donors: false, volunteers: false, live: false } })
      : nearbyNeedMarkers(needs)
    return pins.map((m) => ({ ...m, noFit: deliveryPins.length > 0 }))     // the camera frames the deliveries when there are any
  }, [showNeeds, needs, role, deliveryPins.length])
  const markers = useMemo(() => [...deliveryPins, ...needPins], [deliveryPins, needPins])

  const selected = useMemo(() => deliveries.find((d) => d.id === selectedId) || null, [deliveries, selectedId])
  const lines = useMemo(() => {
    const out = []
    if (route.data?.line?.length > 1) out.push({ id: 'route', points: route.data.line, color: '#2563eb' })
    if (trail?.points?.length > 1) out.push({ id: 'trail', points: trail.points, color: '#b45309' })
    return out
  }, [route.data, trail])

  const choose = useCallback((d) => {
    setSelectedId(d.id); setRoute({}); setTrail(null)
    const p = d.points?.delivery || d.points?.pickup
    if (p) setFocusRequest({ lat: p.latitude, lon: p.longitude, key: `d${d.id}-${Date.now()}` })
  }, [])
  const onSelect = useCallback((m) => { const d = m.deliveryId ? deliveries.find((x) => x.id === m.deliveryId) : null; if (d) choose(d) }, [deliveries, choose])

  const legFor = (d) => (d.status === 'accepted' || d.status === 'pickup_scheduled' ? 'pickup' : 'delivery')
  const fetchRoute = useCallback(async (d, withDevicePosition) => {
    setRoute((r) => ({ ...r, loading: true, error: '' }))
    try {
      const opts = { leg: legFor(d), mode }
      if (withDevicePosition) { const p = await getCurrentPosition({ highAccuracy: true }); opts.lat = p.latitude; opts.lon = p.longitude }
      setRoute({ data: etaSummary(await api.mapsRoute(d.id, opts)) })
    } catch (e) { setRoute({ error: e?.code ? describeGeoError(e) : e.message }) }
  }, [mode])
  // viewers get an ETA automatically while a live position exists; a volunteer asks for theirs (it needs the device position)
  const liveForSelected = selected && live[selected.id]
  useEffect(() => {
    if (!selected || isVolunteer || !LIVE_STATUSES.includes(selected.status) || !liveForSelected) return undefined
    fetchRoute(selected, false)
    const t = setInterval(() => fetchRoute(selected, false), 60000)
    return () => clearInterval(t)
  }, [selected?.id, selected?.status, Boolean(liveForSelected), mode]) // eslint-disable-line react-hooks/exhaustive-deps

  const showTrail = async (d) => {
    try { const r = await api.deliveryLocationHistory(d.id); setTrail({ points: r.points.map((p) => ({ lat: p.latitude, lon: p.longitude })), count: r.points.length, days: r.retention_days }) }
    catch (e) { setTrail({ error: e.message }) }
  }

  return (
    <Layout title="Live map">
      <PageHeader icon={IconPin} title="Live map" subtitle={role === 'admin' ? 'Deliveries in progress, where volunteers are, delays that need attention, and open needs.' : isVolunteer ? 'Your pickups and deliveries, road routes and arrival times.' : 'Follow deliveries to your organization or from your donation as they happen.'}
        actions={<span className="rounded-full bg-white/15 px-3 py-1 text-xs font-semibold text-white" role="status">{liveOpen ? 'Live updates on' : 'Live updates reconnecting: refreshing every 15 seconds'}</span>} />

      <div className="mb-3 flex flex-wrap items-end gap-3">
        <label className="text-xs font-semibold text-ink-muted">Show
          <select className="field mt-1 block" value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}>{STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label className="text-xs font-semibold text-ink-muted">Category
          <select className="field mt-1 block" value={filters.category} onChange={(e) => setFilters((f) => ({ ...f, category: e.target.value }))}><option value="all">All categories</option>{categories.map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
        <label className="text-xs font-semibold text-ink-muted">Period
          <select className="field mt-1 block" value={filters.days} onChange={(e) => setFilters((f) => ({ ...f, days: Number(e.target.value) }))}>{PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        {role !== 'organization' && <label className="flex items-center gap-2 pb-2 text-sm text-ink"><input type="checkbox" checked={showNeeds} onChange={(e) => setShowNeeds(e.target.checked)} /> Show open needs</label>}
        <button type="button" className="btn-ghost ml-auto" aria-expanded={panelOpen} aria-controls="maphub-panel" onClick={() => setPanelOpen((o) => !o)}>{panelOpen ? 'Hide panel' : 'Show panel'}</button>
      </div>
      {needsNote && <p className="mb-3 text-xs text-ink-muted" role="status">{needsNote}</p>}

      <div className={`grid gap-4 ${panelOpen ? 'lg:grid-cols-[minmax(0,1fr)_22rem]' : ''}`}>
        <div className="card p-3">
          <LiveMap markers={markers} lines={lines} height={560} loading={loading && deliveries.length === 0} error={deliveries.length === 0 ? error : ''} onRetry={() => load()}
            ariaLabel="Live delivery map" onSelect={onSelect} selectedId={selected ? `d${selected.id}:vol` : undefined} focusRequest={focusRequest} emptyText="No deliveries in progress match these settings." />
          <MapLegend items={KEY} />
          {error && deliveries.length > 0 && <p className="mt-2 text-xs text-red-700" role="alert">Showing the last information received. {error}</p>}
          <p className="mt-1 text-xs text-ink-muted">Volunteer positions are shown to about 10 m, only while they choose to share, and never before the delivery leg. Road distance and arrival times come from a routing service, not a straight line.</p>
        </div>

        {panelOpen && (
          <aside id="maphub-panel" className="space-y-3" aria-label="Deliveries">
            {risks.length > 0 && (
              <div className="card border-amber-200 bg-amber-50/60 p-3" role="region" aria-label="Needs attention">
                <h3 className="text-sm font-semibold text-ink">Needs attention</h3>
                <ul className="mt-1 space-y-1 text-xs text-ink">{risks.map((r) => <li key={`${r.id}-${r.kind}`}><button type="button" className="text-left underline" onClick={() => { const d = deliveries.find((x) => x.id === r.id); if (d) choose(d) }}>{r.message}</button></li>)}</ul>
              </div>
            )}
            {alerts.length > 0 && (
              <div className="card border-red-200 bg-red-50/60 p-3" role="region" aria-label="Live alerts">
                <h3 className="text-sm font-semibold text-ink">Live alerts</h3>
                <ul className="mt-1 space-y-1 text-xs text-ink">{alerts.map((a, i) => <li key={i}>Delivery #{a.task_id}: {String(a.kind).replace(/_/g, ' ')} ({a.severity})</li>)}</ul>
              </div>
            )}

            {selected && (
              <div className="card p-3" aria-live="polite">
                <div className="flex items-start justify-between gap-2"><h3 className="text-sm font-semibold text-ink">{selected.need?.title || `Delivery #${selected.id}`}</h3><StatusBadge status={selected.status} /></div>
                <p className="mt-1 text-xs text-ink-muted">{selected.organization?.name}{selected.quantity ? ` · quantity ${selected.quantity}` : ''}{selected.volunteer?.name ? ` · volunteer ${selected.volunteer.name}` : ''}</p>
                {isVolunteer && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <select aria-label="Travel mode" className="field" value={mode} onChange={(e) => setMode(e.target.value)}>{MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                    <button type="button" className="btn-primary" disabled={route.loading || !inMotion(selected)} onClick={() => fetchRoute(selected, true)}>{route.loading ? 'Working it out…' : `Route to ${legFor(selected) === 'pickup' ? 'pickup' : 'destination'}`}</button>
                  </div>
                )}
                {route.loading && !isVolunteer && <p className="mt-2 text-xs text-ink-muted" role="status">Working out the arrival time…</p>}
                {route.data && (
                  <div className="mt-2 rounded-lg bg-teal-50 p-2" role="status">
                    <p className="text-lg font-semibold text-ink">{route.data.headline}</p><p className="text-xs text-ink">{route.data.detail}</p><p className="text-xs text-ink-muted">{route.data.traffic}</p>
                  </div>
                )}
                {route.error && <p className="mt-2 text-xs text-ink-muted" role="status">{route.error}</p>}
                {!route.data && !route.error && !route.loading && !isVolunteer && LIVE_STATUSES.includes(selected.status) && !liveForSelected && <p className="mt-2 text-xs text-ink-muted">Arrival time appears once the volunteer shares their location.</p>}
                {role === 'admin' && (
                  <div className="mt-2">
                    <button type="button" className="btn-ghost" onClick={() => showTrail(selected)}>Show movement record</button>
                    {trail?.error && <p className="mt-1 text-xs text-ink-muted" role="status">{trail.error}</p>}
                    {trail && !trail.error && <p className="mt-1 text-xs text-ink-muted" role="status">{trail.count ? `${trail.count} recorded points, kept ${trail.days} days. Viewing this is logged.` : 'No route record exists: the volunteer did not agree to one, or it has been deleted.'}</p>}
                  </div>
                )}
              </div>
            )}

            <div className="card p-3">
              <h3 className="text-sm font-semibold text-ink">Deliveries ({visible.length})</h3>
              {visible.length === 0 ? <p className="mt-1 text-xs text-ink-muted">Nothing matches these settings.</p> : (
                <ul className="mt-2 max-h-80 space-y-1 overflow-y-auto">
                  {visible.map((d) => (
                    <li key={d.id}><button type="button" onClick={() => choose(d)} aria-current={d.id === selectedId} className={`flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-teal-50 ${d.id === selectedId ? 'bg-teal-50' : ''}`}>
                      <span className="min-w-0 truncate text-ink">{d.need?.title || `Delivery #${d.id}`}</span><StatusBadge status={d.status} /></button></li>
                  ))}
                </ul>
              )}
            </div>
            {!loading && deliveries.length === 0 && !error && <EmptyState icon={IconPin} title="No deliveries yet" text="When a donation is on its way you will see it here." />}
          </aside>
        )}
      </div>
    </Layout>
  )
}

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client.js'
import TileMap from './TileMap.jsx'
import { describeGeoError, geolocationSupport } from '../lib/geo.js'
import { ageText, bearingLabel, formatDistance, haversineKm, navLinks } from '../lib/mapMath.js'
import { applyTrackingState, buildFix, classifyTrackingError, createSeq, isStale, remoteFromEvent } from '../lib/trackingPayload.js'
import { useLiveEvent, useLiveStatus } from '../hooks/useLiveEvent.js'
import { createWakeLock, wakeLockSupported } from '../lib/wakeLock.js'

const SEND_EVERY_MS = 6000       // the server accepts one position every 5 s
const POLL_EVERY_MS = 10000       // viewers poll this often ONLY while the live connection is down
const POLL_WHEN_LIVE_MS = 60000   // otherwise a slow safety net: live updates arrive over the event stream

/** Live location and navigation for ONE delivery.
 *  - The assigned volunteer opts in per delivery, sees exactly what is shared, and can stop at any time.
 *  - The organization, donor and administrators watch only during the delivery leg, and see "waiting" or "last known" honestly.
 *  - Navigation hands the destination to a real maps app; this screen never calculates road routes or arrival times. */
export default function LiveTracking({ task, onChanged }) {
  const t = task.tracking || {}
  const [sharing, setSharing] = useState(Boolean(t.sharing))
  const [sending, setSending] = useState(false)
  const [me, setMe] = useState(null)
  const [lastSent, setLastSent] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [remote, setRemote] = useState(null)
  const [paused, setPaused] = useState(Boolean(t.paused))
  const [retain, setRetain] = useState(false)               // the volunteer's separate choice: may a route record be kept?
  const [recording, setRecording] = useState(Boolean(t.retain_history))
  const watch = useRef(null)
  const lastPost = useRef(0)
  const sessionRef = useRef(t.tracking_session_id || null)
  const nextSeq = useRef(createSeq()).current
  const live = useLiveStatus() === 'open'
  const viewing = Boolean(t.can_watch && !t.can_share)

  useEffect(() => {
    setSharing(Boolean(t.sharing)); setPaused(Boolean(t.paused)); setRecording(Boolean(t.retain_history))
    if (t.tracking_session_id) sessionRef.current = t.tracking_session_id
  }, [t.sharing, t.paused, t.retain_history, t.tracking_session_id])
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id) }, [])
  const [awake, setAwake] = useState(false)
  const wake = useRef(null)
  if (wake.current === null) wake.current = createWakeLock({ onChange: setAwake })
  const endWatch = useCallback(() => { if (watch.current != null) { navigator.geolocation.clearWatch(watch.current); watch.current = null } wake.current?.release(); setSending(false) }, [])
  useEffect(() => endWatch, [endWatch])                               // leaving the screen stops this device from sending

  const onFix = useCallback(async (pos) => {
    setMe({ lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy: pos.coords.accuracy })
    const at = Date.now(); if (at - lastPost.current < SEND_EVERY_MS) return
    lastPost.current = at
    try { await api.sendDeliveryLocation(task.id, buildFix(pos, { sessionId: sessionRef.current, seq: nextSeq() })); setLastSent(Date.now()); setError('') }
    catch (e) {
      const kind = classifyTrackingError(e.message)
      if (kind === 'ended') { endWatch(); setSharing(false); setError(e.message) }
      else if (kind === 'paused') { endWatch(); setPaused(true) }
      else if (kind !== 'slow' && kind !== 'bad_time') setError(e.message)      // a cached/old reading or a too-quick retry just waits for the next fix
    }
  }, [task.id, endWatch, nextSeq])
  const onGeoError = useCallback(async (e) => {
    setError(describeGeoError(e))
    if (e && e.code === 1) { endWatch(); setSharing(false); try { await api.deliveryTrackingStop(task.id) } catch { /* the server also clears it when the delivery ends */ } }
  }, [task.id, endWatch])
  const begin = useCallback(() => {
    const support = geolocationSupport(); if (!support.available) { setError(support.reason); return false }
    watch.current = navigator.geolocation.watchPosition(onFix, onGeoError, { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 })
    setSending(true); wake.current?.acquire(); return true          // keep the screen on while sharing; released by endWatch (pause, stop, leaving the page)
  }, [onFix, onGeoError])

  const start = async () => {
    setBusy(true); setError('')
    try {
      const res = await api.deliveryTrackingStart(task.id, { retain_history: retain })
      sessionRef.current = res?.tracking_session_id || null; setRecording(Boolean(res?.retain_history)); setPaused(false); setSharing(true)
      if (!begin()) { await api.deliveryTrackingStop(task.id); setSharing(false) }
      onChanged?.()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const stop = async () => {
    setBusy(true); endWatch()
    try { await api.deliveryTrackingStop(task.id); setSharing(false); setPaused(false); setMe(null); setLastSent(null); onChanged?.() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const pause = async () => {
    setBusy(true); endWatch()
    try { await api.deliveryTrackingPause(task.id); setPaused(true); setLastSent(null); onChanged?.() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const resume = async () => {
    setBusy(true); setError('')
    try { await api.deliveryTrackingResume(task.id); setPaused(false); begin(); onChanged?.() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  // Viewers (organization, donor, administrator): live updates over the event stream; polling only as a fallback.
  const loadRemote = useRef(null)
  useEffect(() => {
    if (!viewing) return undefined
    let alive = true
    const load = async () => { try { const r = await api.getDeliveryLocation(task.id); if (alive) { setRemote({ ...r, fetchedAt: Date.now() }); setError('') } } catch (e) { if (alive) setError(e.message) } }
    loadRemote.current = load
    load()                                                        // also refills anything missed while the connection was down
    const id = setInterval(() => { if (!document.hidden) load() }, live ? POLL_WHEN_LIVE_MS : POLL_EVERY_MS)
    return () => { alive = false; clearInterval(id) }
  }, [task.id, viewing, live])
  useLiveEvent('delivery.location', (d) => { if (viewing && d.task_id === task.id) setRemote(remoteFromEvent(d)) })
  useLiveEvent('delivery.tracking', (d) => {
    if (d.task_id !== task.id) return
    if (viewing) setRemote((r) => applyTrackingState(r, d.state))
    else if (t.can_share) {                                       // the volunteer changed sharing from another tab or device
      if (d.state === 'stopped') { endWatch(); setSharing(false); setPaused(false) }
      else if (d.state === 'paused') { endWatch(); setPaused(true) }
    }
  })
  useLiveEvent('system.resync', () => { if (viewing) loadRemote.current?.() })

  const pickup = task.points?.pickup; const delivery = task.points?.delivery
  const markers = useMemo(() => {
    const m = []
    if (pickup) m.push({ id: 'pickup', kind: 'pickup', lat: pickup.latitude, lon: pickup.longitude, label: 'Pickup' })
    if (delivery) m.push({ id: 'delivery', kind: 'delivery', lat: delivery.latitude, lon: delivery.longitude, label: 'Delivery' })
    if (t.can_share && me) m.push({ id: 'me', kind: 'me', lat: me.lat, lon: me.lon, label: 'You', accuracy: me.accuracy })
    if (!t.can_share && remote?.has_position) m.push({ id: 'vol', kind: 'volunteer', lat: remote.latitude, lon: remote.longitude, label: 'Volunteer', stale: isStale((remote.age_seconds ?? 0) + Math.round((now - remote.fetchedAt) / 1000), remote.stale), accuracy: remote.accuracy_m })
    return m
  }, [pickup, delivery, me, remote, t.can_share, now])

  const showNav = t.can_share && (pickup || delivery)
  const missingPlace = t.can_share && task.addresses_visible?.delivery && !delivery
  const sentAgo = lastSent ? Math.max(0, Math.round((now - lastSent) / 1000)) : null
  const remoteAge = remote?.has_position ? (remote.age_seconds ?? 0) + Math.round((now - remote.fetchedAt) / 1000) : null
  const remoteStale = remote?.has_position ? isStale(remoteAge, remote.stale) : false
  if (!t.can_share && !t.can_watch && !pickup && !delivery) return null

  return (
    <section className="cbt" aria-label="Live location and navigation">
      <h3>{t.can_share ? 'Navigation and live location' : 'Delivery on the map'}</h3>

      {t.can_share && !sharing && (
        <div className="cbt-consent">
          <p><strong>Share my live location for this delivery?</strong> The organization, the donor and administrators will see roughly where you are (to about 10 m) only while you are carrying the items. Your latest position is deleted when the delivery ends, and you can pause or stop at any time. Nothing is shared unless you press the button.</p>
          <label className="cbt-check">
            <input type="checkbox" checked={retain} onChange={(e) => setRetain(e.target.checked)} />
            <span>Optional: also let administrators keep a record of my route for a limited time, so a delivery problem can be looked into. If this is unticked, no route record is kept.</span>
          </label>
        </div>
      )}
      {t.can_share && (
        <div className="cbt-actions">
          {!sharing && <button type="button" className="cbt-btn" onClick={start} disabled={busy}>Start sharing my location</button>}
          {sharing && paused && <button type="button" className="cbt-btn" onClick={resume} disabled={busy}>Resume sharing</button>}
          {sharing && !paused && !sending && <button type="button" className="cbt-btn" onClick={() => begin()} disabled={busy}>Resume sending</button>}
          {sharing && !paused && <button type="button" className="cbt-btn cbt-btn--ghost" onClick={pause} disabled={busy}>Pause</button>}
          {sharing && <button type="button" className="cbt-btn cbt-btn--danger" onClick={stop} disabled={busy}>Stop sharing</button>}
        </div>
      )}
      {t.can_share && sharing && (
        <p className="cbt-status" role="status"><span className={`cbt-dot ${sending && !paused ? '' : 'cbt-dot--off'}`} />
          {paused ? 'Sharing is paused. Nobody can see your position until you resume.'
            : sending ? (sentAgo == null ? 'Sharing is on. Waiting for your first position…' : `Sharing is on · last sent ${ageText(sentAgo)}${me?.accuracy ? ` · accurate to about ${Math.round(me.accuracy)} m` : ''}`)
            : 'Sharing is on, but this device is not sending. Resume or stop.'}</p>
      )}
      {t.can_share && sharing && !paused && awake && <p>Your screen is being kept on while you share, so your phone keeps reporting your position.</p>}
      {t.can_share && sharing && recording && <p>A route record is being kept, because you agreed to it when you started. It is deleted automatically after a limited time.</p>}
      {t.can_share && sharing && !paused && <p>Keep this page open{wakeLockSupported() ? '' : ' and your screen on'}. Phones may pause location updates when the screen is off or the browser is in the background; a web page cannot track reliably in the background.</p>}

      {!t.can_share && t.can_watch && (
        <p className="cbt-status" role="status">
          <span className={`cbt-dot ${!remote?.has_position ? 'cbt-dot--off' : remoteStale ? 'cbt-dot--stale' : ''}`} />
          {!remote ? 'Checking…' : remote.paused ? 'The volunteer has paused sharing for now.' : !remote.sharing ? 'The volunteer is not sharing a live location.' : !remote.has_position ? 'Waiting for the volunteer\u2019s first position.' : remoteStale ? `Last known position, ${ageText(remoteAge)}. The volunteer\u2019s device has not reported recently.` : `Live · updated ${ageText(remoteAge)}`}
        </p>
      )}
      {error && <div className="cbt-error" role="alert">{error}</div>}

      {markers.length > 0 && <TileMap markers={markers} height={300} ariaLabel="Delivery map" />}

      {showNav && (
        <div className="cbt-nav">
          {[['Pickup', pickup], ['Delivery', delivery]].filter(([, p]) => p).map(([name, p]) => {
            const links = navLinks(p.latitude, p.longitude, `${name}: ${p.label || 'destination'}`)
            const km = me ? haversineKm(me.lat, me.lon, p.latitude, p.longitude) : null
            return (
              <div className="cbt-dest" key={name}>
                <div><strong>{name}{p.label ? `: ${p.label}` : ''}</strong>
                  <span>{km != null ? `${formatDistance(km)} ${bearingLabel(me.lat, me.lon, p.latitude, p.longitude)} of you, in a straight line` : 'Start sharing, or open your maps app, for directions'}</span></div>
                <div className="cbt-links">
                  <a href={links.google} target="_blank" rel="noopener noreferrer">Navigate</a>
                  <a href={links.geo}>Open in maps app</a>
                  <a href={links.osm} target="_blank" rel="noopener noreferrer">OpenStreetMap</a>
                </div>
              </div>
            )
          })}
          <p>Directions open in your own maps app. CareBridge shows straight-line distance only; it does not calculate routes or arrival times.</p>
        </div>
      )}
      {missingPlace && <p>No map position is on file for the delivery place. Ask the organization to save its location in Settings, then Location. The address text above is still correct.</p>}
    </section>
  )
}

import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { Button, ConfirmDialog, ErrorState, Field, Pill, Skeleton, formatDate } from './ui.jsx'
import { IconPin, IconShield } from './icons.jsx'
import { describeAccuracy, describeGeoError, geolocationSupport, getCurrentPosition, isRoughReading, parseCoordinates, parseRadius } from '../lib/geo.js'

const INTRO = {
  organization: "Set where your organization is so donors and volunteers can see how far away your needs are.",
  donor: 'Share where you are to see needs near you. This is optional and you can remove it at any time.',
  volunteer: 'Share where you are and how far you can travel to see needs near you. This is optional and you can remove it at any time.'
}

/**
 * The person's own saved location. Nothing is read from the device until they press "Use my current location",
 * and nothing is sent to the server until they review the numbers and press Save.
 */
export default function LocationCard() {
  const { user } = useAuth()
  const toast = useToast()
  const role = user?.role
  const { data, loading, error, reload } = useAsync(() => api.getMyLocation(), [])
  const [lat, setLat] = useState('')
  const [lon, setLon] = useState('')
  const [label, setLabel] = useState('')
  const [radius, setRadius] = useState('')
  const [errors, setErrors] = useState({})
  const [reading, setReading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [readingNote, setReadingNote] = useState('')
  const support = geolocationSupport()

  useEffect(() => {
    if (!data) return
    setLat(data.latitude != null ? String(data.latitude) : '')
    setLon(data.longitude != null ? String(data.longitude) : '')
    setLabel(data.label || '')
    setRadius(data.service_radius_km != null ? String(data.service_radius_km) : '')
  }, [data])

  const useMyPosition = async () => {
    setReading(true); setReadingNote(''); setErrors({})
    try {
      const pos = await getCurrentPosition()
      setLat(pos.latitude.toFixed(6)); setLon(pos.longitude.toFixed(6))
      const quality = describeAccuracy(pos.accuracy)
      setReadingNote(isRoughReading(pos.accuracy)
        ? `Your device gave a rough position (${quality}). Check the numbers, or type a more exact place, then press Save.`
        : `Position found${quality ? ` (${quality})` : ''}. Check it, then press Save. Nothing is saved yet.`)
    } catch (e) {
      toast.error(describeGeoError(e))
    } finally { setReading(false) }
  }

  const save = async (e) => {
    e.preventDefault()
    const c = parseCoordinates(lat, lon)
    const r = role === 'volunteer' ? parseRadius(radius) : { ok: true, value: null }
    const next = { ...c.errors }
    if (!r.ok) next.radius = r.error
    setErrors(next)
    if (!c.ok || !r.ok) return
    setSaving(true)
    try {
      const body = { latitude: c.latitude, longitude: c.longitude }
      if (label.trim() !== (data?.label || '')) body.label = label.trim()
      if (role === 'volunteer' && r.value != null) body.service_radius_km = r.value
      await api.saveMyLocation(body)
      toast.success('Location saved.')
      setReadingNote('')
      reload({ silent: true })
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }

  const remove = async () => {
    setRemoving(true)
    try {
      await api.clearMyLocation(false)
      toast.success('Location removed. Other people can no longer see a distance to you.')
      setConfirmOpen(false); setReadingNote('')
      reload({ silent: true })
    } catch (err) { toast.error(err.message) } finally { setRemoving(false) }
  }

  if (loading && !data) return <div className="card space-y-3 p-5"><Skeleton className="h-5 w-1/3" /><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /></div>
  if (error && !data) return <ErrorState message={error} onRetry={reload} />

  const has = Boolean(data?.has_location)
  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-teal-50 text-teal-700"><IconPin className="h-5 w-5" /></span>
          <div>
            <h2 className="font-display text-base font-semibold text-ink">Your location</h2>
            <p className="mt-0.5 max-w-xl text-sm text-ink-muted">{INTRO[role] || INTRO.donor}</p>
          </div>
        </div>
        {has ? <Pill tone="green">Shared{data.updated_at ? ` · ${formatDate(data.updated_at)}` : ''}</Pill> : <Pill tone="gray">Not shared</Pill>}
      </div>

      <p className="mt-4 flex items-start gap-2 rounded-xl bg-teal-50/60 px-3 py-2.5 text-xs text-ink-muted">
        <IconShield className="mt-0.5 h-4 w-4 shrink-0 text-teal-700" />
        <span>Other people only ever see a rounded distance such as "within 5 km", never your coordinates or address. This is a saved position, not live tracking: CareBridge does not follow your device.</span>
      </p>

      <form onSubmit={save} className="mt-4 space-y-4" noValidate>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="soft" onClick={useMyPosition} loading={reading} disabled={!support.available}>
            <IconPin className="h-4 w-4" /> Use my current location
          </Button>
          {!support.available && <span className="text-xs text-ink-muted">{support.reason}</span>}
        </div>
        {readingNote && <p role="status" className="text-sm text-teal-800">{readingNote}</p>}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Latitude" error={errors.latitude} hint="Between -90 and 90"><input className="field" inputMode="decimal" autoComplete="off" value={lat} onChange={(e) => setLat(e.target.value)} placeholder="17.385" aria-invalid={Boolean(errors.latitude)} /></Field>
          <Field label="Longitude" error={errors.longitude} hint="Between -180 and 180"><input className="field" inputMode="decimal" autoComplete="off" value={lon} onChange={(e) => setLon(e.target.value)} placeholder="78.4867" aria-invalid={Boolean(errors.longitude)} /></Field>
        </div>
        <Field label={role === 'organization' ? 'Address or area name (optional)' : 'Area name (optional)'} hint="Shown to organizations that already work with you, like the existing location field."><input className="field" maxLength={200} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Banjara Hills, Hyderabad" /></Field>
        {role === 'volunteer' && (
          <Field label="How far can you travel? (km, optional)" error={errors.radius} hint="Needs outside this range are left out of your suggestions."><input className="field sm:max-w-[200px]" inputMode="decimal" value={radius} onChange={(e) => setRadius(e.target.value)} placeholder="15" aria-invalid={Boolean(errors.radius)} /></Field>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
          {has && <Button type="button" variant="danger" onClick={() => setConfirmOpen(true)}>Remove my location</Button>}
          <Button type="submit" loading={saving}>Save location</Button>
        </div>
      </form>

      <ConfirmDialog open={confirmOpen} title="Remove your location?" tone="danger" confirmLabel="Remove" loading={removing}
        text="Your saved coordinates (and travel range) will be deleted. You will stop appearing in nearby searches. The area name you typed stays unless you edit it." onConfirm={remove} onCancel={() => setConfirmOpen(false)} />
    </div>
  )
}

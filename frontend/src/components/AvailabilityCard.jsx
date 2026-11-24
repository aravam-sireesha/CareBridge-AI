import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { Button, ErrorState, Field, Pill, Skeleton } from './ui.jsx'
import { IconCalendar } from './icons.jsx'
import { MODE_LABEL, SHORT, TIMEZONES, WEEKDAYS, emptySlot, parseCapacity, slotProblems, summarize } from '../lib/availabilityUi.js'

/** A volunteer's weekly availability and carrying capacity. Nothing here is verified: it is what the volunteer says. */
export default function AvailabilityCard() {
  const toast = useToast()
  const { data, loading, error, reload } = useAsync(() => api.getAvailability(), [])
  const [slots, setSlots] = useState([])
  const [tz, setTz] = useState('Asia/Kolkata')
  const [mode, setMode] = useState('')
  const [capacity, setCapacity] = useState('')
  const [problems, setProblems] = useState([])
  const [capError, setCapError] = useState('')
  const [saving, setSaving] = useState(false)
  const [suggestion, setSuggestion] = useState(null)

  useEffect(() => {
    if (!data) return
    setSlots(data.slots || []); setTz(data.timezone || 'Asia/Kolkata'); setMode(data.transport_mode || ''); setCapacity(data.carry_capacity_kg != null ? String(data.carry_capacity_kg) : '')
  }, [data])

  const edit = (i, patch) => setSlots((list) => list.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  const suggest = async () => { try { setSuggestion(await api.suggestAvailability()) } catch (e) { toast.error(e.message) } }
  const useSuggestion = () => { setSlots(suggestion.slots); setSuggestion(null); toast.info('Filled in below. Check the times, then press Save.') }

  const save = async (e) => {
    e.preventDefault()
    const p = slotProblems(slots); const cap = parseCapacity(capacity)
    setProblems(p); setCapError(cap.ok ? '' : cap.error)
    if (p.length || !cap.ok) return
    setSaving(true)
    try {
      await api.saveAvailability({ slots, timezone: tz, transport_mode: mode || null, carry_capacity_kg: cap.value })
      toast.success('Availability saved.'); reload({ silent: true })
    } catch (err) { setProblems([err.message]) } finally { setSaving(false) }
  }

  if (loading && !data) return <div className="card space-y-3 p-5"><Skeleton className="h-5 w-1/3" /><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /></div>
  if (error && !data) return <ErrorState message={error} onRetry={reload} />

  return (
    <form onSubmit={save} className="card p-5" noValidate aria-labelledby="avail-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-teal-50 text-teal-700"><IconCalendar className="h-5 w-5" /></span>
          <div><h2 id="avail-title" className="font-display text-base font-semibold text-ink">Your availability</h2>
            <p className="mt-0.5 max-w-xl text-sm text-ink-muted">Tell organizations when you can collect and deliver. This is what you say, not something we have checked. It is used to suggest tasks that fit your week.</p></div>
        </div>
        <Pill tone={data?.has_schedule ? 'green' : 'gray'}>{data?.has_schedule ? 'Schedule saved' : 'Not set'}</Pill>
      </div>

      {data?.legacy_text && !data.has_schedule && (
        <div className="mt-4 rounded-xl bg-sky-50 p-3 text-sm text-sky-800">
          <p>Earlier you wrote: <strong>“{data.legacy_text}”</strong>. That text is not used for matching by itself.</p>
          {!suggestion ? <button type="button" onClick={suggest} className="mt-1 font-semibold underline">Suggest a schedule from this text</button>
            : <div className="mt-2" role="status">
              <p>{suggestion.note}</p>
              {suggestion.slots.length ? <><p className="mt-1 font-semibold">{summarize(suggestion.slots)}</p><button type="button" className="btn-soft mt-2" onClick={useSuggestion}>Use these times</button></> : null}
            </div>}
        </div>
      )}

      <fieldset className="mt-5"><legend className="text-sm font-semibold text-ink">Weekly time slots</legend>
        {slots.length === 0 && <p className="mt-2 text-sm text-ink-muted">No time slots yet. Add the hours you are usually free.</p>}
        <ul className="mt-2 space-y-2">
          {slots.map((s, i) => (
            <li key={i} className="flex flex-wrap items-end gap-2" data-slot={i}>
              <label className="text-xs font-semibold text-ink-muted">Day<select className="field mt-1" value={s.weekday} onChange={(e) => edit(i, { weekday: Number(e.target.value) })}>{WEEKDAYS.map((d, k) => <option key={k} value={k}>{d}</option>)}</select></label>
              <label className="text-xs font-semibold text-ink-muted">From<input className="field mt-1" type="time" value={s.start} onChange={(e) => edit(i, { start: e.target.value })} /></label>
              <label className="text-xs font-semibold text-ink-muted">To<input className="field mt-1" type="time" value={s.end} onChange={(e) => edit(i, { end: e.target.value })} /></label>
              <Button type="button" variant="ghost" onClick={() => setSlots((l) => l.filter((_, j) => j !== i))} aria-label={`Remove ${SHORT[s.weekday]} slot ${i + 1}`}>Remove</Button>
            </li>
          ))}
        </ul>
        <Button type="button" variant="soft" className="mt-3" onClick={() => setSlots((l) => [...l, emptySlot(l.length ? (l[l.length - 1].weekday + 1) % 7 : 5)])}>Add a time slot</Button>
      </fieldset>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Field label="Your timezone" hint={data?.timezone_is_default ? 'Using the platform default until you choose.' : ''}>
          <select className="field" value={tz} onChange={(e) => setTz(e.target.value)}>{[...new Set([tz, ...TIMEZONES])].map((z) => <option key={z} value={z}>{z}</option>)}</select>
        </Field>
        <Field label="How do you travel?"><select className="field" value={mode} onChange={(e) => setMode(e.target.value)}><option value="">Not stated</option>{Object.entries(MODE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
      </div>
      <div className="mt-4">
        <Field label="How much can you carry in one trip? (kg, optional)" error={capError} hint="The weight of donated items you can carry, not passenger seats. This is your own estimate and is not verified. If you leave it empty, you will not be ruled out for heavy deliveries, but organizations will see it was not stated.">
          <input className="field sm:max-w-[200px]" inputMode="decimal" value={capacity} onChange={(e) => setCapacity(e.target.value)} placeholder="40" aria-invalid={Boolean(capError)} />
        </Field>
      </div>

      {problems.length > 0 && <ul role="alert" className="mt-4 list-disc space-y-0.5 rounded-xl bg-red-50 p-3 pl-7 text-sm text-red-700">{problems.map((p, i) => <li key={i}>{p}</li>)}</ul>}
      <div className="mt-5 flex items-center justify-between gap-2">
        <p className="text-xs text-ink-muted">{summarize(slots)}</p>
        <Button type="submit" loading={saving}>Save availability</Button>
      </div>
    </form>
  )
}

import React, { useEffect, useMemo, useState } from 'react'
import Layout from '../components/Layout.jsx'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { openParam } from '../lib/openParam.js'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, Pill, Skeleton, StatCard, formatDate } from '../components/ui.jsx'
import { IconDonations, IconHand, IconPlus } from '../components/icons.jsx'
import LiveTracking from '../components/LiveTracking.jsx'
import { JOURNEY, RESOLUTIONS, STATUS_TONE, buildPayload, fieldFor, groupOf, journeyProgress } from '../lib/deliveryUi.js'

const TITLES = {
  organization: ['Deliveries', 'Arrange and follow deliveries from donors to your needs, and confirm what you receive.'],
  donor: ['My deliveries', 'Commit to approved deliveries and follow your gifts until they arrive.'],
  volunteer: ['My tasks', 'Delivery tasks offered to you. A task is yours only after you accept it.'],
  admin: ['Delivery approvals', 'Review proposed deliveries, and resolve problems that were reported.']
}
const TABS = [['action', 'Needs your action'], ['progress', 'In progress'], ['done', 'Finished'], ['all', 'All']]

function Journey({ status }) {
  const done = journeyProgress(status)
  if (done < 0) return null
  return (
    <ol className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Delivery progress">
      {JOURNEY.map((s, i) => (
        <li key={s.key} className={`flex items-center gap-1.5 ${i < done ? 'font-semibold text-green-700' : 'text-ink-muted'}`} aria-current={i === done - 1 ? 'step' : undefined}>
          <span className={`h-2 w-2 rounded-full ${i < done ? 'bg-green-600' : 'bg-line'}`} aria-hidden="true" />{s.label}
        </li>
      ))}
    </ol>
  )
}

function ProposeForm({ open, onClose, onCreated, preset }) {
  const toast = useToast()
  const needs = useAsync(() => (open ? api.listNeeds() : Promise.resolve([])), [open])
  const [needId, setNeedId] = useState(preset?.need || '')
  const [info, setInfo] = useState(null)
  const [donorId, setDonorId] = useState('')
  const [quantity, setQuantity] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const openNeeds = (needs.data || []).filter((n) => ['open', 'pending', null, undefined].includes(n.status))

  useEffect(() => {
    setInfo(null); setDonorId('')
    if (!needId) return
    api.deliveryCandidates(needId).then((r) => { setInfo(r); if (preset?.donor && String(needId) === String(preset.need) && r.donors.some((d) => String(d.id) === String(preset.donor))) setDonorId(String(preset.donor)) }).catch((e) => setError(e.message))
  }, [needId])  // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e) => {
    e.preventDefault(); setError('')
    const q = Number(quantity)
    if (!needId) return setError('Choose a need.')
    if (!donorId) return setError('Choose a donor.')
    if (!Number.isInteger(q) || q < 1) return setError('Enter a whole quantity of at least 1.')
    setSaving(true)
    try {
      const task = await api.proposeDelivery({ need_id: Number(needId), donor_id: Number(donorId), quantity: q, item_description: text.trim() || undefined })
      toast.success('Delivery proposed. Submit it for approval when you are ready.')
      setNeedId(''); setDonorId(''); setQuantity(''); setText(''); onCreated(task)
    } catch (err) { setError(err.message) } finally { setSaving(false) }
  }

  return (
    <Modal open={open} onClose={onClose} title="Propose a delivery" subtitle="Nothing is committed yet: the donor, an administrator and the volunteer each decide for themselves.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        <Field label="Need"><select className="field" value={needId} onChange={(e) => setNeedId(e.target.value)}>
          <option value="">Choose a need</option>{openNeeds.map((n) => <option key={n.id} value={n.id}>{n.title || n.category} ({n.quantity ?? '?'} needed)</option>)}</select></Field>
        {needId && !info && <Skeleton className="h-10 w-full" />}
        {info && (
          <>
            <p className="text-sm text-ink-muted">Still to arrange for this need: <strong className="text-ink">{info.remaining_quantity}</strong></p>
            <Field label="Donor" hint="Your own donors, plus donors recommended for this need.">
              <select className="field" value={donorId} onChange={(e) => setDonorId(e.target.value)}>
                <option value="">Choose a donor</option>{info.donors.map((d) => <option key={d.id} value={d.id}>{d.name}{d.recommended ? ' (recommended)' : ''}</option>)}</select>
            </Field>
            <Field label="Quantity" hint="Cannot be more than what is still to arrange."><input className="field sm:max-w-[160px]" inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></Field>
            <Field label="What is being given (optional)"><input className="field" maxLength={300} value={text} onChange={(e) => setText(e.target.value)} placeholder="Rice, 5 kg bags" /></Field>
          </>
        )}
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving} disabled={!info}>Propose delivery</Button></div>
      </form>
    </Modal>
  )
}

function Detail({ taskId, onClose, onChanged }) {
  const toast = useToast()
  const { data: task, loading, error, reload } = useAsync(() => (taskId ? api.getDelivery(taskId) : Promise.resolve(null)), [taskId])
  const [pending, setPending] = useState(null)       // the action being filled in
  const [values, setValues] = useState({})
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [helpers, setHelpers] = useState([])

  useEffect(() => { setPending(null); setValues({}); setErrors({}) }, [taskId])
  useEffect(() => {
    if (pending?.action === 'offer' && task) api.deliveryCandidates(task.need.id).then((r) => setHelpers(r.volunteers)).catch(() => setHelpers([]))
  }, [pending, task])

  const start = (a) => {
    setErrors({}); setValues({ __expected: task.quantity })
    if (!a.fields.length) return run(a, {})
    setPending(a)
  }
  const run = async (a, payload) => {
    setBusy(true)
    try { await api.deliveryAction(task.id, a.action, payload); toast.success(`${a.label}: done.`); setPending(null); await reload({ silent: true }); onChanged() }
    catch (err) { toast.error(err.message) } finally { setBusy(false) }
  }
  const send = (e) => {
    e.preventDefault()
    const built = buildPayload(pending.action, pending.fields, values)
    setErrors(built.errors)
    if (built.ok) run(pending, built.payload)
  }
  const set = (k) => (e) => setValues((v) => ({ ...v, [k]: e.target.value }))

  return (
    <Modal open={Boolean(taskId)} onClose={onClose} wide title={task ? `Delivery #${task.id}` : 'Delivery'} subtitle={task ? `${task.need.title || task.need.category} · ${task.organization.name}` : ''}>
      {loading && !task ? <Skeleton className="h-40 w-full" /> : error && !task ? <ErrorState message={error} onRetry={reload} /> : task && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={STATUS_TONE[task.status] || 'gray'}>{task.status_label}</Pill>
            {task.quantity_mismatch && <Pill tone="amber">Quantity differs from the plan</Pill>}
          </div>
          <Journey status={task.status} />

          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <div><dt className="text-xs text-ink-muted">Quantity planned</dt><dd className="font-semibold text-ink">{task.quantity}{task.item_description ? ` · ${task.item_description}` : ''}</dd></div>
            {task.received_quantity != null && <div><dt className="text-xs text-ink-muted">Quantity received</dt><dd className="font-semibold text-ink">{task.received_quantity}</dd></div>}
            {task.donor && <div><dt className="text-xs text-ink-muted">Donor</dt><dd className="text-ink">{task.donor.name}</dd></div>}
            {task.volunteer && <div><dt className="text-xs text-ink-muted">Volunteer</dt><dd className="text-ink">{task.volunteer.name}</dd></div>}
            {task.pickup_at && <div><dt className="text-xs text-ink-muted">Pickup</dt><dd className="text-ink">{formatDate(task.pickup_at)}</dd></div>}
            {task.addresses_visible.pickup && <div><dt className="text-xs text-ink-muted">Pickup place</dt><dd className="text-ink">{task.pickup_area || 'Not provided'}</dd></div>}
            {task.addresses_visible.delivery && <div><dt className="text-xs text-ink-muted">Delivery place</dt><dd className="text-ink">{task.delivery_area || 'Not provided'}</dd></div>}
          </dl>
          {!task.addresses_visible.pickup && task.status === 'offered' && <p className="rounded-xl bg-sky-50 p-3 text-xs text-sky-800">Pickup and delivery places are shown after you accept this task.</p>}
          {[['Decision', task.decision_reason], ['Problem reported', task.exception_reason], ['Cancelled because', task.cancel_reason], ['Proof of delivery', task.delivery_note], ['Receipt note', task.receipt_note]].filter(([, v]) => v).map(([k, v]) => (
            <p key={k} className="rounded-xl bg-bg p-3 text-sm"><span className="font-semibold text-ink">{k}: </span><span className="text-ink-muted">{v}</span></p>
          ))}

          <LiveTracking key={task.id} task={task} onChanged={() => reload({ silent: true })} />

          {task.allowed_actions.length > 0 && !pending && (
            <div className="flex flex-wrap gap-2 border-t border-line pt-4" role="group" aria-label="What you can do now">
              {task.allowed_actions.map((a) => <Button key={a.action} variant={a.tone === 'danger' ? 'danger' : a.tone === 'secondary' ? 'ghost' : 'primary'} disabled={busy} loading={busy && pending?.action === a.action} onClick={() => start(a)}>{a.label}</Button>)}
            </div>
          )}

          {pending && (
            <form onSubmit={send} className="space-y-4 rounded-2xl border border-line p-4" noValidate>
              <h3 className="font-display text-base font-semibold text-ink">{pending.label}</h3>
              {pending.fields.map((f) => {
                const meta = fieldFor(pending.action, f)
                return (
                  <Field key={f} label={meta.label} hint={meta.hint} error={errors[f]}>
                    {meta.type === 'textarea' ? <textarea className="field min-h-[84px]" maxLength={500} value={values[f] || ''} onChange={set(f)} />
                      : meta.type === 'volunteer' ? <select className="field" value={values[f] || ''} onChange={set(f)}><option value="">Choose a volunteer</option>{helpers.map((v) => <option key={v.id} value={v.id}>{v.name}{v.recommended ? ' (recommended)' : ''}</option>)}</select>
                      : meta.type === 'resolution' ? <select className="field" value={values[f] || ''} onChange={set(f)}><option value="">Choose</option>{RESOLUTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select>
                      : meta.type === 'number' ? <input className="field sm:max-w-[200px]" inputMode="numeric" value={values[f] ?? ''} onChange={set(f)} />
                      : <input className="field sm:max-w-[260px]" type={meta.type} value={values[f] || ''} onChange={set(f)} />}
                  </Field>
                )
              })}
              {pending.action === 'confirm_receipt' && <Field label="Note" hint="Required if the quantity differs from the plan." error={errors.note}><textarea className="field min-h-[72px]" maxLength={500} value={values.note || ''} onChange={set('note')} /></Field>}
              <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setPending(null)}>Back</Button><Button type="submit" variant={pending.tone === 'danger' ? 'danger' : 'primary'} loading={busy}>{pending.label}</Button></div>
            </form>
          )}

          <div>
            <h3 className="mb-2 text-sm font-semibold text-ink">History</h3>
            <ol className="space-y-2 border-l-2 border-line pl-4">
              {task.events.map((e, i) => (
                <li key={i} className="text-sm"><span className="font-medium text-ink">{e.to.replace(/_/g, ' ')}</span> <span className="text-ink-muted">· {e.actor_role} · {formatDate(e.at)}</span>
                  {e.note && <p className="text-xs text-ink-muted">{e.note}</p>}</li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </Modal>
  )
}

export default function Deliveries() {
  const { user } = useAuth()
  const list = useAsync(() => api.listDeliveries(), [])
  const impact = useAsync(() => api.deliveryImpact(), [])
  const [tab, setTab] = useState('action')
  const [openId, setOpenId] = useState(() => { const v = Number(openParam()); return Number.isInteger(v) && v > 0 ? v : null })
  const preset = useMemo(() => { try { const q = new URLSearchParams(window.location.search); return q.get('propose') === '1' ? { need: q.get('need') || '', donor: q.get('donor') || '' } : null } catch { return null } }, [])
  const [proposing, setProposing] = useState(() => Boolean(preset) && (user.role === 'organization' || user.role === 'admin'))
  const [title, subtitle] = TITLES[user.role] || TITLES.organization
  const canPropose = user.role === 'organization' || user.role === 'admin'

  const tasks = list.data || []
  const counts = useMemo(() => tasks.reduce((c, t) => { const g = groupOf(t); c[g] += 1; c.all += 1; return c }, { action: 0, progress: 0, done: 0, all: 0 }), [tasks])
  const shown = tab === 'all' ? tasks : tasks.filter((t) => groupOf(t) === tab)
  useEffect(() => { if (list.data && counts.action === 0 && tab === 'action') setTab(counts.progress ? 'progress' : 'all') }, [list.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const refresh = () => { list.reload({ silent: true }); impact.reload({ silent: true }) }
  const q = impact.data?.quantities

  return (
    <Layout title={title}>
      <PageHeader icon={IconDonations} title={title} subtitle={subtitle}
        actions={canPropose && <Button variant="ghost" className="border-white/40 bg-white/95" onClick={() => setProposing(true)}><IconPlus className="h-4 w-4" /> Propose a delivery</Button>} />

      <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Planned or committed" value={q ? q.planned + q.committed : '–'} icon={IconHand} tone="sky" hint="Not yet accepted by a volunteer" />
        <StatCard label="On the way" value={q ? q.in_progress : '–'} icon={IconHand} tone="teal" hint="Accepted through in transit" />
        <StatCard label="Delivered, not confirmed" value={q ? q.delivered : '–'} icon={IconHand} tone="amber" hint="Waiting for the organization" />
        <StatCard label="Receipt confirmed" value={q ? q.confirmed : '–'} icon={IconDonations} tone="green" hint="What organizations actually received" />
      </div>

      <div className="mt-6 flex flex-wrap gap-2" role="tablist" aria-label="Deliveries">
        {TABS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
            className={`rounded-full border px-3.5 py-1.5 text-sm font-semibold transition ${tab === key ? 'border-teal-700 bg-teal-700 text-white' : 'border-line bg-white text-ink-muted hover:border-teal-300'}`}>
            {label} <span className="ml-1 text-xs opacity-80">{counts[key]}</span>
          </button>
        ))}
      </div>

      <div className="mt-4">
        {list.loading && !list.data ? <div className="space-y-3"><Skeleton className="h-20 w-full" /><Skeleton className="h-20 w-full" /></div>
          : list.error && !list.data ? <ErrorState message={list.error} onRetry={list.reload} />
          : shown.length === 0 ? (
            <div className="card p-2"><EmptyState icon={IconDonations} title={tasks.length === 0 ? 'No deliveries yet' : 'Nothing here'}
              text={tasks.length === 0 ? (canPropose ? 'Propose a delivery to connect a donor with one of your needs.' : 'Deliveries you are part of will appear here.') : 'Try another tab.'}
              action={tasks.length === 0 && canPropose ? <Button onClick={() => setProposing(true)}><IconPlus className="h-4 w-4" /> Propose a delivery</Button> : null} /></div>
          ) : (
            <ul className="space-y-3">
              {shown.map((t) => (
                <li key={t.id}>
                  <button type="button" onClick={() => setOpenId(t.id)} className="card card-hover w-full p-4 text-left">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-ink">{t.need.title || t.need.category} <span className="font-normal text-ink-muted">· {t.quantity}{t.item_description ? ` · ${t.item_description}` : ''}</span></p>
                        <p className="text-xs text-ink-muted">{t.organization.name}{t.donor ? ` · from ${t.donor.name}` : ''}{t.volunteer ? ` · ${t.volunteer.name}` : ''} · updated {formatDate(t.updated_at)}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        {t.allowed_actions.length > 0 && groupOf(t) === 'action' && <Pill tone="amber">Your turn</Pill>}
                        <Pill tone={STATUS_TONE[t.status] || 'gray'}>{t.status_label}</Pill>
                      </div>
                    </div>
                    <div className="mt-3"><Journey status={t.status} /></div>
                  </button>
                </li>
              ))}
            </ul>
          )}
      </div>

      <ProposeForm preset={preset} open={proposing} onClose={() => setProposing(false)} onCreated={(t) => { setProposing(false); refresh(); setOpenId(t.id) }} />
      <Detail taskId={openId} onClose={() => setOpenId(null)} onChanged={refresh} />
    </Layout>
  )
}

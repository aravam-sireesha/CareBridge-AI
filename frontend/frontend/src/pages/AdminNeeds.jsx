import React, { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { LevelPill, ScoreBar, SuggestionCard } from '../components/AdminParts.jsx'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, TableSkeleton, formatDate } from '../components/ui.jsx'
import { IconEdit, IconNeeds, IconPlus, IconSpark, IconTrash } from '../components/icons.jsx'

const URGENCY = ['critical', 'high', 'medium', 'low']
const STATUSES = ['open', 'pending', 'fulfilled', 'closed']

function AddNeedModal({ open, onClose, orgs, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState({ org_id: '', category: '', quantity: 1, urgency: 'medium' })
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (open && !f.org_id && orgs.length) setF((p) => ({ ...p, org_id: String(orgs[0].id) })) }, [open, orgs, f.org_id])
  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try { await api.createNeed({ org_id: Number(f.org_id), category: f.category.trim(), quantity: Number(f.quantity), urgency: f.urgency }); toast.success('Need added.'); setF((p) => ({ ...p, category: '', quantity: 1 })); onSaved(); onClose() }
    catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  return (
    <Modal open={open} onClose={onClose} title="Add a need for an organization" subtitle="Needs you add here are saved to the organization's list.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Organization"><select className="field" required value={f.org_id} onChange={(e) => setF({ ...f, org_id: e.target.value })}>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
        <Field label="Category"><input className="field" required maxLength={200} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} placeholder="School supplies" /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Quantity"><input className="field" type="number" min={0} required value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></Field>
          <Field label="Urgency"><select className="field capitalize" value={f.urgency} onChange={(e) => setF({ ...f, urgency: e.target.value })}>{URGENCY.map((u) => <option key={u}>{u}</option>)}</select></Field>
        </div>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving} disabled={!f.org_id || !f.category.trim()}>Add need</Button></div>
      </form>
    </Modal>
  )
}

function EditNeedModal({ need, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState({ category: '', quantity: 0, urgency: 'medium', status: 'open' })
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (need) setF({ category: need.category || '', quantity: need.quantity ?? 0, urgency: need.urgency || 'medium', status: need.status || 'open' }) }, [need])
  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try { await api.updateNeed(need.id, { category: f.category.trim(), quantity: Number(f.quantity), urgency: f.urgency, status: f.status }); toast.success('Need updated.'); onSaved(); onClose() }
    catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  return (
    <Modal open={!!need} onClose={onClose} title="Edit need" subtitle={need ? `${need.organization_name || 'Organization'} · AI priority is recalculated after saving.` : ''}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Category"><input className="field" required maxLength={200} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} /></Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Quantity"><input className="field" type="number" min={0} required value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></Field>
          <Field label="Urgency"><select className="field capitalize" value={f.urgency} onChange={(e) => setF({ ...f, urgency: e.target.value })}>{URGENCY.map((u) => <option key={u}>{u}</option>)}</select></Field>
          <Field label="Status"><select className="field capitalize" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>{STATUSES.map((u) => <option key={u}>{u}</option>)}</select></Field>
        </div>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving} disabled={!f.category.trim()}>Save changes</Button></div>
      </form>
    </Modal>
  )
}

function SuggestModal({ need, onClose, onChanged }) {
  const toast = useToast()
  const [state, setState] = useState({ loading: true, error: '', data: null })
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!need) return
    let alive = true
    setState({ loading: true, error: '', data: null })
    api.adminSuggestDonors(need.id, 5).then((data) => alive && setState({ loading: false, error: '', data })).catch((e) => alive && setState({ loading: false, error: e.message, data: null }))
    return () => { alive = false }
  }, [need])
  const decide = async (s, decision) => {
    setBusy(true)
    try { await api.adminReviewSuggestion(s.id, decision); setState((p) => ({ ...p, data: { ...p.data, suggestions: p.data.suggestions.map((x) => (x.id === s.id ? { ...x, status: decision } : x)) } })); toast.success(`Suggestion ${decision}.`); onChanged() }
    catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  const list = state.data?.suggestions || []
  return (
    <Modal open={!!need} onClose={onClose} wide title={need ? `Suggested donors for ${need.category}` : ''} subtitle={need ? `${need.organization_name || 'Organization'} · ${need.urgency} urgency · AI priority ${Math.round(need.priority_score * 100)}%` : ''}>
      {state.loading && <TableSkeleton rows={3} cols={2} />}
      {state.error && <ErrorState message={state.error} />}
      {!state.loading && !state.error && list.length === 0 && <EmptyState icon={IconSpark} title="No suitable donor found" text="No donor's interests or giving history connect to this need yet. Add donors or broaden their interests." />}
      <div className="space-y-3">{list.map((s) => <SuggestionCard key={s.id} s={s} busy={busy} showNeed={false} onDecide={decide} />)}</div>
    </Modal>
  )
}

export default function AdminNeeds() {
  const [params, setParams] = useSearchParams()
  const [filters, setFilters] = useState({ status: params.get('status') || '', urgency: '', organization_id: '' })
  const query = useMemo(() => {
    const q = new URLSearchParams()
    Object.entries(filters).forEach(([k, v]) => v && q.set(k, v))
    const s = q.toString()
    return s ? `?${s}` : ''
  }, [filters])
  const needs = useAsync(() => api.adminNeeds(query), [query])
  const orgs = useAsync(() => api.adminOrganizations(), [])
  const toast = useToast()
  const [adding, setAdding] = useState(false)
  const [target, setTarget] = useState(null)
  const [editing, setEditing] = useState(null)
  const remove = async (n) => {
    if (!window.confirm(`Delete the need "${n.category}"? Needs with donations cannot be deleted; close them instead.`)) return
    try { await api.adminDeleteNeed(n.id); toast.success('Need deleted.'); needs.reload({ silent: true }) } catch (e) { toast.error(e.message) }
  }

  const setStatus = async (n, status) => {
    try { await api.updateNeed(n.id, { status }); toast.success('Status updated.'); needs.reload({ silent: true }) } catch (e) { toast.error(e.message) }
  }
  const setUrgency = async (n, urgency) => {
    try { await api.updateNeed(n.id, { urgency }); toast.success('Urgency updated; the AI priority was recalculated.'); needs.reload({ silent: true }) } catch (e) { toast.error(e.message) }
  }
  const setF = (k) => (e) => { setFilters((p) => ({ ...p, [k]: e.target.value })); if (k === 'status') setParams(e.target.value ? { status: e.target.value } : {}) }
  const rows = needs.data || []

  return (
    <Layout title="All needs">
      <PageHeader icon={IconNeeds} tone="amber" title="All organization needs" subtitle="Ranked by AI priority: urgency level, time open and size of the request."
        actions={<Button variant="ghost" onClick={() => setAdding(true)} className="!border-white/40 !bg-white/15 !text-white hover:!bg-white/25"><IconPlus className="h-4 w-4" /> Add need</Button>} />
      <div className="card mb-5 grid gap-3 p-4 sm:grid-cols-3">
        <Field label="Status"><select className="field capitalize" value={filters.status} onChange={setF('status')}><option value="">All</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Urgency"><select className="field capitalize" value={filters.urgency} onChange={setF('urgency')}><option value="">All</option>{URGENCY.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Organization"><select className="field" value={filters.organization_id} onChange={setF('organization_id')}><option value="">All</option>{(orgs.data || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
      </div>
      {needs.error ? <ErrorState message={needs.error} onRetry={needs.reload} /> : needs.loading ? <TableSkeleton rows={5} cols={5} /> : rows.length === 0 ? (
        <EmptyState icon={IconNeeds} title="No needs match" text="Change the filters or add a need for an organization." />
      ) : (
        <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[860px] text-sm">
          <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-3">Need</th><th className="px-4 py-3">Organization</th><th className="w-44 px-4 py-3">AI priority</th><th className="px-4 py-3">Urgency</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Donors</th></tr></thead>
          <tbody>{rows.map((n) => (
            <tr key={n.id} className="border-b border-line align-top last:border-0 hover:bg-teal-50/40">
              <td className="px-4 py-3.5"><p className="font-semibold text-ink">{n.category || `Need ${n.id}`}</p><p className="text-xs text-ink-muted">Qty {n.quantity ?? '–'} · added {formatDate(n.created_at)}</p></td>
              <td className="px-4 py-3.5"><p className="text-ink">{n.organization_name || '–'}</p><StatusBadge status={n.organization_verified ? 'verified' : 'unverified'} /></td>
              <td className="px-4 py-3.5"><div className="mb-1"><LevelPill level={n.priority_level} /></div><ScoreBar label="Score" value={n.priority_score} tone="rose" /></td>
              <td className="px-4 py-3.5"><select aria-label="Urgency" value={n.urgency || 'medium'} onChange={(e) => setUrgency(n, e.target.value)} className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold capitalize">{URGENCY.map((u) => <option key={u}>{u}</option>)}</select></td>
              <td className="px-4 py-3.5"><select aria-label="Status" value={n.status || 'open'} onChange={(e) => setStatus(n, e.target.value)} className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold capitalize">{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></td>
              <td className="px-4 py-3.5 text-right"><div className="flex flex-wrap justify-end gap-1.5">{n.is_open ? <Button variant="soft" className="px-3 py-1.5 text-xs" onClick={() => setTarget(n)}><IconSpark className="h-3.5 w-3.5" />{n.suggestion_count ? `${n.suggestion_count} suggested` : 'Suggest donors'}</Button> : <span className="self-center text-xs text-ink-muted">Closed</span>}<Button variant="ghost" className="px-2.5 py-1.5 text-xs" aria-label={`Edit ${n.category}`} onClick={() => setEditing(n)}><IconEdit className="h-3.5 w-3.5" /></Button><Button variant="danger" className="px-2.5 py-1.5 text-xs" aria-label={`Delete ${n.category}`} onClick={() => remove(n)}><IconTrash className="h-3.5 w-3.5" /></Button></div></td>
            </tr>))}</tbody></table></div></div>
      )}
      <AddNeedModal open={adding} onClose={() => setAdding(false)} orgs={orgs.data || []} onSaved={() => needs.reload({ silent: true })} />
      <EditNeedModal need={editing} onClose={() => setEditing(null)} onSaved={() => needs.reload({ silent: true })} />
      <SuggestModal need={target} onClose={() => setTarget(null)} onChanged={() => needs.reload({ silent: true })} />
    </Layout>
  )
}

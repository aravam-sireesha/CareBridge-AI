import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { LevelPill, Reasons, ScoreBar } from '../components/AdminParts.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, Pill, TableSkeleton, formatDate } from '../components/ui.jsx'
import { IconEdit, IconPeople, IconPlus, IconSearch, IconTrash } from '../components/icons.jsx'

const blank = { name: '', contact: '', skills: '', availability: '', location: '', organization_id: '' }

function VolunteerForm({ open, volunteer, orgs, onClose, onSaved }) {
  const toast = useToast()
  const [f, setF] = useState(blank)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (open) setF(volunteer ? { name: volunteer.name || '', contact: volunteer.contact || '', skills: volunteer.skills || '', availability: volunteer.availability || '', location: volunteer.location || '', organization_id: volunteer.organization_id ? String(volunteer.organization_id) : '' } : blank)
  }, [open, volunteer])
  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    const body = { name: f.name.trim(), contact: f.contact.trim() || null, skills: f.skills.trim() || null, availability: f.availability.trim() || null, location: f.location.trim() || null }
    try {
      if (volunteer) await api.adminUpdateVolunteer(volunteer.id, { ...body, ...(f.organization_id ? { organization_id: Number(f.organization_id) } : { clear_organization: true }) })
      else await api.adminCreateVolunteer({ ...body, organization_id: f.organization_id ? Number(f.organization_id) : null })
      toast.success(volunteer ? 'Volunteer updated.' : 'Volunteer added.'); onSaved(); onClose()
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  return (
    <Modal open={open} onClose={onClose} title={volunteer ? 'Edit volunteer' : 'Add a volunteer'} subtitle="Skills and availability drive the AI volunteer suggestions, so list what this person can do and when.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name"><input className="field" required maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Contact"><input className="field" maxLength={200} value={f.contact} onChange={(e) => setF({ ...f, contact: e.target.value })} placeholder="Email or phone" /></Field>
          <Field label="Location"><input className="field" maxLength={200} value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        </div>
        <Field label="Skills" hint="Comma separated, e.g. teaching, cooking, first aid"><input className="field" maxLength={2000} value={f.skills} onChange={(e) => setF({ ...f, skills: e.target.value })} /></Field>
        <Field label="Availability" hint="For example weekends, evenings, full time"><input className="field" maxLength={200} value={f.availability} onChange={(e) => setF({ ...f, availability: e.target.value })} /></Field>
        <Field label="Organization" hint="Optional. Volunteers already in an organization are suggested for its needs first."><select className="field" value={f.organization_id} onChange={(e) => setF({ ...f, organization_id: e.target.value })}><option value="">None (platform volunteer)</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving} disabled={!f.name.trim()}>{volunteer ? 'Save changes' : 'Add volunteer'}</Button></div>
      </form>
    </Modal>
  )
}

function VolunteerDetail({ id, onClose }) {
  const [state, setState] = useState({ loading: true, error: '', data: null })
  useEffect(() => {
    if (!id) return undefined
    let alive = true
    setState({ loading: true, error: '', data: null })
    api.adminVolunteer(id).then((data) => alive && setState({ loading: false, error: '', data })).catch((e) => alive && setState({ loading: false, error: e.message, data: null }))
    return () => { alive = false }
  }, [id])
  const v = state.data
  return (
    <Modal open={!!id} onClose={onClose} wide title={v ? v.name : 'Volunteer'} subtitle={v ? `${v.organization_name || 'Platform volunteer'}${v.account_email ? ` · account ${v.account_email}` : ''}` : ''}>
      {state.loading && <TableSkeleton rows={3} cols={2} />}
      {state.error && <ErrorState message={state.error} />}
      {v && (
        <div className="space-y-5">
          <p className="text-sm text-ink-muted"><strong className="text-ink">Skills:</strong> {v.skills || 'not recorded'} · <strong className="text-ink">Available:</strong> {v.availability || 'not stated'}{v.location ? ` · ${v.location}` : ''}{v.contact ? ` · ${v.contact}` : ''}</p>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Open needs that suit this volunteer</p>
            {v.recommended_needs.length === 0 ? <p className="text-sm text-ink-muted">No open need matches this volunteer's skills yet.</p> : (
              <div className="space-y-2.5">{v.recommended_needs.map((n) => (
                <div key={n.need_id} className="card p-3.5">
                  <div className="flex items-start justify-between gap-2"><div><p className="text-sm font-semibold text-ink">{n.category}</p><p className="text-xs text-ink-muted">{n.organization_name} · qty {n.quantity ?? '–'}</p></div><LevelPill level={n.urgency} /></div>
                  <div className="mt-2 grid gap-3 sm:grid-cols-2"><ScoreBar label="Volunteer fit" value={n.fit_score} /><ScoreBar label="Priority" value={n.priority_score} tone="rose" /></div>
                  <Reasons items={n.reasons.slice(0, 3)} />
                </div>))}</div>)}
          </div>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Matches so far</p>
            {v.matches_history.length === 0 ? <p className="text-sm text-ink-muted">No matches recorded.</p> : (
              <ul className="divide-y divide-line rounded-xl border border-line">{v.matches_history.map((m) => <li key={m.id} className="flex items-center justify-between gap-3 px-3.5 py-2.5 text-sm"><span className="font-semibold text-ink">{m.need_category || 'Need'}</span><span className="flex items-center gap-2 text-xs text-ink-muted"><StatusBadge status={m.status} />{formatDate(m.created_at)}</span></li>)}</ul>)}
          </div>
        </div>
      )}
    </Modal>
  )
}

export default function AdminVolunteers() {
  const toast = useToast()
  const [orgFilter, setOrgFilter] = useState('')
  const [search, setSearch] = useState('')
  const list = useAsync(() => api.adminVolunteers(orgFilter), [orgFilter])
  const orgs = useAsync(() => api.adminOrganizations(), [])
  const [editing, setEditing] = useState(undefined)
  const [viewing, setViewing] = useState(null)
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (list.data || []).filter((v) => !q || [v.name, v.contact, v.skills, v.availability, v.location, v.organization_name].some((x) => (x || '').toLowerCase().includes(q)))
  }, [list.data, search])
  const remove = async (v) => {
    if (!window.confirm(`Delete volunteer "${v.name}"? This cannot be undone.`)) return
    try { await api.adminDeleteVolunteer(v.id); toast.success('Volunteer deleted.'); list.reload({ silent: true }) } catch (e) { toast.error(e.message) }
  }
  return (
    <Layout title="All volunteers">
      <PageHeader icon={IconPeople} tone="sky" title="Volunteers of all organizations" subtitle={`${(list.data || []).length} volunteer(s). Open one to see the open needs that suit their skills and availability.`}
        actions={<Button variant="ghost" onClick={() => setEditing(null)} className="!border-white/40 !bg-white/15 !text-white hover:!bg-white/25"><IconPlus className="h-4 w-4" /> Add volunteer</Button>} />
      <div className="card mb-5 grid gap-3 p-4 sm:grid-cols-[1fr_16rem]">
        <Field label="Search"><div className="relative"><IconSearch className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" /><input className="field pl-10" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, skill, availability, organization" aria-label="Search volunteers" /></div></Field>
        <Field label="Organization"><select className="field" value={orgFilter} onChange={(e) => setOrgFilter(e.target.value)}><option value="">All organizations</option>{(orgs.data || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
      </div>
      {list.error ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading ? <TableSkeleton rows={5} cols={5} /> : rows.length === 0 ? (
        <EmptyState icon={IconPeople} title="No volunteers found" text="Add a volunteer, or change the search and organization filter." />
      ) : (
        <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[820px] text-sm">
          <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-3">Volunteer</th><th className="px-4 py-3">Skills</th><th className="px-4 py-3">Availability</th><th className="px-4 py-3">Organization</th><th className="px-4 py-3 text-right">Actions</th></tr></thead>
          <tbody>{rows.map((v) => (
            <tr key={v.id} className="border-b border-line align-top last:border-0 hover:bg-teal-50/40">
              <td className="px-4 py-3.5"><button className="text-left font-semibold text-ink hover:text-teal-700" onClick={() => setViewing(v.id)}>{v.name}</button><p className="text-xs text-ink-muted">{v.contact || 'No contact'}{v.location ? ` · ${v.location}` : ''}</p>{v.account_email && <Pill tone="sky" className="mt-1">has account</Pill>}</td>
              <td className="px-4 py-3.5 text-ink-muted">{v.skills || '–'}</td>
              <td className="px-4 py-3.5 text-ink-muted">{v.availability || <span className="text-amber-700">not stated</span>}</td>
              <td className="px-4 py-3.5 text-ink-muted">{v.organization_name || 'Platform volunteer'}<p className="text-xs">{v.matches} match(es){v.pending_suggestions > 0 ? ` · ${v.pending_suggestions} AI suggestion(s)` : ''}</p></td>
              <td className="px-4 py-3.5 text-right"><div className="flex justify-end gap-1.5"><Button variant="soft" className="px-3 py-1.5 text-xs" onClick={() => setViewing(v.id)}>View</Button><Button variant="ghost" className="px-2.5 py-1.5 text-xs" aria-label={`Edit ${v.name}`} onClick={() => setEditing(v)}><IconEdit className="h-3.5 w-3.5" /></Button><Button variant="danger" className="px-2.5 py-1.5 text-xs" aria-label={`Delete ${v.name}`} onClick={() => remove(v)}><IconTrash className="h-3.5 w-3.5" /></Button></div></td>
            </tr>))}</tbody></table></div></div>
      )}
      <VolunteerForm open={editing !== undefined} volunteer={editing || null} orgs={orgs.data || []} onClose={() => setEditing(undefined)} onSaved={() => list.reload({ silent: true })} />
      <VolunteerDetail id={viewing} onClose={() => setViewing(null)} />
    </Layout>
  )
}

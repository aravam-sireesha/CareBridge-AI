import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { LevelPill, Reasons, ScoreBar } from '../components/AdminParts.jsx'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, Pill, TableSkeleton, formatDate } from '../components/ui.jsx'
import { IconDonations, IconEdit, IconPlus, IconSearch, IconTrash } from '../components/icons.jsx'

const money = (n) => Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })

function DonorForm({ open, donor, orgs, onClose, onSaved }) {
  const toast = useToast()
  const blank = { name: '', contact: '', preferences: '', location: '', organization_id: '' }
  const [f, setF] = useState(blank)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (open) setF(donor ? { name: donor.name || '', contact: donor.contact || '', preferences: donor.preferences || '', location: donor.location || '', organization_id: donor.organization_id ? String(donor.organization_id) : '' } : blank)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, donor])
  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    const body = { name: f.name.trim(), contact: f.contact.trim() || null, preferences: f.preferences.trim() || null, location: f.location.trim() || null }
    try {
      if (donor) await api.adminUpdateDonor(donor.id, { ...body, ...(f.organization_id ? { organization_id: Number(f.organization_id) } : { clear_organization: true }) })
      else await api.adminCreateDonor({ ...body, organization_id: f.organization_id ? Number(f.organization_id) : null })
      toast.success(donor ? 'Donor updated.' : 'Donor added.'); onSaved(); onClose()
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }
  return (
    <Modal open={open} onClose={onClose} title={donor ? 'Edit donor' : 'Add a donor'} subtitle="Interests drive the AI donor suggestions, so list what this donor likes to support.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name"><input className="field" required maxLength={200} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Contact"><input className="field" maxLength={200} value={f.contact} onChange={(e) => setF({ ...f, contact: e.target.value })} placeholder="Email or phone" /></Field>
          <Field label="Location"><input className="field" maxLength={200} value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        </div>
        <Field label="Interests" hint="Comma separated, e.g. education, food, medicine"><input className="field" maxLength={1000} value={f.preferences} onChange={(e) => setF({ ...f, preferences: e.target.value })} /></Field>
        <Field label="Linked organization" hint="Optional. Linked organizations can see this donor by name."><select className="field" value={f.organization_id} onChange={(e) => setF({ ...f, organization_id: e.target.value })}><option value="">None (platform donor)</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={saving} disabled={!f.name.trim()}>{donor ? 'Save changes' : 'Add donor'}</Button></div>
      </form>
    </Modal>
  )
}

function DonorDetail({ id, onClose }) {
  const [state, setState] = useState({ loading: true, error: '', data: null })
  useEffect(() => {
    if (!id) return undefined
    let alive = true
    setState({ loading: true, error: '', data: null })
    api.adminDonor(id).then((data) => alive && setState({ loading: false, error: '', data })).catch((e) => alive && setState({ loading: false, error: e.message, data: null }))
    return () => { alive = false }
  }, [id])
  const d = state.data
  return (
    <Modal open={!!id} onClose={onClose} wide title={d ? d.name : 'Donor'} subtitle={d ? `${d.organization_name || 'Platform donor'}${d.account_email ? ` · account ${d.account_email}` : ''}` : ''}>
      {state.loading && <TableSkeleton rows={3} cols={2} />}
      {state.error && <ErrorState message={state.error} />}
      {d && (
        <div className="space-y-5">
          <div className="grid grid-cols-3 gap-3 text-center">{[['Gifts', d.gifts], ['Total given', money(d.total_given)], ['Last gift', d.last_gift ? formatDate(d.last_gift) : '–']].map(([k, v]) => <div key={k} className="rounded-xl bg-teal-50/60 p-3"><p className="font-display text-lg font-bold text-teal-700">{v}</p><p className="text-[11px] text-ink-muted">{k}</p></div>)}</div>
          <p className="text-sm text-ink-muted"><strong className="text-ink">Interests:</strong> {d.preferences || 'not recorded'}{d.location ? ` · ${d.location}` : ''}{d.contact ? ` · ${d.contact}` : ''}</p>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Open needs that suit this donor</p>
            {d.recommended_needs.length === 0 ? <p className="text-sm text-ink-muted">No open need matches this donor's interests yet.</p> : (
              <div className="space-y-2.5">{d.recommended_needs.map((n) => (
                <div key={n.need_id} className="card p-3.5">
                  <div className="flex items-start justify-between gap-2"><div><p className="text-sm font-semibold text-ink">{n.category}</p><p className="text-xs text-ink-muted">{n.organization_name} · qty {n.quantity ?? '–'}</p></div><LevelPill level={n.urgency} /></div>
                  <div className="mt-2 grid gap-3 sm:grid-cols-2"><ScoreBar label="Donor fit" value={n.fit_score} /><ScoreBar label="Priority" value={n.priority_score} tone="rose" /></div>
                  <Reasons items={n.reasons.slice(0, 3)} />
                </div>))}</div>)}
          </div>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-muted/80">Giving history</p>
            {d.donations.length === 0 ? <p className="text-sm text-ink-muted">No donations recorded.</p> : (
              <ul className="divide-y divide-line rounded-xl border border-line">{d.donations.map((g) => <li key={g.id} className="flex items-center justify-between gap-3 px-3.5 py-2.5 text-sm"><span className="min-w-0"><span className="font-semibold text-ink">{g.need_category || 'General gift'}</span><span className="text-xs text-ink-muted"> · {g.organization_name || '–'}{g.description ? ` · ${g.description}` : ''}</span></span><span className="shrink-0 text-right text-xs text-ink-muted"><strong className="text-ink">{g.amount ? money(g.amount) : 'In kind'}</strong><br />{formatDate(g.timestamp)}</span></li>)}</ul>)}
          </div>
        </div>
      )}
    </Modal>
  )
}

export default function AdminDonors() {
  const toast = useToast()
  const [orgFilter, setOrgFilter] = useState('')
  const [search, setSearch] = useState('')
  const donors = useAsync(() => api.adminDonors(orgFilter), [orgFilter])
  const orgs = useAsync(() => api.adminOrganizations(), [])
  const [editing, setEditing] = useState(undefined)   // undefined closed, null = new, object = edit
  const [viewing, setViewing] = useState(null)

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (donors.data || []).filter((d) => !q || [d.name, d.contact, d.preferences, d.location, d.organization_name].some((v) => (v || '').toLowerCase().includes(q)))
  }, [donors.data, search])

  const remove = async (d) => {
    if (!window.confirm(`Delete donor "${d.name}"? This cannot be undone.`)) return
    try { await api.adminDeleteDonor(d.id); toast.success('Donor deleted.'); donors.reload({ silent: true }) } catch (e) { toast.error(e.message) }
  }
  const total = (donors.data || []).reduce((a, d) => a + d.total_given, 0)

  return (
    <Layout title="All donors">
      <PageHeader icon={IconDonations} tone="rose" title="Donors of all organizations" subtitle={`${(donors.data || []).length} donor(s) · ${money(total)} given in total. Open a donor to see their history and the needs that suit them.`}
        actions={<Button variant="ghost" onClick={() => setEditing(null)} className="!border-white/40 !bg-white/15 !text-white hover:!bg-white/25"><IconPlus className="h-4 w-4" /> Add donor</Button>} />
      <div className="card mb-5 grid gap-3 p-4 sm:grid-cols-[1fr_16rem]">
        <Field label="Search"><div className="relative"><IconSearch className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" /><input className="field pl-10" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, interest, contact, organization" aria-label="Search donors" /></div></Field>
        <Field label="Organization"><select className="field" value={orgFilter} onChange={(e) => setOrgFilter(e.target.value)}><option value="">All organizations</option>{(orgs.data || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
      </div>
      {donors.error ? <ErrorState message={donors.error} onRetry={donors.reload} /> : donors.loading ? <TableSkeleton rows={5} cols={5} /> : rows.length === 0 ? (
        <EmptyState icon={IconDonations} title="No donors found" text="Add a donor, or change the search and organization filter." />
      ) : (
        <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[820px] text-sm">
          <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-3">Donor</th><th className="px-4 py-3">Interests</th><th className="px-4 py-3">Organization</th><th className="px-4 py-3 text-right">Giving</th><th className="px-4 py-3 text-right">Actions</th></tr></thead>
          <tbody>{rows.map((d) => (
            <tr key={d.id} className="border-b border-line align-top last:border-0 hover:bg-teal-50/40">
              <td className="px-4 py-3.5"><button className="text-left font-semibold text-ink hover:text-teal-700" onClick={() => setViewing(d.id)}>{d.name}</button><p className="text-xs text-ink-muted">{d.contact || 'No contact'}{d.location ? ` · ${d.location}` : ''}</p>{d.account_email && <Pill tone="sky" className="mt-1">has account</Pill>}</td>
              <td className="px-4 py-3.5 text-ink-muted">{d.preferences || '–'}</td>
              <td className="px-4 py-3.5 text-ink-muted">{d.organization_name || 'Platform donor'}</td>
              <td className="px-4 py-3.5 text-right"><p className="font-semibold text-ink">{money(d.total_given)}</p><p className="text-xs text-ink-muted">{d.gifts} gift(s){d.last_gift ? ` · last ${formatDate(d.last_gift)}` : ''}</p>{d.pending_suggestions > 0 && <Pill tone="violet" className="mt-1">{d.pending_suggestions} AI suggestion(s)</Pill>}</td>
              <td className="px-4 py-3.5 text-right"><div className="flex justify-end gap-1.5"><Button variant="soft" className="px-3 py-1.5 text-xs" onClick={() => setViewing(d.id)}>View</Button><Button variant="ghost" className="px-2.5 py-1.5 text-xs" aria-label={`Edit ${d.name}`} onClick={() => setEditing(d)}><IconEdit className="h-3.5 w-3.5" /></Button><Button variant="danger" className="px-2.5 py-1.5 text-xs" aria-label={`Delete ${d.name}`} onClick={() => remove(d)}><IconTrash className="h-3.5 w-3.5" /></Button></div></td>
            </tr>))}</tbody></table></div></div>
      )}
      <DonorForm open={editing !== undefined} donor={editing || null} orgs={orgs.data || []} onClose={() => setEditing(undefined)} onSaved={() => donors.reload({ silent: true })} />
      <DonorDetail id={viewing} onClose={() => setViewing(null)} />
    </Layout>
  )
}

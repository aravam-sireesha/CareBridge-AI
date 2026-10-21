import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, TableSkeleton, Tabs } from '../components/ui.jsx'
import { IconDonations, IconPeople, IconPlus } from '../components/icons.jsx'

export default function People() {
  const { user } = useAuth()
  const toast = useToast()
  const canAdd = user.role === 'admin' || user.role === 'organization'
  const [tab, setTab] = useState('donors')
  const donors = useAsync(() => api.listDonors(), [])
  const volunteers = useAsync(() => api.listVolunteers(), [])
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [f, setF] = useState({ name: '', contact: '', location: '', preferences: '', skills: '', availability: '' })
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }))
  const current = tab === 'donors' ? donors : volunteers
  const cols = tab === 'donors' ? [['name', 'Name'], ['preferences', 'Supports'], ['location', 'Location'], ['contact', 'Contact']] : [['name', 'Name'], ['skills', 'Skills'], ['availability', 'Availability'], ['location', 'Location'], ['contact', 'Contact']]

  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try {
      const base = { name: f.name.trim(), contact: f.contact || null, location: f.location || null }
      if (tab === 'donors') { await api.createDonor({ ...base, preferences: f.preferences || null }) }
      else { await api.createVolunteer({ ...base, skills: f.skills || null, availability: f.availability || null }) }
      toast.success(`${tab === 'donors' ? 'Donor' : 'Volunteer'} saved to the database.`)
      setOpen(false); setF({ name: '', contact: '', location: '', preferences: '', skills: '', availability: '' })
      current.reload({ silent: true })
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }

  return (
    <Layout title="Donors & volunteers">
      <PageHeader icon={IconPeople} tone="rose" title="Donors & volunteers" subtitle="See who can be matched against open needs."
        actions={canAdd && <Button variant="ghost" className="border-white/40 bg-white/95" onClick={() => setOpen(true)}><IconPlus className="h-4 w-4" /> Add {tab === 'donors' ? 'donor' : 'volunteer'}</Button>} />
      <Tabs tabs={[{ key: 'donors', label: `Donors${donors.data ? ` (${donors.data.length})` : ''}`, icon: IconDonations }, { key: 'volunteers', label: `Volunteers${volunteers.data ? ` (${volunteers.data.length})` : ''}`, icon: IconPeople }]} value={tab} onChange={setTab} />

      {current.error ? <ErrorState message={current.error} onRetry={current.reload} /> : current.loading ? <TableSkeleton rows={4} cols={cols.length} /> : !current.data?.length ? (
        <EmptyState icon={tab === 'donors' ? IconDonations : IconPeople} title={`No ${tab} yet`} text={canAdd ? 'Add one to include them in matching suggestions.' : undefined} />
      ) : (
        <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm">
          <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted">{cols.map(([, l]) => <th key={l} className="px-4 py-3">{l}</th>)}</tr></thead>
          <tbody>{current.data.map((r) => (
            <tr key={r.id} className="border-b border-line transition last:border-0 hover:bg-teal-50/40">
              {cols.map(([k], i) => <td key={k} className={`px-4 py-3.5 ${i === 0 ? 'font-semibold text-ink' : 'text-ink-muted'}`}>{r[k] || '–'}</td>)}
            </tr>))}</tbody></table></div></div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title={`Add a ${tab === 'donors' ? 'donor' : 'volunteer'}`} subtitle="Saved to PostgreSQL.">
        <form onSubmit={submit} className="space-y-4">
          <Field label="Name"><input className="field" required value={f.name} onChange={set('name')} /></Field>
          <div className="grid gap-4 sm:grid-cols-2"><Field label="Contact"><input className="field" value={f.contact} onChange={set('contact')} /></Field><Field label="Location"><input className="field" value={f.location} onChange={set('location')} /></Field></div>
          {tab === 'donors' ? <Field label="Supports (matched against need categories)"><input className="field" value={f.preferences} onChange={set('preferences')} placeholder="education, food" /></Field> : <>
            <Field label="Skills"><input className="field" value={f.skills} onChange={set('skills')} placeholder="tutoring, first aid" /></Field>
            <Field label="Availability"><input className="field" value={f.availability} onChange={set('availability')} placeholder="weekends" /></Field></>}
          <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" loading={saving}>Save</Button></div>
        </form>
      </Modal>
    </Layout>
  )
}

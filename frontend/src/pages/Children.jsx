import React, { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, Pill, TableSkeleton } from '../components/ui.jsx'
import { IconChildren, IconPlus, IconSearch } from '../components/icons.jsx'

export default function Children() {
  const { user } = useAuth()
  const toast = useToast()
  const minimal = user.role === 'admin'   // administrators get the privacy-minimized list; full details open on demand
  const { data, loading, error, reload } = useAsync(() => (minimal ? api.listChildrenSummary() : api.listChildren()), [])
  const orgs = useAsync(() => (user.role === 'admin' ? api.listOrganizations() : Promise.resolve([])), [])
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ age: '', interests: '', skills: '', academic_performance: '', org_id: '' })
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const rows = useMemo(() => {
    const term = q.trim().toLowerCase()
    const orgName = (c) => (orgs.data || []).find((o) => o.id === c.org_id)?.name || ''
    return (data || []).filter((c) => !term || (minimal ? [c.id, c.age_group, orgName(c)] : [c.id, c.interests, c.skills, c.academic_performance]).join(' ').toLowerCase().includes(term))
  }, [data, q, minimal, orgs.data])

  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try {
      const body = { age: Number(form.age), interests: form.interests || null, skills: form.skills || null, academic_performance: form.academic_performance || null }
      if (user.role === 'admin') body.org_id = Number(form.org_id)
      await api.createChild(body)
      toast.success('Child profile saved to the database.')
      setOpen(false); setForm({ age: '', interests: '', skills: '', academic_performance: '', org_id: '' })
      reload({ silent: true })
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }

  return (
    <Layout title="Children">
      <PageHeader icon={IconChildren} title="Children" subtitle="Child records are visible only to administrators and the organization that owns them."
        actions={<Button variant="ghost" className="border-white/40 bg-white/95" onClick={() => setOpen(true)}><IconPlus className="h-4 w-4" /> Add child</Button>} />

      {minimal && <p className="mb-4 rounded-xl bg-bg p-3 text-sm text-ink-muted">Sensitive details (interests, skills, school results) are hidden in this list. Open a full record only when you need it.</p>}
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="relative w-full max-w-xs"><IconSearch className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" /><input className="field pl-10" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search interests, skills…" aria-label="Search children" /></div>
        <span className="text-xs font-medium text-ink-muted">{rows.length} of {data?.length ?? 0}</span>
      </div>

      {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <TableSkeleton rows={5} cols={5} /> : rows.length === 0 ? (
        <EmptyState icon={IconChildren} title={data?.length ? 'No matches for your search' : 'No children registered yet'} text="Add a child profile to start career guidance and needs planning."
          action={!data?.length && <Button onClick={() => setOpen(true)}><IconPlus className="h-4 w-4" /> Add the first child</Button>} />
      ) : (
        <div className="card overflow-hidden"><div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted">
              {minimal
                ? <><th className="px-4 py-3">Record</th><th className="px-4 py-3">Organization</th><th className="px-4 py-3">Age group</th><th className="px-4 py-3" /></>
                : <><th className="px-4 py-3">ID</th><th className="px-4 py-3">Age</th><th className="px-4 py-3">Interests</th><th className="px-4 py-3">Skills</th><th className="px-4 py-3" /></>}</tr></thead>
            <tbody>{rows.map((c) => (
              <tr key={c.id} className="border-b border-line transition last:border-0 hover:bg-teal-50/40">
                <td className="px-4 py-3.5 font-semibold text-ink-muted">#{c.id}</td>
                {minimal ? (
                  <>
                    <td className="px-4 py-3.5 text-ink">{(orgs.data || []).find((o) => o.id === c.org_id)?.name || `Organization ${c.org_id}`}</td>
                    <td className="px-4 py-3.5"><Pill tone="sky">{c.age_group} yrs</Pill></td>
                    <td className="px-4 py-3.5 text-right"><Link to={`/children/${c.id}`} className="btn-soft px-3 py-1.5 text-xs">Open full record</Link></td>
                  </>
                ) : (
                  <>
                    <td className="px-4 py-3.5"><Pill tone="sky">{c.age ?? '–'} yrs</Pill></td>
                    <td className="px-4 py-3.5 text-ink">{c.interests || '–'}</td>
                    <td className="px-4 py-3.5 text-ink-muted">{c.skills || '–'}</td>
                    <td className="px-4 py-3.5 text-right"><Link to={`/children/${c.id}`} className="btn-soft px-3 py-1.5 text-xs">View profile</Link></td>
                  </>
                )}
              </tr>))}</tbody>
          </table></div></div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="Add a child" subtitle="Saved to the children table in PostgreSQL.">
        <form onSubmit={submit} className="space-y-4">
          {user.role === 'admin' && <Field label="Organization"><select className="field" required value={form.org_id} onChange={set('org_id')}><option value="">Select…</option>{(orgs.data || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>}
          <Field label="Age"><input className="field" type="number" min="0" max="25" required value={form.age} onChange={set('age')} /></Field>
          <Field label="Interests"><input className="field" value={form.interests} onChange={set('interests')} placeholder="Drawing, cricket, robotics" /></Field>
          <Field label="Skills"><input className="field" value={form.skills} onChange={set('skills')} placeholder="Singing, basic coding" /></Field>
          <Field label="Academic performance"><input className="field" value={form.academic_performance} onChange={set('academic_performance')} placeholder="Strong in maths, needs reading support" /></Field>
          <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" loading={saving}>Save child</Button></div>
        </form>
      </Modal>
    </Layout>
  )
}

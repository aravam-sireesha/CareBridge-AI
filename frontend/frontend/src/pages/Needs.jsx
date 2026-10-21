import React, { useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, TableSkeleton, formatDate } from '../components/ui.jsx'
import { IconNeeds, IconPlus } from '../components/icons.jsx'

const URGENCY = ['all', 'critical', 'high', 'medium', 'low']
const STATUSES = ['open', 'pending', 'fulfilled', 'closed']

export default function Needs() {
  const { user } = useAuth()
  const toast = useToast()
  const canManage = user.role === 'admin' || user.role === 'organization'
  const { data, loading, error, reload } = useAsync(() => api.listNeeds(), [])
  const orgs = useAsync(() => (user.role === 'admin' ? api.listOrganizations() : Promise.resolve([])), [])
  const [filter, setFilter] = useState('all')
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ category: '', quantity: '', urgency: 'medium', org_id: '' })
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const rows = useMemo(() => (data || []).filter((n) => filter === 'all' || (n.urgency || '').toLowerCase() === filter), [data, filter])

  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try {
      const body = { category: form.category.trim(), quantity: Number(form.quantity), urgency: form.urgency }
      if (user.role === 'admin') body.org_id = Number(form.org_id)
      await api.createNeed(body)
      toast.success('Need saved to the database.')
      setOpen(false); setForm({ category: '', quantity: '', urgency: 'medium', org_id: '' })
      reload({ silent: true })
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }

  const changeStatus = async (need, status) => {
    try { await api.updateNeed(need.id, { status }); toast.success(`Need marked ${status}.`); reload({ silent: true }) }
    catch (err) { toast.error(err.message) }
  }

  return (
    <Layout title="Needs">
      <PageHeader icon={IconNeeds} tone="amber" title="Needs"
        subtitle={canManage ? 'Record what children need and track it until it is fulfilled.' : 'Needs from verified organizations that you can help with.'}
        actions={canManage && <Button variant="ghost" className="border-white/40 bg-white/95" onClick={() => setOpen(true)}><IconPlus className="h-4 w-4" /> Add need</Button>} />

      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Filter by urgency">
        {URGENCY.map((u) => (
          <button key={u} onClick={() => setFilter(u)} className={`rounded-full px-4 py-1.5 text-xs font-semibold capitalize transition ${filter === u ? 'bg-gradient-to-r from-teal-600 to-sky-600 text-white shadow-card' : 'bg-white text-ink-muted ring-1 ring-line hover:text-teal-700'}`}>{u}</button>
        ))}
      </div>

      {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <TableSkeleton rows={5} cols={5} /> : rows.length === 0 ? (
        <EmptyState icon={IconNeeds} title="No needs found" text={canManage ? 'Add a need so donors and volunteers can be matched to it.' : 'Verified organizations have not posted needs yet.'}
          action={canManage && <Button onClick={() => setOpen(true)}><IconPlus className="h-4 w-4" /> Add a need</Button>} />
      ) : (
        <div className="card overflow-hidden"><div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted">
              <th className="px-4 py-3">Category</th><th className="px-4 py-3">Organization</th><th className="px-4 py-3">Quantity</th><th className="px-4 py-3">Urgency</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Posted</th></tr></thead>
            <tbody>{rows.map((n) => (
              <tr key={n.id} className="border-b border-line transition last:border-0 hover:bg-teal-50/40">
                <td className="px-4 py-3.5 font-semibold text-ink">{n.category || '–'}</td>
                <td className="px-4 py-3.5 text-ink-muted">{n.organization_name || '–'}</td>
                <td className="px-4 py-3.5 text-ink-muted">{n.quantity ?? '–'}</td>
                <td className="px-4 py-3.5"><StatusBadge status={n.urgency} /></td>
                <td className="px-4 py-3.5">{canManage ? (
                  <select aria-label="Change status" value={(n.status || 'open').toLowerCase()} onChange={(e) => changeStatus(n, e.target.value)} className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold capitalize text-ink">
                    {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}</select>) : <StatusBadge status={n.status} />}</td>
                <td className="px-4 py-3.5 text-ink-muted">{formatDate(n.created_at)}</td>
              </tr>))}</tbody>
          </table></div></div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="Add a need" subtitle="Saved to the needs table in PostgreSQL.">
        <form onSubmit={submit} className="space-y-4">
          {user.role === 'admin' && <Field label="Organization"><select className="field" required value={form.org_id} onChange={set('org_id')}><option value="">Select…</option>{(orgs.data || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>}
          <Field label="Category"><input className="field" required maxLength={200} value={form.category} onChange={set('category')} placeholder="School supplies" /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Quantity"><input className="field" type="number" min="0" required value={form.quantity} onChange={set('quantity')} /></Field>
            <Field label="Urgency"><select className="field" value={form.urgency} onChange={set('urgency')}>{['low', 'medium', 'high', 'critical'].map((u) => <option key={u} value={u} className="capitalize">{u}</option>)}</select></Field>
          </div>
          <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" loading={saving}>Save need</Button></div>
        </form>
      </Modal>
    </Layout>
  )
}

import React, { useState } from 'react'
import { openParam } from '../lib/openParam.js'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import DataTable from '../components/DataTable.jsx'
import NeedAssist from '../components/NeedAssist.jsx'
import NearbyHelpers from '../components/NearbyHelpers.jsx'
import { Button, Field, Modal, PageHeader, formatDate } from '../components/ui.jsx'
import { IconNeeds, IconPlus } from '../components/icons.jsx'

const STATUSES = ['open', 'pending', 'fulfilled', 'closed']
const EMPTY = { category: '', quantity: '', urgency: 'medium', org_id: '', title: '', description: '' }

export default function Needs() {
  const { user } = useAuth()
  const toast = useToast()
  const canManage = user.role === 'admin' || user.role === 'organization'
  const { data, loading, error, reload } = useAsync(() => api.listNeeds(), [])
  const orgs = useAsync(() => (user.role === 'admin' ? api.listOrganizations() : Promise.resolve([])), [])
  const [open, setOpen] = useState(() => { try { return canManage && new URLSearchParams(window.location.search).get('new') === '1' } catch { return false } })
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try {
      const body = { category: form.category.trim(), quantity: Number(form.quantity), urgency: form.urgency }
      if (form.title.trim()) body.title = form.title.trim()
      if (form.description.trim()) body.description = form.description.trim()
      if (user.role === 'admin') body.org_id = Number(form.org_id)
      await api.createNeed(body)
      toast.success('Need saved to the database.')
      setOpen(false); setForm(EMPTY)
      reload({ silent: true })
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }

  const changeStatus = async (need, status) => {
    try { await api.updateNeed(need.id, { status }); toast.success(`Need marked ${status}.`); reload({ silent: true }) }
    catch (err) { toast.error(err.message) }
  }

  return (
    <Layout title="Needs">
      <PageHeader icon={IconNeeds} title="Needs"
        subtitle={canManage ? 'Record what children need and track it until it is fulfilled.' : 'Needs from verified organizations that you can help with.'}
        actions={canManage && <Button onClick={() => setOpen(true)}><IconPlus className="h-4 w-4" /> Add need</Button>} />

      <div className="card p-4">
        <DataTable label="Needs" caption="Needs" rows={data} loading={loading} error={error} onRetry={reload} openId={openParam()} pageSize={10} searchPlaceholder="Search needs"
          initialSort={{ key: 'created_at', dir: 'desc' }}
          filters={[
            { key: 'urgency', label: 'Urgency', get: (n) => (n.urgency || '').toLowerCase(), options: ['critical', 'high', 'medium', 'low'].map((v) => ({ value: v, label: v })) },
            { key: 'status', label: 'Status', get: (n) => (n.status || 'open').toLowerCase(), options: STATUSES.map((v) => ({ value: v, label: v })) }
          ]}
          columns={[
            { key: 'category', header: 'Category', sortValue: (n) => n.category || '', render: (n) => <span className="font-semibold">{n.category || '–'}</span> },
            { key: 'organization_name', header: 'Organization', sortValue: (n) => n.organization_name || '', render: (n) => n.organization_name || '–' },
            { key: 'quantity', header: 'Quantity', sortValue: (n) => Number(n.quantity || 0), render: (n) => n.quantity ?? '–' },
            { key: 'urgency', header: 'Urgency', sortValue: (n) => ['low', 'medium', 'high', 'critical'].indexOf((n.urgency || '').toLowerCase()), render: (n) => <StatusBadge status={n.urgency} />, searchable: false },
            { key: 'status', header: 'Status', sortValue: (n) => n.status || '', render: (n) => (canManage
              ? <select aria-label="Change status" value={(n.status || 'open').toLowerCase()} onChange={(e) => changeStatus(n, e.target.value)} className="rounded-lg border border-line bg-white px-2 py-1 text-xs font-semibold capitalize text-ink">{STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}</select>
              : <StatusBadge status={n.status} />) },
            { key: 'created_at', header: 'Posted', sortValue: (n) => n.created_at || '', render: (n) => formatDate(n.created_at) }
          ]}
          detailTitle={(n) => `${n.title || n.category || 'Need'} (#${n.id})`}
          detail={(n) => (
            <div className="space-y-4">
            <dl className="space-y-3 text-sm">
              {[['Category', n.category], ['Organization', n.organization_name], ['Quantity', n.quantity], ['Description', n.description], ['Location', n.location], ['Beneficiaries', n.beneficiaries], ['Required by', n.required_by ? formatDate(n.required_by) : null], ['Posted', formatDate(n.created_at)]].map(([k, v]) => (
                <div key={k}><dt className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{k}</dt><dd className="mt-0.5 whitespace-pre-line text-ink">{v ?? '–'}</dd></div>))}
              <div className="flex gap-2"><StatusBadge status={n.urgency} /><StatusBadge status={n.status} /></div>
            </dl>
            {canManage && <NearbyHelpers needId={n.id} />}
            </div>
          )}
          emptyTitle="No open needs found" emptyText={canManage ? 'Add a need so donors and volunteers can be matched to it.' : 'Verified organizations have not posted needs yet.'}
          emptyAction={canManage && <Button onClick={() => setOpen(true)}><IconPlus className="h-4 w-4" /> Add a need</Button>} />
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="Add a need" subtitle="Saved to the needs table in PostgreSQL.">
        <form onSubmit={submit} className="space-y-4">
          <NeedAssist onUse={(k, v) => setForm((f) => ({ ...f, [k]: v }))} />
          {user.role === 'admin' && <Field label="Organization"><select className="field" required value={form.org_id} onChange={set('org_id')}><option value="">Select…</option>{(orgs.data || []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>}
          <Field label="Category"><input className="field" required maxLength={200} value={form.category} onChange={set('category')} placeholder="School supplies" /></Field>
          <Field label="Title (optional)"><input className="field" maxLength={200} value={form.title} onChange={set('title')} placeholder="Winter blankets for the boys' dormitory" /></Field>
          <Field label="Description (optional)"><textarea className="field" rows={3} maxLength={4000} value={form.description} onChange={set('description')} /></Field>
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

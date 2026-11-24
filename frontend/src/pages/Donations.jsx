import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { openParam } from '../lib/openParam.js'
import { useAsync } from '../hooks/useAsync.js'
import DataTable from '../components/DataTable.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import Layout from '../components/Layout.jsx'
import { Button, Field, Modal, PageHeader, StatCard, StatSkeleton, formatDate, formatMoney } from '../components/ui.jsx'
import { IconDonations, IconPlus } from '../components/icons.jsx'

export default function Donations() {
  const { user } = useAuth()
  const toast = useToast()
  const canRecord = ['admin', 'organization', 'donor'].includes(user.role)
  const { data, loading, error, reload } = useAsync(() => api.listDonations(), [])
  const donors = useAsync(() => (canRecord ? api.listDonors() : Promise.resolve([])), [])
  const needs = useAsync(() => api.listNeeds(), [])
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [f, setF] = useState({ donor_id: '', need_id: '', amount: '', resource_description: '' })
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }))
  const total = (data || []).reduce((s, d) => s + Number(d.amount || 0), 0)
  const availableNeeds = needs.data || []
  const needsUnavailable = needs.loading || !!needs.error || availableNeeds.length === 0
  const emptyNeedsMessage = user.role === 'organization'
    ? 'No needs are available for your organization. Add a need first, then try again.'
    : user.role === 'donor'
      ? 'No needs from verified organizations are available yet.'
      : 'No needs are available yet. Create a need first, then try again.'

  const submit = async (e) => {
    e.preventDefault(); setSaving(true)
    try {
      await api.createDonation({ donor_id: Number(f.donor_id), need_id: Number(f.need_id), amount: f.amount === '' ? null : Number(f.amount), resource_description: f.resource_description || null })
      toast.success('Donation saved to the database.')
      setOpen(false); setF({ donor_id: '', need_id: '', amount: '', resource_description: '' })
      reload({ silent: true })
    } catch (err) { toast.error(err.message) } finally { setSaving(false) }
  }

  return (
    <Layout title="Donations">
      <PageHeader icon={IconDonations} tone="rose" title="Donations" subtitle={user.role === 'donor' ? 'The gifts you have made. You can record a new one for any verified need.' : 'Record gifts and link them to needs. Unusual ones are screened by the fraud module.'}
        actions={canRecord && <Button variant="ghost" className="border-white/40 bg-white/95" onClick={() => setOpen(true)}><IconPlus className="h-4 w-4" /> Record donation</Button>} />
      {loading && !data ? <div className="mb-5"><StatSkeleton count={2} /></div> : null}
      {!loading && !error && data && <div className="mb-5 grid gap-4 sm:grid-cols-2"><StatCard label="Donations" value={data.length} icon={IconDonations} tone="rose" /><StatCard label="Total amount" value={formatMoney(total)} icon={IconDonations} tone="teal" /></div>}
      <div className="card p-4">
        <DataTable label="Donations" caption="Donations" rows={data} loading={loading} error={error} onRetry={reload} openId={openParam()} pageSize={10} initialSort={{ key: 'timestamp', dir: 'desc' }}
          searchPlaceholder="Search donations"
          filters={[{ key: 'status', label: 'Status', get: (d) => (d.status || 'unspecified').toLowerCase(), options: [...new Set((data || []).map((d) => (d.status || 'unspecified').toLowerCase()))].sort().map((v) => ({ value: v, label: v.replace(/_/g, ' ') })) }]}
          columns={[
            { key: 'donor_name', header: 'Donor', sortValue: (d) => d.donor_name || '', render: (d) => <span className="font-semibold">{d.donor_name || (d.donor_id ? `Donor #${d.donor_id}` : '–')}</span> },
            { key: 'need_name', header: 'For need', sortValue: (d) => d.need_name || '', render: (d) => d.need_name || '–' },
            { key: 'amount', header: 'Amount', sortValue: (d) => Number(d.amount || 0), render: (d) => <span className="font-semibold text-teal-700">{formatMoney(d.amount)}</span> },
            { key: 'status', header: 'Status', sortValue: (d) => d.status || '', render: (d) => <StatusBadge status={d.status || 'unspecified'} /> },
            { key: 'resource_description', header: 'Description', sortValue: (d) => d.resource_description || '', hideOnMobile: true, render: (d) => d.resource_description || '–' },
            { key: 'timestamp', header: 'Date', sortValue: (d) => d.timestamp || '', render: (d) => formatDate(d.timestamp) }
          ]}
          detailTitle={(d) => `Donation #${d.id}`}
          detail={(d) => (
            <dl className="space-y-3 text-sm">
              {[['Donor', d.donor_name || (d.donor_id ? `Donor #${d.donor_id}` : '–')], ['For need', d.need_name || '–'], ['Amount', formatMoney(d.amount)], ['Description', d.resource_description || '–'], ['Recorded', formatDate(d.timestamp)], ['Delivered', d.delivered_at ? formatDate(d.delivered_at) : 'Not yet'], ['Confirmed', d.confirmed_at ? formatDate(d.confirmed_at) : 'Not yet'], ['Delivery note', d.delivery_note || '–']].map(([k, v]) => (
                <div key={k}><dt className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{k}</dt><dd className="mt-0.5 text-ink">{v}</dd></div>))}
              <div><dt className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Status</dt><dd className="mt-1"><StatusBadge status={d.status || 'unspecified'} /></dd></div>
            </dl>
          )}
          emptyTitle="No donations have been recorded yet" emptyText={canRecord ? 'Record a donation to see it here and in the dashboard trend.' : 'Your donations will appear here.'}
          emptyAction={canRecord && <Button onClick={() => setOpen(true)}><IconPlus className="h-4 w-4" /> Record donation</Button>} />
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="Record a donation" subtitle="Saved to the donations table in PostgreSQL.">
        <form onSubmit={submit} className="space-y-4">
          <Field label="Donor"><select className="field" required value={f.donor_id} onChange={set('donor_id')}><option value="">Select a donor…</option>{(donors.data || []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>
          <Field
            label="For need"
            hint={!needs.error && (needs.loading ? 'Loading available needs…' : !availableNeeds.length ? emptyNeedsMessage : undefined)}
            error={needs.error ? `Could not load needs: ${needs.error}` : undefined}
          >
            <select
              className="field"
              required
              value={f.need_id}
              onChange={set('need_id')}
              disabled={needsUnavailable}
            >
              <option value="">
                {needs.loading ? 'Loading needs…' : needs.error ? 'Could not load needs' : availableNeeds.length ? 'Select a need…' : 'No needs available'}
              </option>
              {availableNeeds.map((n) => <option key={n.id} value={n.id}>{n.category} (#{n.id})</option>)}
            </select>
          </Field>
          {needs.error && <Button type="button" variant="ghost" className="-mt-2" onClick={() => needs.reload()}>Retry loading needs</Button>}
          <Field label="Amount (INR)"><input className="field" type="number" min="0" step="0.01" required value={f.amount} onChange={set('amount')} /></Field>
          <Field label="Description"><input className="field" value={f.resource_description} onChange={set('resource_description')} placeholder="Books and stationery" /></Field>
          <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" loading={saving} disabled={needsUnavailable}>Save donation</Button></div>
        </form>
      </Modal>
    </Layout>
  )
}

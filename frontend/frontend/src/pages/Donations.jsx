import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Button, EmptyState, ErrorState, Field, Modal, PageHeader, StatCard, TableSkeleton, formatDate, formatMoney } from '../components/ui.jsx'
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
      {!loading && !error && <div className="mb-5 grid gap-4 sm:grid-cols-2"><StatCard label="Donations" value={data.length} icon={IconDonations} tone="rose" /><StatCard label="Total amount" value={formatMoney(total)} icon={IconDonations} tone="teal" /></div>}
      {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <TableSkeleton rows={5} cols={5} /> : !data.length ? (
        <EmptyState icon={IconDonations} title="No donations yet" text={canRecord ? 'Record a donation to see it here and in the dashboard trend.' : 'Your donations will appear here.'} />
      ) : (
        <div className="card overflow-hidden"><div className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm">
          <thead><tr className="border-b border-line bg-teal-50/60 text-left text-xs font-semibold text-ink-muted"><th className="px-4 py-3">Donor</th><th className="px-4 py-3">For need</th><th className="px-4 py-3">Amount</th><th className="px-4 py-3">Description</th><th className="px-4 py-3">Date</th></tr></thead>
          <tbody>{data.map((d) => (
            <tr key={d.id} className="border-b border-line transition last:border-0 hover:bg-teal-50/40">
              <td className="px-4 py-3.5 font-semibold text-ink">{d.donor_name || (d.donor_id ? `Donor #${d.donor_id}` : '–')}</td>
              <td className="px-4 py-3.5 text-ink-muted">{d.need_name || '–'}</td>
              <td className="px-4 py-3.5 font-semibold text-teal-700">{formatMoney(d.amount)}</td>
              <td className="px-4 py-3.5 text-ink-muted">{d.resource_description || '–'}</td>
              <td className="px-4 py-3.5 text-ink-muted">{formatDate(d.timestamp)}</td>
            </tr>))}</tbody></table></div></div>
      )}
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

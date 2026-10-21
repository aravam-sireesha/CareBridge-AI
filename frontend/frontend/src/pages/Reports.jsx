import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { Button, CardSkeleton, ErrorState, Field, PageHeader } from '../components/ui.jsx'
import { IconDownload, IconFile } from '../components/icons.jsx'

const STATUS_HINT = { donation_summary: 'pledged, in_transit, delivered, confirmed', need_fulfillment: 'open, pending, fulfilled, closed', org_verification: 'pending, under_review, info_requested, verified, rejected', anomaly_review: 'outstanding or reviewed' }

export default function Reports() {
  const { user } = useAuth()
  const toast = useToast()
  const types = useAsync(() => api.reportTypes(), [])
  const [type, setType] = useState('')
  const [f, setF] = useState({ date_from: '', date_to: '', status: '', category: '', organization_id: '' })
  const [busy, setBusy] = useState(false)
  const list = types.data?.reports || []
  const current = list.find((r) => r.key === (type || list[0]?.key))
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }))
  const show = (k) => current?.filters.includes(k) && !(k === 'organization_id' && user?.role !== 'admin')
  const download = async () => {
    setBusy(true)
    try { await api.downloadReport(current.key, f); toast.success('Report downloaded.') } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  return (
    <Layout title="Reports">
      <PageHeader icon={IconFile} title="Reports" subtitle="Download CSV reports built from live records. Child records are never included, and every download is logged." />
      {types.error ? <ErrorState message={types.error} onRetry={types.reload} /> : types.loading && !types.data ? <CardSkeleton rows={3} /> : (
        <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
          <div className="card divide-y divide-line" role="radiogroup" aria-label="Report type">
            {list.map((r) => (
              <label key={r.key} className="flex cursor-pointer items-center gap-3 px-4 py-3 hover:bg-teal-50/60">
                <input type="radio" name="report" checked={current?.key === r.key} onChange={() => setType(r.key)} />
                <span className="text-sm font-semibold text-ink">{r.label}</span>
              </label>
            ))}
            {(types.data?.unavailable || []).map((u) => <p key={u.key} className="px-4 py-3 text-xs text-ink-muted"><strong className="capitalize text-ink">{u.key.replace(/_/g, ' ')}</strong>: not available. {u.reason}</p>)}
          </div>
          {current && (
            <div className="card p-5">
              <h2 className="font-display text-base font-semibold text-ink">{current.label}</h2>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {show('date_from') && <Field label="From date"><input className="field" type="date" value={f.date_from} onChange={set('date_from')} /></Field>}
                {show('date_to') && <Field label="To date"><input className="field" type="date" value={f.date_to} onChange={set('date_to')} /></Field>}
                {show('status') && <Field label="Status" hint={STATUS_HINT[current.key]}><input className="field" value={f.status} onChange={set('status')} placeholder="Any" /></Field>}
                {show('category') && <Field label="Category"><input className="field" value={f.category} onChange={set('category')} placeholder="Any" /></Field>}
                {show('organization_id') && <Field label="Organization ID"><input className="field" type="number" min="1" value={f.organization_id} onChange={set('organization_id')} placeholder="All" /></Field>}
              </div>
              {user?.role === 'organization' && <p className="mt-3 text-xs text-ink-muted">Reports include only your own organization&apos;s records.</p>}
              <div className="mt-5"><Button loading={busy} onClick={download}><IconDownload className="h-4 w-4" /> Download CSV</Button></div>
            </div>
          )}
        </div>
      )}
    </Layout>
  )
}

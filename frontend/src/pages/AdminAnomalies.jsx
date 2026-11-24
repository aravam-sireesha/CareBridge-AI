import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { Reasons } from '../components/AdminParts.jsx'
import { Button, ConfirmDialog, EmptyState, ErrorState, PageHeader, Pagination, TableSkeleton, formatDate } from '../components/ui.jsx'
import { IconAlert } from '../components/icons.jsx'

const DECISIONS = {
  donation: [['confirmed_fraud', 'Confirm after review', 'danger', 'You are recording that, after reviewing the evidence yourself, this donation is fraudulent. The alert alone is only a signal.'], ['false_positive', 'Not an issue', 'ghost', 'You are recording that this alert was a false positive.']],
  need: [['action_taken', 'Action taken', 'primary', 'You are recording that you followed up on this alert.'], ['dismissed', 'Dismiss', 'ghost', 'You are recording that no action is needed.']]
}

export default function AdminAnomalies() {
  const toast = useToast()
  const [f, setF] = useState({ kind: 'all', state: 'outstanding', min_score: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [pending, setPending] = useState(null)
  const [busy, setBusy] = useState(false)
  const list = useAsync(() => api.anomalies({ ...f, page, page_size: 15 }), [f, page])
  const d = list.data
  const set = (k) => (e) => { setF((p) => ({ ...p, [k]: e.target.value })); setPage(1) }
  const decide = async () => {
    setBusy(true)
    try {
      const { item, decision } = pending
      if (item.kind === 'donation') await api.reviewFraudFlag(item.id, decision); else await api.reviewNeedAlert(item.id, decision)
      toast.success('Review saved and added to the audit trail.'); setPending(null); list.reload({ silent: true })
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  return (
    <Layout title="Anomaly Detection">
      <PageHeader icon={IconAlert} tone="amber" title="Anomaly Detection" subtitle="Unusual donations and needs found by the AI. An alert is a signal to look into, not proof of wrongdoing; a person decides." />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label><span className="mb-1 block text-xs font-semibold text-ink-muted">Type</span><select className="field" value={f.kind} onChange={set('kind')}><option value="all">All</option><option value="donation">Donations</option><option value="need">Needs</option></select></label>
        <label><span className="mb-1 block text-xs font-semibold text-ink-muted">Review status</span><select className="field" value={f.state} onChange={set('state')}><option value="outstanding">Outstanding</option><option value="reviewed">Reviewed</option><option value="all">All</option></select></label>
        <label><span className="mb-1 block text-xs font-semibold text-ink-muted">Minimum model score</span><input className="field" type="number" min="0" step="0.05" value={f.min_score} onChange={set('min_score')} placeholder="e.g. 0.6" /></label>
        <label><span className="mb-1 block text-xs font-semibold text-ink-muted">From</span><input className="field" type="date" value={f.date_from} onChange={set('date_from')} /></label>
        <label><span className="mb-1 block text-xs font-semibold text-ink-muted">To</span><input className="field" type="date" value={f.date_to} onChange={set('date_to')} /></label>
      </div>
      {list.error ? <ErrorState message={`The anomaly list could not be loaded. ${list.error}`} onRetry={list.reload} /> : list.loading && !d ? <TableSkeleton rows={5} cols={5} /> : d.items.length === 0 ? (
        <EmptyState icon={IconAlert} title="Nothing to show" text="No alerts match these filters. Run the AI scans from the Admin Dashboard to look for new ones." />
      ) : (
        <div className="space-y-3">
          {d.capped && <p role="status" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">Showing the most recent alerts only. Narrow the dates to see older ones.</p>}
          {d.items.map((i) => (
            <article key={`${i.kind}-${i.id}`} className="card p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0"><p className="font-semibold text-ink">{i.subject}</p>
                  <p className="text-xs text-ink-muted">{i.kind === 'donation' ? 'Donation alert' : 'Need alert'} #{i.id}{i.organization ? ` · ${i.organization}` : ''} · detected {formatDate(i.flagged_at)} · {i.model_version}</p></div>
                <div className="flex items-center gap-3"><span className="text-xs text-ink-muted">Model score <strong className="text-ink">{Number(i.score).toFixed(2)}</strong></span><StatusBadge status={i.status} /></div>
              </div>
              <Reasons items={Array.isArray(i.reasons) ? i.reasons : [String(i.reasons)]} />
              {i.status === 'outstanding' ? (
                <div className="mt-3 flex flex-wrap justify-end gap-2">{DECISIONS[i.kind].map(([decision, label, variant, text]) => <Button key={decision} variant={variant} className="px-3 py-1.5 text-xs" onClick={() => setPending({ item: i, decision, label, variant, text })}>{label}</Button>)}</div>
              ) : <p className="mt-2 text-xs text-ink-muted">Reviewed{i.reviewed_by ? ` by ${i.reviewed_by}` : ''}{i.reviewed_at ? ` on ${formatDate(i.reviewed_at)}` : ''}.</p>}
            </article>
          ))}
        </div>
      )}
      {d && <Pagination page={d.page} pages={d.pages} total={d.total} onPage={setPage} label="alerts" />}
      <p className="mt-6 text-xs text-ink-muted">Marking an alert “under review” or “escalated” is not available yet: the current data model records only the final decision.</p>
      {pending && <ConfirmDialog open title={pending.label} text={pending.text} confirmLabel={pending.label} tone={pending.variant === 'danger' ? 'danger' : 'primary'} loading={busy} onConfirm={decide} onCancel={() => setPending(null)} />}
    </Layout>
  )
}

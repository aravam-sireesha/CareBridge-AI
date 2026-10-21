import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import { useDebounced } from '../hooks/useDebounced.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { Button, ConfirmDialog, EmptyState, ErrorState, Modal, PageHeader, Pagination, TableSkeleton, Tabs, formatDate } from '../components/ui.jsx'
import { IconBuilding, IconSearch } from '../components/icons.jsx'

const TABS = [['all', 'All'], ['pending', 'Pending'], ['under_review', 'Under review'], ['info_requested', 'Info requested'], ['verified', 'Verified'], ['rejected', 'Rejected']]
const ACTIONS = {
  approve: { label: 'Approve', title: 'Approve this organization?', text: 'It will be able to publish needs that donors and volunteers can see. The organization is notified and this decision is saved in the audit trail.', variant: 'primary' },
  under_review: { label: 'Mark under review', title: 'Mark as under review?', text: 'The organization is told its application is being reviewed.', variant: 'ghost' },
  request_info: { label: 'Request more information', title: 'Ask for more information', text: 'Tell the organization exactly what is missing. They will see your message.', variant: 'ghost', reason: 'What do you need from them?' },
  reject: { label: 'Reject', title: 'Reject this organization?', text: 'The organization is not verified and cannot publish public needs. They will see your reason.', variant: 'danger', reason: 'Reason for rejecting' }
}
const Row = ({ k, v }) => <div className="grid gap-1 py-2 sm:grid-cols-[10rem_1fr]"><dt className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{k}</dt><dd className="break-words text-sm text-ink">{v || <span className="text-ink-muted">Not provided</span>}</dd></div>

function ReviewModal({ id, onClose, onChanged }) {
  const toast = useToast()
  const detail = useAsync(() => api.verificationDetail(id), [id])
  const [action, setAction] = useState(null)
  const [busy, setBusy] = useState(false)
  const d = detail.data
  const confirm = async (note) => {
    setBusy(true)
    try {
      await api.decideVerification(id, { decision: action, note: note || null, expected_status: d.status })
      toast.success('Decision saved and added to the audit trail.')
      setAction(null); detail.reload({ silent: true }); onChanged()
    } catch (e) { toast.error(e.message); if (e.status === 409) { setAction(null); detail.reload({ silent: true }) } } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose} wide title={d ? d.name : 'Organization'} subtitle="Review the registration details, then record a decision.">
      {detail.error ? <ErrorState message={detail.error} onRetry={detail.reload} /> : !d ? <TableSkeleton rows={4} cols={2} /> : (
        <>
          <div className="mb-4 flex items-center gap-3"><StatusBadge status={d.status} /><span className="text-xs text-ink-muted">Submitted {formatDate(d.submitted_at)}{d.verified_at ? ` · verified ${formatDate(d.verified_at)}` : ''}</span></div>
          <dl className="divide-y divide-line rounded-xl border border-line px-4">
            <Row k="Registration no." v={d.registration_number} /><Row k="Authorized contact" v={d.contact} /><Row k="Address" v={d.address} />
            <Row k="Website" v={d.website} /><Row k="About" v={d.description} /><Row k="Needs posted" v={String(d.needs_count)} /><Row k="Reviewer note" v={d.note} />
            <Row k="Documents" v={d.documents_supported ? null : 'Document upload is not available in this version, so none can be shown. Check registration details with the organization directly.'} />
          </dl>
          <div className="mt-4 flex flex-wrap gap-2">
            {Object.entries(ACTIONS).filter(([k]) => !(k === 'approve' && d.status === 'verified') && !(k === 'under_review' && d.status === 'under_review')).map(([k, a]) => (
              <Button key={k} variant={a.variant} onClick={() => setAction(k)}>{a.label}</Button>
            ))}
          </div>
          <h3 className="mb-2 mt-6 text-sm font-semibold text-ink">Decision history</h3>
          {d.history.length === 0 ? <p className="text-sm text-ink-muted">No decisions recorded yet.</p> : (
            <ul className="space-y-2">{d.history.map((h, i) => (
              <li key={i} className="rounded-xl bg-bg px-3 py-2 text-sm"><span className="font-semibold">{h.action.replace('organization.verification.', '').replace('organization.', '').replace(/_/g, ' ')}</span> by {h.by || 'unknown'} · {new Date(h.at).toLocaleString()}{h.detail?.note ? <p className="mt-0.5 text-xs text-ink-muted">“{h.detail.note}”</p> : null}</li>
            ))}</ul>
          )}
          {action && <ConfirmDialog open title={ACTIONS[action].title} text={ACTIONS[action].text} confirmLabel={ACTIONS[action].label} tone={ACTIONS[action].variant === 'danger' ? 'danger' : 'primary'}
            reasonLabel={ACTIONS[action].reason || 'Note (optional)'} reasonRequired={!!ACTIONS[action].reason} loading={busy} onConfirm={confirm} onCancel={() => setAction(null)} />}
        </>
      )}
    </Modal>
  )
}

export default function AdminVerification() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(null)
  const dq = useDebounced(q)
  const list = useAsync(() => api.verifications({ q: dq, status: status === 'all' ? '' : status, page, page_size: 15 }), [dq, status, page])
  const d = list.data
  const counts = d?.counts || {}
  const tabs = TABS.map(([key, label]) => ({ key, label: key === 'all' ? label : `${label} (${counts[key] || 0})` }))
  return (
    <Layout title="Organization Verification">
      <PageHeader icon={IconBuilding} title="Organization Verification" subtitle="Only verified organizations can publish needs that donors and volunteers see. Every decision is recorded with your name and reason." />
      <Tabs tabs={tabs} value={status} onChange={(k) => { setStatus(k); setPage(1) }} />
      <label className="relative mb-4 block max-w-sm"><span className="sr-only">Search organizations</span>
        <IconSearch className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
        <input className="field pl-10" placeholder="Search name, contact or registration no." value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
      </label>
      {list.error ? <ErrorState message={list.error} onRetry={list.reload} /> : list.loading && !d ? <TableSkeleton rows={6} cols={5} /> : d.items.length === 0 ? (
        <EmptyState icon={IconBuilding} title="No organizations match" text="Try another status or a different search." />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wide text-ink-muted"><tr><th className="px-4 py-3">Organization</th><th className="px-4 py-3">Contact</th><th className="px-4 py-3">Submitted</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Needs</th><th className="px-4 py-3"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody className="divide-y divide-line">{d.items.map((o) => (
              <tr key={o.id}>
                <td className="px-4 py-3"><p className="font-semibold text-ink">{o.name}</p><p className="text-xs text-ink-muted">{o.registration_number || 'No registration no.'}</p></td>
                <td className="px-4 py-3 text-ink-muted">{o.contact || '—'}</td><td className="px-4 py-3 text-ink-muted">{formatDate(o.submitted_at)}</td>
                <td className="px-4 py-3"><StatusBadge status={o.status} /></td><td className="px-4 py-3 text-right">{o.needs_count}</td>
                <td className="px-4 py-3 text-right"><Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => setOpen(o.id)} aria-label={`Review ${o.name}`}>Review</Button></td>
              </tr>))}
            </tbody>
          </table>
        </div>
      )}
      {d && <Pagination page={d.page} pages={d.pages} total={d.total} onPage={setPage} label="organizations" />}
      {open && <ReviewModal id={open} onClose={() => setOpen(null)} onChanged={() => list.reload({ silent: true })} />}
    </Layout>
  )
}

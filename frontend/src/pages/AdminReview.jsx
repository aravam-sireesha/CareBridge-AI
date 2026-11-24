import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import ReviewItem, { TYPE_LABELS } from '../components/ReviewItem.jsx'
import { Button, CardSkeleton, EmptyState, ErrorState, PageHeader, Tabs } from '../components/ui.jsx'
import { IconCheck, IconSpark } from '../components/icons.jsx'

export default function AdminReview() {
  const toast = useToast()
  const queue = useAsync(() => api.adminReviewQueue(), [])
  const [tab, setTab] = useState('all')
  const [busy, setBusy] = useState(false)
  const [running, setRunning] = useState(false)

  const decide = async (item, decision) => {
    setBusy(true)
    try { await api.adminDecide(item.type, item.id, decision); toast.success('Decision saved and added to the audit trail.'); queue.reload({ silent: true }) }
    catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  const scan = async () => {
    setRunning(true)
    try {
      const r = await api.adminRunScans()
      toast.success(`AI scans finished: ${r.predicted_needs} predicted need(s), ${r.new_fraud_flags} new fraud flag(s), ${r.donor_suggestions} donor suggestion(s), ${r.resource_proposals} resource proposal(s).`)
      queue.reload({ silent: true })
    } catch (e) { toast.error(e.message) } finally { setRunning(false) }
  }
  const data = queue.data
  const counts = data?.counts || {}
  const tabs = [{ key: 'all', label: `All (${data?.total ?? 0})` }, ...Object.keys(TYPE_LABELS).filter((k) => counts[k]).map((k) => ({ key: k, label: `${TYPE_LABELS[k]} (${counts[k]})` }))]
  const items = (data?.items || []).filter((i) => tab === 'all' || i.type === tab)
  const activeTab = tabs.some((t) => t.key === tab) ? tab : 'all'

  return (
    <Layout title="Review queue">
      <PageHeader icon={IconCheck} tone="sky" title="Review & approve" subtitle="Everything the AI flags or suggests waits here for a person to decide. Every decision is recorded in the audit trail."
        actions={<Button variant="ghost" loading={running} onClick={scan} className="!border-white/40 !bg-white/15 !text-white hover:!bg-white/25"><IconSpark className="h-4 w-4" /> Run all AI scans</Button>} />
      <Tabs tabs={tabs} value={activeTab} onChange={setTab} />
      {queue.error ? <ErrorState message={queue.error} onRetry={queue.reload} /> : queue.loading && !data ? <CardSkeleton rows={3} /> : items.length === 0 ? (
        <EmptyState icon={IconCheck} title="Nothing is waiting for a decision" text="Press “Run all AI scans” to look for new predicted needs, suspicious donations, donor suggestions and resource proposals." />
      ) : <div className="space-y-3">{items.map((i) => <ReviewItem key={i.key} item={i} busy={busy} onDecide={decide} />)}</div>}
    </Layout>
  )
}

import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { ReviewList } from '../components/ReviewList.jsx'
import { Button, CardSkeleton, ErrorState, PageHeader, Tabs, formatMoney, formatDate } from '../components/ui.jsx'
import { IconRefresh, IconShield } from '../components/icons.jsx'

export default function FraudFlags() {
  const toast = useToast()
  const { data, loading, error, reload, setData } = useAsync(() => api.listFraudFlags(), [])
  const [scanning, setScanning] = useState(false)
  const [tab, setTab] = useState('pending')

  const scan = async () => {
    setScanning(true)
    try { const r = await api.scanDonations(); toast.success(`Checked ${r.scanned} new donation${r.scanned === 1 ? '' : 's'}: ${r.new_flags} flagged for review.`); await reload({ silent: true }) }
    catch (e) { toast.error(e.message) } finally { setScanning(false) }
  }
  const decide = (decision) => async (item) => {
    try {
      await api.reviewFraudFlag(item.id, decision)
      setData((rows) => rows.map((r) => (r.flag_id === item.id ? { ...r, status: decision } : r)))
      toast.success(decision === 'confirmed_fraud' ? 'Confirmed as fraud.' : 'Marked as a false positive.')
    } catch (e) { toast.error(e.message) }
  }

  const items = (data || []).map((f) => ({
    id: f.flag_id, score: f.score, status: f.status,
    title: `${formatMoney(f.amount)} · donation #${f.donation_id}`,
    subtitle: `${f.resource_description || 'No description'} · ${formatDate(f.flagged_at)}`,
    reasons: f.reasons || []
  }))
  const pending = items.filter((i) => i.status === 'suggested')
  const reviewed = items.filter((i) => i.status !== 'suggested')

  return (
    <Layout title="Fraud flags">
      <PageHeader icon={IconShield} tone="rose" title="Fraud flags" subtitle="Donations that look unusual. An administrator reviews every flag; nothing is blocked automatically."
        actions={<Button variant="ghost" className="border-white/40 bg-white/95" loading={scanning} onClick={scan}><IconRefresh className="h-4 w-4" /> Scan donations</Button>} />
      <Tabs tabs={[{ key: 'pending', label: `To review (${pending.length})` }, { key: 'reviewed', label: `Reviewed (${reviewed.length})` }]} value={tab} onChange={setTab} />
      {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <CardSkeleton rows={3} /> : (
        <ReviewList items={tab === 'pending' ? pending : reviewed} icon={IconShield} emptyTitle={tab === 'pending' ? 'No donations are flagged' : 'Nothing reviewed yet'}
          emptyText={tab === 'pending' ? 'Press “Scan donations” to screen new donations.' : undefined}
          approveLabel="Confirm fraud" rejectLabel="False positive" onApprove={decide('confirmed_fraud')} onReject={decide('false_positive')} />
      )}
    </Layout>
  )
}

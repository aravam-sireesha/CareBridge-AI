import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { ReviewList } from '../components/ReviewList.jsx'
import { Button, CardSkeleton, ErrorState, PageHeader, Tabs } from '../components/ui.jsx'
import { IconAlert, IconRefresh } from '../components/icons.jsx'

export default function NeedAlerts() {
  const { user } = useAuth()
  const toast = useToast()
  const isAdmin = user.role === 'admin'
  const { data, loading, error, reload, setData } = useAsync(() => api.listNeedAlerts(), [])
  const [scanning, setScanning] = useState(false)
  const [tab, setTab] = useState('pending')

  const scan = async () => {
    setScanning(true)
    try { const res = await api.scanNeeds(); toast.success(`Scan complete: ${res.alerts.length} need(s) need attention.`); await reload({ silent: true }) }
    catch (e) { toast.error(e.message) } finally { setScanning(false) }
  }
  const decide = (decision) => async (item) => {
    try {
      await api.reviewNeedAlert(item.id, decision)
      setData((rows) => rows.map((r) => (r.alert_id === item.id ? { ...r, review_decision: decision } : r)))
      toast.success(decision === 'action_taken' ? 'Marked as actioned.' : 'Alert dismissed.')
    } catch (e) { toast.error(e.message) }
  }

  const items = (data || []).map((a) => ({
    id: a.alert_id, score: a.score, status: a.review_decision || 'flagged',
    title: `${a.need_category || 'Need'} (need #${a.need_id})`,
    subtitle: `Urgency ${a.need_urgency || '–'} · quantity ${a.need_quantity ?? '–'} · ${a.need_status || 'open'}`,
    reasons: a.reasons || []
  }))
  const pending = items.filter((i) => i.status === 'flagged')
  const reviewed = items.filter((i) => i.status !== 'flagged')
  const shown = tab === 'pending' ? pending : reviewed

  return (
    <Layout title="Need alerts">
      <PageHeader icon={IconAlert} tone="amber" title="Need alerts" subtitle="Open needs flagged for high urgency, long waits or unusual quantity."
        actions={isAdmin && <Button variant="ghost" className="border-white/40 bg-white/95" loading={scanning} onClick={scan}><IconRefresh className="h-4 w-4" /> Scan needs</Button>} />
      <Tabs tabs={[{ key: 'pending', label: `Needs attention (${pending.length})` }, { key: 'reviewed', label: `Reviewed (${reviewed.length})` }]} value={tab} onChange={setTab} />
      {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <CardSkeleton rows={3} /> : (
        <ReviewList items={shown} icon={IconAlert} emptyTitle={tab === 'pending' ? 'No needs are flagged' : 'Nothing reviewed yet'}
          emptyText={tab === 'pending' && isAdmin ? 'Press “Scan needs” to check all open needs again.' : undefined}
          readOnly={!isAdmin} approveLabel="Mark actioned" rejectLabel="Dismiss" onApprove={decide('action_taken')} onReject={decide('dismissed')} />
      )}
    </Layout>
  )
}

import React, { useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { SuggestionCard } from '../components/AdminParts.jsx'
import { Button, CardSkeleton, EmptyState, ErrorState, PageHeader, Tabs } from '../components/ui.jsx'
import { IconSpark } from '../components/icons.jsx'

export default function AdminSuggestions() {
  const toast = useToast()
  const { data, loading, error, reload, setData } = useAsync(() => api.adminSuggestions(), [])
  const [tab, setTab] = useState('suggested')
  const [busy, setBusy] = useState(false)
  const [running, setRunning] = useState(false)

  const decide = async (s, decision) => {
    setBusy(true)
    try { await api.adminReviewSuggestion(s.id, decision); setData((rows) => rows.map((r) => (r.id === s.id ? { ...r, status: decision } : r))); toast.success(`Suggestion ${decision}.`) }
    catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }
  const generate = async () => {
    setRunning(true)
    try { const r = await api.adminGenerateSuggestions(); toast.success(`Scanned ${r.needs_scanned} open need(s); ${r.suggestions} suggestion(s) refreshed.`); reload({ silent: true }) }
    catch (e) { toast.error(e.message) } finally { setRunning(false) }
  }
  const rows = data || []
  const groups = { suggested: rows.filter((r) => r.status === 'suggested'), done: rows.filter((r) => ['approved', 'contacted'].includes(r.status)), rejected: rows.filter((r) => r.status === 'rejected') }
  const shown = groups[tab]
  return (
    <Layout title="Donor suggestions">
      <PageHeader icon={IconSpark} tone="violet" title="AI donor suggestions" subtitle="Donors the model recommends for each open need, most urgent first. Your decisions train the model."
        actions={<Button variant="ghost" loading={running} onClick={generate} className="!border-white/40 !bg-white/15 !text-white hover:!bg-white/25"><IconSpark className="h-4 w-4" /> Refresh for all open needs</Button>} />
      <Tabs tabs={[{ key: 'suggested', label: `To review (${groups.suggested.length})` }, { key: 'done', label: `Approved / contacted (${groups.done.length})` }, { key: 'rejected', label: `Rejected (${groups.rejected.length})` }]} value={tab} onChange={setTab} />
      {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <CardSkeleton rows={3} /> : shown.length === 0 ? (
        <EmptyState icon={IconSpark} title={tab === 'suggested' ? 'Nothing waiting for review' : 'Nothing here yet'} text={tab === 'suggested' ? 'Press “Refresh for all open needs”, or open a need on the All needs page.' : undefined} />
      ) : <div className="space-y-3">{shown.map((s) => <SuggestionCard key={s.id} s={s} busy={busy} onDecide={decide} />)}</div>}
    </Layout>
  )
}

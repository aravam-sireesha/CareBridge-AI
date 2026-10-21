import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { ReviewList } from '../components/ReviewList.jsx'
import { Button, CardSkeleton, ErrorState, Field, PageHeader, Tabs } from '../components/ui.jsx'
import { IconHand, IconSpark } from '../components/icons.jsx'

export default function MatchingReview() {
  const { user } = useAuth()
  const toast = useToast()
  const isAdmin = user.role === 'admin'
  const matches = useAsync(() => api.listMatches(), [])
  const needs = useAsync(() => api.listNeeds(), [])
  const [needId, setNeedId] = useState('')
  const [suggesting, setSuggesting] = useState(false)
  const [tab, setTab] = useState('pending')
  const openNeeds = (needs.data || []).filter((n) => ['open', 'pending'].includes((n.status || '').toLowerCase()))
  useEffect(() => { if (!needId && openNeeds.length) setNeedId(String(openNeeds[0].id)) }, [openNeeds, needId])

  const suggest = async () => {
    setSuggesting(true)
    try {
      const res = await api.suggestMatches(needId)
      toast[res.suggestions.length ? 'success' : 'info'](res.suggestions.length ? `${res.suggestions.length} match(es) suggested.` : 'No donor or volunteer fits this need yet.')
      await matches.reload({ silent: true })
    } catch (e) { toast.error(e.message) } finally { setSuggesting(false) }
  }
  const decide = (status) => async (item) => {
    try {
      await api.reviewMatch(item.id, status)
      matches.setData((rows) => rows.map((r) => (r.match_id === item.id ? { ...r, status } : r)))
      toast.success(status === 'confirmed' ? 'Match confirmed.' : 'Match rejected.')
    } catch (e) { toast.error(e.message) }
  }

  const items = (matches.data || []).map((m) => ({
    id: m.match_id, score: m.score, status: m.status,
    title: `${m.donor_name || m.volunteer_name || 'Candidate'} → ${m.need_category || `need #${m.need_id}`}`,
    subtitle: `${m.donor_id ? 'Donor' : 'Volunteer'} · need urgency ${m.need_urgency || '–'}`,
    reasons: m.reasons || []
  }))
  const pending = items.filter((i) => ['suggested', 'pending_review'].includes(i.status))
  const reviewed = items.filter((i) => !['suggested', 'pending_review'].includes(i.status))

  return (
    <Layout title="Matching review">
      <PageHeader icon={IconHand} title="Matching review" subtitle="Donors and volunteers suggested for open needs, with scores and reasons." />
      {isAdmin && (
        <div className="card mb-5 flex flex-wrap items-end gap-3 p-4">
          <Field label="Find matches for need" className="min-w-[16rem] flex-1">
            <select className="field" value={needId} onChange={(e) => setNeedId(e.target.value)} disabled={!openNeeds.length}>
              {!openNeeds.length && <option>No open needs</option>}
              {openNeeds.map((n) => <option key={n.id} value={n.id}>{n.category} · {n.urgency} (#{n.id})</option>)}
            </select>
          </Field>
          <Button loading={suggesting} disabled={!needId} onClick={suggest}><IconSpark className="h-4 w-4" /> Suggest matches</Button>
        </div>
      )}
      <Tabs tabs={[{ key: 'pending', label: `To review (${pending.length})` }, { key: 'reviewed', label: `Decided (${reviewed.length})` }]} value={tab} onChange={setTab} />
      {matches.error ? <ErrorState message={matches.error} onRetry={matches.reload} /> : matches.loading ? <CardSkeleton rows={3} /> : (
        <ReviewList items={tab === 'pending' ? pending : reviewed} icon={IconHand} emptyTitle={tab === 'pending' ? 'No matches waiting' : 'No decisions yet'}
          emptyText={tab === 'pending' && isAdmin ? 'Choose a need above and press “Suggest matches”.' : undefined}
          readOnly={!isAdmin} approveLabel="Confirm" rejectLabel="Reject" onApprove={decide('confirmed')} onReject={decide('rejected')} />
      )}
    </Layout>
  )
}

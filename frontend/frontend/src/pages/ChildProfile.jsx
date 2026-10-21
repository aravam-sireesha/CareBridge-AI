import React from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import { CardSkeleton, ErrorState, PageHeader, Pill, formatDate } from '../components/ui.jsx'
import { IconBriefcase, IconChildren } from '../components/icons.jsx'

export default function ChildProfile() {
  const { id } = useParams()
  const { user } = useAuth()
  const child = useAsync(() => api.getChild(id), [id])
  const recs = useAsync(() => api.listRecommendations(id).catch(() => []), [id])
  const c = child.data
  const fields = c ? [['Age', c.age != null ? `${c.age} years` : '–'], ['Interests', c.interests], ['Skills', c.skills], ['Academic performance', c.academic_performance]] : []

  return (
    <Layout title={c ? `Child #${c.id}` : 'Child profile'}>
      <PageHeader icon={IconChildren} title={c ? `Child #${c.id}` : 'Child profile'} subtitle="Profile details and career guidance history."
        actions={<Link to={`/ai/career?child=${id}`} className="btn bg-white/95 text-teal-700 hover:bg-white"><IconBriefcase className="h-4 w-4" /> Career guidance</Link>} />
      {child.error ? <ErrorState message={child.error} onRetry={child.reload} /> : child.loading ? <CardSkeleton rows={3} /> : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            {fields.map(([l, v]) => <div key={l} className="card p-5"><p className="text-xs font-semibold text-ink-muted">{l}</p><p className="mt-1.5 text-[15px] font-medium text-ink">{v || '–'}</p></div>)}
          </div>
          <h2 className="mb-3 mt-8 font-display text-base font-semibold">Career recommendations</h2>
          {recs.loading ? <CardSkeleton rows={1} /> : !recs.data?.length ? <div className="card p-6 text-sm text-ink-muted">No recommendations yet. {user.role === 'admin' ? 'Open career guidance to generate them.' : ''}</div> : (
            <div className="space-y-3">{recs.data.map((r) => (
              <div key={r.recommendation_id} className="card flex flex-wrap items-center justify-between gap-3 p-4">
                <div className="flex flex-wrap gap-2">{r.candidates.map((x) => <Pill key={x} tone={r.feedback?.chosen_career === x ? 'green' : 'violet'}>{x}</Pill>)}</div>
                <div className="flex items-center gap-3 text-xs text-ink-muted">{formatDate(r.created_at)}<StatusBadge status={r.feedback?.decision || 'suggested'} /></div>
              </div>))}</div>
          )}
        </>
      )}
    </Layout>
  )
}

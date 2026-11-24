import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import ForecastPanel from '../components/ForecastPanel.jsx'
import { HealthCard } from '../components/LiveAnalysis.jsx'
import { Reasons, ScoreBar } from '../components/AdminParts.jsx'
import { Button, CardSkeleton, EmptyState, ErrorState, Field, PageHeader, Pill, Section } from '../components/ui.jsx'
import { IconSpark } from '../components/icons.jsx'

const KINDS = [['organization', 'Organization'], ['need', 'Need'], ['donor', 'Donor'], ['volunteer', 'Volunteer']]
const SECTION_TITLES = {
  need: { donors: 'Best donors', volunteers: 'Best volunteers', resources: 'Resources that fit', organizations: 'Partner organizations holding resources' },
  donor: { needs: 'Needs this donor should support', organizations: 'Organizations to support' },
  volunteer: { needs: 'Needs this volunteer can help with', organizations: 'Organizations to join' },
  organization: { needs: 'Needs in priority order', donors: 'Best donors for these needs', volunteers: 'Best volunteers for these needs', resources: 'Resources that could be allocated' }
}
const ORDER = ['needs', 'donors', 'volunteers', 'resources', 'organizations']
const EXPLORE = new Set(['organization', 'need', 'donor', 'volunteer'])

function Suggestion({ item, onExplore }) {
  return (
    <div className="card p-3.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0"><p className="text-sm font-semibold text-ink">{item.label}</p>{item.sublabel && <p className="mt-0.5 text-xs text-ink-muted">{item.sublabel}</p>}</div>
        <div className="flex shrink-0 items-center gap-1.5">{item.extra?.verified === false && <Pill tone="amber">unverified</Pill>}{EXPLORE.has(item.kind) && <button type="button" onClick={() => onExplore(item.kind, item.id)} className="rounded-full bg-teal-50 px-2.5 py-1 text-[11px] font-bold text-teal-700 hover:bg-teal-100" aria-label={`Explore ${item.label}`}>Explore</button>}</div>
      </div>
      <div className="mt-2"><ScoreBar label="Score" value={item.score} tone={item.kind === 'need' ? 'rose' : 'teal'} /></div>
      <Reasons items={item.reasons} />
    </div>
  )
}

export default function AdminHub() {
  const toast = useToast()
  const entities = useAsync(() => api.adminEntities(), [])
  const [kind, setKind] = useState('need')
  const [id, setId] = useState('')
  const [state, setState] = useState({ loading: false, error: '', data: null })
  const [sending, setSending] = useState(false)

  const options = entities.data?.[kind] || []
  useEffect(() => { if (options.length && !options.some((o) => String(o.id) === String(id))) setId(String(options[0].id)) }, [kind, entities.data]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!id) return undefined
    let alive = true
    setState({ loading: true, error: '', data: null })
    api.adminRecommend(kind, id, 5).then((data) => alive && setState({ loading: false, error: '', data })).catch((e) => alive && setState({ loading: false, error: e.message, data: null }))
    return () => { alive = false }
  }, [kind, id])

  const explore = (k, i) => { setKind(k); setId(String(i)) }
  const send = async () => {
    setSending(true)
    try {
      const results = await Promise.allSettled([api.adminSuggestDonors(id, 5), api.adminSuggestVolunteers(id, 5), api.adminSuggestResources(id)])
      const failed = results.find((r) => r.status === 'rejected')
      if (failed) throw new Error(failed.reason?.message || 'Could not save suggestions')
      toast.success('Suggestions were added to the review queue.')
    } catch (e) { toast.error(e.message) } finally { setSending(false) }
  }

  const d = state.data
  const titles = SECTION_TITLES[kind] || {}
  return (
    <Layout title="AI suggestion hub">
      <PageHeader icon={IconSpark} tone="violet" title="AI suggestion hub" subtitle="Pick any organization, need, donor or volunteer. The AI suggests the best related organizations, needs, donors, volunteers and resources, with reasons." />
      <div className="card mb-6 p-4">
        <div role="tablist" aria-label="What do you want suggestions for?" className="mb-4 inline-flex rounded-xl bg-teal-50 p-1">
          {KINDS.map(([k, label]) => <button key={k} role="tab" aria-selected={kind === k} type="button" onClick={() => setKind(k)} className={`rounded-lg px-4 py-1.5 text-sm font-semibold transition ${kind === k ? 'bg-white text-teal-700 shadow-card' : 'text-ink-muted hover:text-teal-700'}`}>{label}</button>)}
        </div>
        <Field label={`Choose a ${kind}`}>
          <select className="field" value={id} onChange={(e) => setId(e.target.value)} aria-label={`Choose a ${kind}`}>{options.length === 0 && <option value="">None available</option>}{options.map((o) => <option key={o.id} value={o.id}>{o.label}{o.sublabel ? `, ${o.sublabel}` : ''}</option>)}</select>
        </Field>
      </div>

      {entities.error ? <ErrorState message={entities.error} onRetry={entities.reload} /> : state.error ? <ErrorState message={state.error} /> : state.loading || entities.loading ? <CardSkeleton rows={3} /> : !d ? (
        <EmptyState icon={IconSpark} title={`No ${kind} to analyse yet`} text="Add records first, then come back for suggestions." />
      ) : (
        <>
          <div className="card mb-6 flex flex-wrap items-center justify-between gap-3 p-4">
            <div><Pill tone="violet" className="mb-1 capitalize">{d.entity.kind}</Pill><p className="font-display text-lg font-semibold text-ink">{d.entity.label}</p><p className="text-sm text-ink-muted">{d.entity.sublabel}</p></div>
            {d.entity.kind === 'need' && <Button loading={sending} onClick={send}><IconSpark className="h-4 w-4" /> Send suggestions to review queue</Button>}
          </div>
          {d.health && <div className="mb-6 max-w-2xl"><HealthCard h={d.health} compact /></div>}
          <div className="space-y-8">
            {ORDER.filter((k) => d.sections[k]).map((k) => (
              <Section key={k} title={titles[k] || k}>
                {d.sections[k].length === 0 ? <p className="card p-4 text-sm text-ink-muted">Nothing suitable yet.</p> : <div className="grid gap-3 md:grid-cols-2">{d.sections[k].map((it) => <Suggestion key={`${it.kind}-${it.id}`} item={it} onExplore={explore} />)}</div>}
              </Section>
            ))}
            <Section title="Predicted demand for the related categories"><ForecastPanel items={d.forecast} /></Section>
          </div>
        </>
      )}
    </Layout>
  )
}

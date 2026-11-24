import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { useToast } from '../context/ToastContext.jsx'
import { useAsync } from '../hooks/useAsync.js'
import Layout from '../components/Layout.jsx'
import { LevelPill, ScoreBar } from '../components/AdminParts.jsx'
import { Button, CardSkeleton, ErrorState, PageHeader, Section, StatCard } from '../components/ui.jsx'
import { IconAlert, IconBuilding, IconDonations, IconKey, IconNeeds, IconSpark } from '../components/icons.jsx'


export function OverviewBody({ data, loading, error, reload }) {
  const t = data?.totals
  const m = data?.model
  const progress = m ? Math.min(1, (m.reviewed_rows || 0) / (m.needed || 20)) : 0
  return (
    <>
    {error ? <ErrorState message={error} onRetry={reload} /> : loading ? <CardSkeleton rows={3} /> : (
      <>
        <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <StatCard label="Organizations" value={t.organizations} hint={`${t.unverified_organizations} waiting for verification`} icon={IconBuilding} tone="teal" to="/admin/organizations" />
          <StatCard label="Open needs" value={t.open_needs} hint={`${t.critical_needs} critical or high`} icon={IconNeeds} tone="amber" />
          <StatCard label="Donors" value={t.donors} icon={IconDonations} tone="rose" />
          <StatCard label="Suggestions to review" value={t.suggestions_waiting} hint="AI recommends, you decide" icon={IconSpark} tone="violet" />
          <StatCard label="Critical / high" value={t.critical_needs} hint="by ML priority score" icon={IconAlert} tone="red" />
          <StatCard label="All needs" value={t.needs} icon={IconNeeds} tone="sky" />
        </div>

        <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          <Section title="Needs that need attention first" action={<Link to="/admin/needs" className="text-sm font-semibold text-sky-600 hover:underline">See all needs</Link>}>
            <div className="space-y-3">
              {data.top_needs.length === 0 && <p className="card p-6 text-center text-sm text-ink-muted">No open needs right now.</p>}
              {data.top_needs.map((n) => (
                <div key={n.id} className="card p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div><p className="text-sm font-semibold text-ink">{n.category || `Need ${n.id}`}</p><p className="text-xs text-ink-muted">{n.organization_name || 'Unknown organization'} · quantity {n.quantity ?? '–'}</p></div>
                    <LevelPill level={n.priority_level} />
                  </div>
                  <div className="mt-3"><ScoreBar label="AI priority" value={n.priority_score} tone="rose" /></div>
                  <p className="mt-2 text-xs text-ink-muted">{n.priority_reasons.join(' · ')}{n.suggestion_count ? ` · ${n.suggestion_count} donor suggestion(s)` : ' · no donors suggested yet'}</p>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Donor-matching model">
            <div className="card p-5">
              <p className="font-display text-lg font-semibold text-teal-800">{m.model_version}</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-muted">{m.description}</p>
              <div className="mt-4"><ScoreBar label={`Learning from your decisions (${m.reviewed_rows}/${m.needed})`} value={progress} tone="sky" /></div>
              <p className="mt-2 text-xs text-ink-muted">{m.mode === 'learned' ? 'The model now blends what you approved and rejected with its rules.' : `Rule-based until ${m.needed} reviewed suggestions exist, then it learns from them.`}</p>
              {m.coefficients && <div className="mt-3 flex flex-wrap gap-1.5">{Object.entries(m.coefficients).map(([k, v]) => <span key={k} className="rounded-full bg-teal-50 px-2.5 py-1 text-[11px] font-semibold text-teal-700">{k.replace('_', ' ')} {v > 0 ? '+' : ''}{v}</span>)}</div>}
            </div>
          </Section>
        </div>
      </>
    )}
    </>
  )
}

export default function AdminOverview() {
  const toast = useToast()
  const { data, loading, error, reload } = useAsync(() => api.adminOverview(), [])
  const [running, setRunning] = useState(false)

  const generate = async () => {
    setRunning(true)
    try {
      const r = await api.adminGenerateSuggestions()
      toast.success(`Scanned ${r.needs_scanned} open need(s) and prepared ${r.suggestions} donor suggestion(s).`)
      reload({ silent: true })
    } catch (e) { toast.error(e.message) } finally { setRunning(false) }
  }

  return (
    <Layout title="Overview & AI model">
      <PageHeader icon={IconKey} title="Overview & AI model" subtitle="Every organization's needs in one place, ranked by AI urgency, with donor suggestions you approve."
        actions={<Button variant="ghost" loading={running} onClick={generate} className="!border-white/40 !bg-white/15 !text-white hover:!bg-white/25"><IconSpark className="h-4 w-4" /> Run AI donor suggestions</Button>} />
      <OverviewBody data={data} loading={loading} error={error} reload={reload} />
    </Layout>
  )
}
